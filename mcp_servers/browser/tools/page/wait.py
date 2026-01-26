"""
Smart waiting for browser conditions.

Provides wait_for function for navigation, load, text, element presence.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session
from ..shadow_dom import DEEP_QUERY_JS


def wait_for(
    config: BrowserConfig, condition: str, timeout: float = 10.0, text: str | None = None, selector: str | None = None
) -> dict[str, Any]:
    """
    Wait for a condition before proceeding.

    Args:
        config: Browser configuration
        condition: What to wait for:
            - "navigation": Page URL change
            - "load": Page fully loaded (document.readyState == 'complete')
            - "domcontentloaded": DOM ready (document.readyState != 'loading')
            - "text": Specific text appears on page
            - "element": Element matching selector appears
            - "networkidle": No network activity for 500ms (alias: network_idle)
        timeout: Maximum wait time in seconds
        text: Text to wait for (when condition="text")
        selector: CSS selector (when condition="element")

    Returns:
        Dictionary with success status, elapsed time, and condition details
    """
    condition = _normalize_condition(condition)

    valid_conditions = ["navigation", "load", "domcontentloaded", "text", "element", "networkidle"]
    if condition not in valid_conditions:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason=f"Invalid condition: {condition}",
            suggestion=f"Use one of: {', '.join(valid_conditions)}",
        )

    if condition == "text" and not text:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="text parameter required for condition='text'",
            suggestion="Provide text='expected text'",
        )

    if condition == "element" and not selector:
        raise SmartToolError(
            tool="wait_for",
            action="validate",
            reason="selector parameter required for condition='element'",
            suggestion="Provide selector='css selector'",
        )

    toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
    is_v2 = toolset in {"v2", "northstar", "north-star"}
    dialog_suggestion = (
        "Handle the dialog first: run(actions=[{dialog:{accept:true}}])"
        if is_v2
        else "Handle the dialog first: dialog(accept=true|false, text='...')"
    )

    # Cross-call robustness: if Tier-0 telemetry says a dialog is currently open,
    # fail fast without attempting any CDP commands that may time out/hang.
    try:
        tab_id = session_manager.tab_id
        if isinstance(tab_id, str) and tab_id:
            t0 = session_manager.get_telemetry(tab_id)
            if t0 is not None and getattr(t0, "dialog_open", False):
                meta = getattr(t0, "dialog_last", None)
                dialog = meta if isinstance(meta, dict) else {}
                return {
                    "success": False,
                    "condition": condition,
                    "elapsed": 0.0,
                    "reason": "dialog_open",
                    "dialog": {"type": dialog.get("type"), "message": dialog.get("message"), "url": dialog.get("url")},
                    "suggestion": dialog_suggestion,
                    "target": tab_id,
                }
    except Exception:
        pass

    # Waiting should be resilient and low-flake; do not require Tier-1 diagnostics injection here.
    with get_session(config, ensure_diagnostics=False) as (session, target):
        start_time = time.time()

        def pop_dialog() -> dict[str, Any] | None:
            try:
                params = session.conn.pop_event("Page.javascriptDialogOpening")  # type: ignore[attr-defined]
                return params if isinstance(params, dict) else None
            except Exception:
                return None

        # Some waits can be implemented without Runtime.evaluate (important when dialogs block JS).
        if condition in {"load", "domcontentloaded"}:
            event_name = "Page.loadEventFired" if condition == "load" else "Page.domContentEventFired"
            deadline = start_time + timeout
            while time.time() < deadline:
                remaining = max(0.0, deadline - time.time())
                # Pump events with a small timeout so we can also detect dialogs.
                try:
                    ev = session.conn.wait_for_event(event_name, timeout=min(0.3, remaining))  # type: ignore[attr-defined]
                except Exception:
                    ev = None
                if ev is not None:
                    return {
                        "success": True,
                        "condition": condition,
                        "elapsed": round(time.time() - start_time, 2),
                        "target": target["id"],
                    }
                if dlg := pop_dialog():
                    return {
                        "success": False,
                        "condition": condition,
                        "elapsed": round(time.time() - start_time, 2),
                        "reason": "dialog_open",
                        "dialog": {
                            "type": dlg.get("type"),
                            "message": dlg.get("message"),
                            "url": dlg.get("url"),
                        },
                        "suggestion": dialog_suggestion,
                        "target": target["id"],
                    }

            return {
                "success": False,
                "condition": condition,
                "timeout": timeout,
                "elapsed": round(time.time() - start_time, 2),
                "suggestion": f"Condition '{condition}' not met within {timeout}s",
                "target": target["id"],
            }

        start_url: str | None = None
        start_loader_id: str | None = None
        start_ts_ms = int(time.time() * 1000)
        if condition == "navigation":
            # Prefer CDP history (no JS eval).
            try:
                nav = session.send("Page.getNavigationHistory")
                if isinstance(nav, dict):
                    idx = nav.get("currentIndex")
                    entries = nav.get("entries")
                    if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                        cur = entries[idx] if isinstance(entries[idx], dict) else None
                        if isinstance(cur, dict) and isinstance(cur.get("url"), str):
                            start_url = cur.get("url")
            except Exception:
                start_url = None
            if not start_url:
                try:
                    start_url = session.eval_js("window.location.href")
                except Exception:
                    start_url = None

            # Also capture a top-frame loaderId baseline (ironclad commit detection even if URL
            # ends up the same or history APIs are flaky).
            try:
                tree = session.send("Page.getFrameTree")
                frame = None
                if isinstance(tree, dict):
                    ft = tree.get("frameTree")
                    if isinstance(ft, dict):
                        frame = ft.get("frame")
                if isinstance(frame, dict):
                    lid = frame.get("loaderId")
                    if isinstance(lid, str) and lid:
                        start_loader_id = lid
                    if not start_url and isinstance(frame.get("url"), str) and frame.get("url"):
                        start_url = frame.get("url")
            except Exception:
                start_loader_id = None

            # Heuristic: consider very recent Tier-0 navigation events as success even if
            # the URL has already changed by the time wait() starts (common race when
            # calling wait(navigation) right after click(wait_after="none")).
            # Use a slightly wider window to cover real-world scheduling delays between tool calls.
            since_ms = max(0, start_ts_ms - 10_000)

            deadline = start_time + timeout
            while time.time() < deadline:
                remaining = max(0.0, deadline - time.time())

                if dlg := pop_dialog():
                    return {
                        "success": False,
                        "condition": condition,
                        "elapsed": round(time.time() - start_time, 2),
                        "reason": "dialog_open",
                        "dialog": {"type": dlg.get("type"), "message": dlg.get("message"), "url": dlg.get("url")},
                        "suggestion": dialog_suggestion,
                        "target": target["id"],
                    }

                # Tier-0 fast-path: if navigation committed very recently, return success.
                try:
                    tab_id = session.tab_id
                    if isinstance(tab_id, str) and tab_id:
                        snap = session_manager.tier0_snapshot(tab_id, since=since_ms, offset=0, limit=3)
                        nav_events = snap.get("navigation") if isinstance(snap, dict) else None
                        if isinstance(nav_events, list) and nav_events:
                            last = nav_events[-1] if isinstance(nav_events[-1], dict) else None
                            new_url = last.get("url") if isinstance(last, dict) else None
                            if isinstance(new_url, str) and new_url:
                                return {
                                    "success": True,
                                    "condition": condition,
                                    "elapsed": round(time.time() - start_time, 2),
                                    "old_url": start_url,
                                    "new_url": new_url,
                                    "target": target["id"],
                                    "note": "detected via tier0 navigation events",
                                }
                except Exception:
                    pass

                # Prefer top-frame commit events (cheap, robust, no JS eval).
                ev = None
                try:
                    ev = session.conn.wait_for_event(  # type: ignore[attr-defined]
                        "Page.frameNavigated",
                        timeout=min(0.3, remaining),
                    )
                except Exception:
                    ev = None

                if isinstance(ev, dict):
                    frame = ev.get("frame")
                    if isinstance(frame, dict):
                        parent_id = frame.get("parentId")
                        if not parent_id:
                            new_url = frame.get("url")
                            return {
                                "success": True,
                                "condition": condition,
                                "elapsed": round(time.time() - start_time, 2),
                                "old_url": start_url,
                                "new_url": new_url,
                                "target": target["id"],
                            }

                # SPA (pushState/hash) navigations.
                spa = None
                try:
                    spa = session.conn.pop_event("Page.navigatedWithinDocument")  # type: ignore[attr-defined]
                except Exception:
                    spa = None
                if isinstance(spa, dict) and isinstance(spa.get("url"), str) and spa.get("url"):
                    return {
                        "success": True,
                        "condition": condition,
                        "elapsed": round(time.time() - start_time, 2),
                        "old_url": start_url,
                        "new_url": spa.get("url"),
                        "target": target["id"],
                    }

                # Fallback: if events are missing, still detect via URL polling.
                try:
                    res = _check_condition(
                        session,
                        target,
                        condition,
                        time.time() - start_time,
                        start_url,
                        text,
                        selector,
                        start_loader_id=start_loader_id,
                    )
                    if res:
                        return res
                except Exception:
                    pass

                time.sleep(0.05)

            return {
                "success": False,
                "condition": condition,
                "timeout": timeout,
                "elapsed": round(time.time() - start_time, 2),
                "suggestion": f"Condition '{condition}' not met within {timeout}s",
                "target": target["id"],
            }

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time

            if dlg := pop_dialog():
                return {
                    "success": False,
                    "condition": condition,
                    "elapsed": round(elapsed, 2),
                    "reason": "dialog_open",
                    "dialog": {"type": dlg.get("type"), "message": dlg.get("message"), "url": dlg.get("url")},
                    "suggestion": dialog_suggestion,
                    "target": target["id"],
                }

            result = _check_condition(session, target, condition, elapsed, start_url, text, selector)
            if result:
                return result

            time.sleep(0.15)

        return {
            "success": False,
            "condition": condition,
            "timeout": timeout,
            "elapsed": round(time.time() - start_time, 2),
            "suggestion": f"Condition '{condition}' not met within {timeout}s",
            "target": target["id"],
        }


def _check_condition(
    session: Any,
    target: dict[str, Any],
    condition: str,
    elapsed: float,
    start_url: str | None,
    text: str | None,
    selector: str | None,
    *,
    start_loader_id: str | None = None,
) -> dict[str, Any] | None:
    """Check a single wait condition. Returns result dict if met, None otherwise."""
    if condition == "navigation":
        current_url: str | None = None
        current_loader_id: str | None = None

        # Prefer frame tree commit info (more reliable than history APIs).
        try:
            tree = session.send("Page.getFrameTree")
            frame = None
            if isinstance(tree, dict):
                ft = tree.get("frameTree")
                if isinstance(ft, dict):
                    frame = ft.get("frame")
            if isinstance(frame, dict):
                url = frame.get("url")
                lid = frame.get("loaderId")
                if isinstance(url, str) and url:
                    current_url = url
                if isinstance(lid, str) and lid:
                    current_loader_id = lid
        except Exception:
            current_url = None
            current_loader_id = None

        # Fallback: CDP history (no JS eval).
        try:
            if current_url is None:
                nav = session.send("Page.getNavigationHistory")
                if isinstance(nav, dict):
                    idx = nav.get("currentIndex")
                    entries = nav.get("entries")
                    if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                        cur = entries[idx] if isinstance(entries[idx], dict) else None
                        if isinstance(cur, dict) and isinstance(cur.get("url"), str):
                            current_url = cur.get("url")
        except Exception:
            pass

        # Last resort: JS URL polling.
        if current_url is None:
            try:
                current_url = session.eval_js("window.location.href")
            except Exception:
                current_url = None

        # LoaderId is an ironclad commit signal (changes on real navigations).
        if start_loader_id and current_loader_id and current_loader_id != start_loader_id:
            return {
                "success": True,
                "condition": condition,
                "elapsed": round(elapsed, 2),
                "old_url": start_url,
                "new_url": current_url,
                "target": target["id"],
                "note": "detected via Page.getFrameTree (loaderId)",
            }

        if current_url and start_url and current_url != start_url:
            return {
                "success": True,
                "condition": condition,
                "elapsed": round(elapsed, 2),
                "old_url": start_url,
                "new_url": current_url,
                "target": target["id"],
            }

    elif condition == "text" and text:
        js = f"""
        (() => {{
            {DEEP_QUERY_JS}
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const needle = norm({json.dumps(text)});
            if (!needle) return false;
            let root = document.body;
            const sel = {json.dumps(selector)};
            if (sel && typeof sel === 'string') {{
                try {{
                    const nodes = __mcpQueryAllDeep(sel, 5);
                    if (nodes && nodes.length) root = nodes[0];
                }} catch (e) {{}}
            }}
            if (!root) return false;
            let hay = '';
            try {{ hay = String(root.innerText || ''); }} catch (e) {{}}
            if (!hay) {{
                try {{ hay = String(root.textContent || ''); }} catch (e) {{}}
            }}
            return norm(hay).includes(needle);
        }})()
        """
        try:
            found = session.eval_js(js)
        except Exception:
            found = False
        if found:
            return {
                "success": True,
                "condition": condition,
                "text": text,
                **({"selector": selector} if selector else {}),
                "elapsed": round(elapsed, 2),
                "target": target["id"],
            }

    elif condition == "element" and selector:
        js = f"(() => {{ {DEEP_QUERY_JS} const nodes = __mcpQueryAllDeep({json.dumps(selector)}, 5); return nodes.length > 0; }})()"
        try:
            found = session.eval_js(js)
        except Exception:
            found = False
        if found:
            return {
                "success": True,
                "condition": condition,
                "selector": selector,
                "found": True,
                "elapsed": round(elapsed, 2),
                "target": target["id"],
            }

    elif condition == "networkidle":
        js = """
        (() => {
            if (!window._networkIdleTracker) {
                window._networkIdleTracker = { count: 0, lastActivity: Date.now() };
                const observer = new PerformanceObserver((list) => {
                    window._networkIdleTracker.count++;
                    window._networkIdleTracker.lastActivity = Date.now();
                });
                observer.observe({ entryTypes: ['resource'] });
            }
            return Date.now() - window._networkIdleTracker.lastActivity > 500;
        })()
        """
        try:
            is_idle = session.eval_js(js)
        except Exception:
            is_idle = False
        if is_idle:
            return {"success": True, "condition": condition, "elapsed": round(elapsed, 2), "target": target["id"]}

    return None


def _normalize_condition(condition: str) -> str:
    """Normalize common condition aliases for compatibility."""
    c = (condition or "").strip().lower()
    if c in {"network_idle", "network-idle", "network idle", "networkidle"}:
        return "networkidle"
    if c in {"domcontentloaded", "dom_content_loaded", "dom-content-loaded"}:
        return "domcontentloaded"
    return c
