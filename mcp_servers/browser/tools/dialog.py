"""
Dialog handling tools for JavaScript alerts, confirms, and prompts.

Provides:
- handle_dialog: Accept or dismiss JS dialogs
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from ..config import BrowserConfig
from ..http_client import HttpClientError
from ..session import session_manager
from .base import SmartToolError, get_session


def handle_dialog(
    config: BrowserConfig,
    accept: bool = True,
    prompt_text: str | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Handle JavaScript alert/confirm/prompt dialogs.

    Call when a dialog is blocking the page.

    Args:
        config: Browser configuration
        accept: True to accept/OK, False to dismiss/cancel
        prompt_text: Text to enter for prompt() dialogs
        timeout: Max seconds to wait for a dialog to appear when none is active

    Returns:
        Dict with accept status, prompt_text if provided, and target ID.

        If no dialog is currently open, returns a non-error payload:
        {"handled": false, "reason": "no_dialog", ...}
    """

    # IMPORTANT: JS dialogs block the page's JS thread; Runtime.evaluate may hang until the
    # dialog is handled. Avoid Tier-1 diagnostics injection here to prevent tool timeouts.
    # Also avoid Page.enable here. Cross-call dialog handling is the most fragile path:
    # the dialog is already open and some CDP domains may stop responding reliably.
    def _is_no_dialog_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "no dialog" in msg
            or "dialog is not showing" in msg
            or "no javascript dialog" in msg
            or "no javascript dialog is showing" in msg
        )

    def _is_cdp_timeout(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "cdp response timed out" in msg or ("timed out" in msg and "cdp" in msg)

    def _best_effort_dialog_meta(tab_id: str | None) -> dict[str, Any] | None:
        if not isinstance(tab_id, str) or not tab_id:
            return None
        try:
            t0 = session_manager.get_telemetry(tab_id)
            meta = getattr(t0, "dialog_last", None) if t0 is not None else None
            if isinstance(meta, dict) and meta:
                return meta
        except Exception:
            return None
        return None

    def _attempt(*, conn_timeout: float) -> dict[str, Any]:
        with get_session(
            config,
            timeout=conn_timeout,
            ensure_diagnostics=False,
            ensure_telemetry=False,
            enable_page=False,
        ) as (session, target):
            try:
                try:
                    timeout_s = float(timeout)
                except Exception:
                    timeout_s = 0.0
                timeout_s = max(0.0, min(timeout_s, 30.0))

                params: dict[str, Any] = {"accept": accept}
                if prompt_text is not None:
                    params["promptText"] = prompt_text

                # Best-effort: enabling Page can make dialog handling more reliable across calls.
                # Never fail if this hangs/errors: dialog is already open and CDP can be fragile here.
                with suppress(Exception):
                    session.enable_page()

                tab_id = session.tab_id
                opened = _best_effort_dialog_meta(tab_id)

                # If Tier-0 telemetry believes a dialog is open, treat "no dialog" from CDP as a
                # stale-state signal and clear it. This avoids returning handled=false with
                # dialogOpen=true snapshots.
                expected_open = False
                try:
                    t0 = session_manager.get_telemetry(tab_id)
                    expected_open = bool(getattr(t0, "dialog_open", False)) if t0 is not None else False
                except Exception:
                    expected_open = False

                # Fast-path: try to handle immediately.
                try:
                    session.send("Page.handleJavaScriptDialog", params)
                    handled = True
                except Exception as exc:
                    if not _is_no_dialog_error(exc):
                        raise

                    # Optionally wait briefly for a dialog to open (common right after a click).
                    handled = False
                    if timeout_s > 0:
                        deadline = time.time() + timeout_s
                        while time.time() < deadline:
                            try:
                                session.send("Page.handleJavaScriptDialog", params)
                                handled = True
                                break
                            except Exception as exc2:
                                if not _is_no_dialog_error(exc2):
                                    raise
                            time.sleep(0.1)

                if not handled:
                    if expected_open:
                        # Clear local dialog-open state (best-effort) so future tool calls do not
                        # keep failing fast on a dialog that is no longer present.
                        with suppress(Exception):
                            session_manager.note_dialog_closed(tab_id)
                        # IMPORTANT: a dialog-open event can still brick CDP even if the dialog is
                        # already gone by the time we attempt to handle it. Treat this as "handled"
                        # but continue with the same post-health checks/recovery as the normal path.
                        handled = True
                        stale_state_cleared = True
                    else:
                        return {
                            "handled": False,
                            "reason": "no_dialog",
                            "accepted": accept,
                            **({"promptText": prompt_text} if prompt_text is not None else {}),
                            **({"waited_s": timeout_s} if timeout_s > 0 else {}),
                            "target": target["id"],
                            **({"dialog": opened} if isinstance(opened, dict) and opened else {}),
                        }
                else:
                    stale_state_cleared = False

                # Keep Tier-0 dialog state consistent across calls (the "closed" event is not
                # guaranteed to arrive on the same connection in dialog-brick scenarios).
                if not stale_state_cleared:
                    with suppress(Exception):
                        session_manager.note_dialog_closed(tab_id, accepted=bool(accept), user_input=prompt_text)

                # Best-effort: re-enable core domains after handling.
                # Some Chrome builds can end up in a fragile state after a modal dialog.
                with suppress(Exception):
                    session.enable_page()
                with suppress(Exception):
                    session.enable_runtime()

                # Post-check: some dialog scenarios leave the tab/target in a "CDP brick" state
                # (commands start timing out even though the dialog was handled). If detected,
                # do a best-effort soft heal by switching to a fresh tab without restarting Chrome.
                recovered: dict[str, Any] | None = None
                restore_url: str | None = None
                # Prefer restoring the page where the dialog originated (if known).
                if isinstance(opened, dict) and isinstance(opened.get("url"), str) and opened.get("url"):
                    restore_url = opened.get("url")

                nav_timeout = False
                try:
                    nav = session.send("Page.getNavigationHistory")
                    if isinstance(nav, dict):
                        idx = nav.get("currentIndex")
                        entries = nav.get("entries")
                        if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                            cur = entries[idx] if isinstance(entries[idx], dict) else None
                            if isinstance(cur, dict) and isinstance(cur.get("url"), str) and cur.get("url"):
                                restore_url = cur.get("url")
                except Exception as exc:
                    nav_timeout = _is_cdp_timeout(exc)

                def _runtime_smoke(sess: Any) -> tuple[bool, bool]:
                    """Return (ok, timeout) for a cheap deterministic Runtime smoke check."""
                    ok = False
                    timeout_hit = False
                    try:
                        # Keep dialog() cross-call cheap and bounded: the caller is blocked on a modal
                        # and every extra second is pure cognitive tax.
                        #
                        # We do *at most* a couple of attempts and only retry on CDP timeouts.
                        attempts = 0
                        while attempts < 2:
                            attempts += 1
                            try:
                                with suppress(Exception):
                                    sess.enable_runtime()
                                sess.eval_js("1", timeout=0.8)  # cheap, deterministic
                                ok = True
                                break
                            except Exception as exc3:  # noqa: BLE001
                                if _is_cdp_timeout(exc3):
                                    timeout_hit = True
                                    time.sleep(0.05)
                                    continue
                                break
                    except Exception:
                        ok = False
                    return ok, timeout_hit

                # Stronger health-check: Runtime may still be bricked even when Page domain responds.
                runtime_ok, runtime_timeout = _runtime_smoke(session)
                runtime_failed = not bool(runtime_ok)

                # Cross-call guard: verify the tab is healthy for a *fresh* tool call.
                # (Some dialog bricks only show up on the next connection.)
                fresh_runtime_ok = True
                fresh_runtime_timeout = False
                try:
                    with get_session(
                        config,
                        timeout=1.5,
                        ensure_diagnostics=False,
                        # Simulate typical next-call setup more closely (Tier-0 on).
                        ensure_telemetry=True,
                        enable_page=False,
                    ) as (fresh, _t2):
                        try:
                            fresh_runtime_ok, fresh_runtime_timeout = _runtime_smoke(fresh)
                        except Exception as exc:  # noqa: BLE001
                            fresh_runtime_ok = False
                            fresh_runtime_timeout = _is_cdp_timeout(exc)
                except Exception as exc:
                    fresh_runtime_ok = False
                    fresh_runtime_timeout = _is_cdp_timeout(exc)

                if (nav_timeout or runtime_timeout or runtime_failed) and recovered is None:
                    # Best-effort: close the bricked tab, open a fresh one, switch session.
                    try:
                        # Clear local caches/buses so the next tool call doesn't reuse stale state.
                        # This is safe even if Chrome is in a bad state (no CDP calls inside).
                        recovered_reset: dict[str, Any] | None = None
                        with suppress(Exception):
                            rr = session_manager.recover_reset()
                            recovered_reset = rr if isinstance(rr, dict) else None
                        with suppress(Exception):
                            if isinstance(tab_id, str) and tab_id:
                                session_manager.close_tab(config, tab_id)
                        new_id = session_manager.new_tab(config, restore_url or "about:blank")
                        recovered = {
                            "mode": "soft",
                            "ok": True,
                            "sessionTabId": new_id,
                            **({"restoredUrl": restore_url} if restore_url else {}),
                            "runtimeOk": False,
                            **({"reset": recovered_reset} if isinstance(recovered_reset, dict) else {}),
                        }
                    except Exception as exc2:
                        recovered = {"mode": "soft", "ok": False, "error": str(exc2)}

                # If the next-call health check says we're bricked, try the same soft heal.
                if (fresh_runtime_timeout or (not fresh_runtime_ok)) and recovered is None:
                    try:
                        recovered_reset: dict[str, Any] | None = None
                        with suppress(Exception):
                            rr = session_manager.recover_reset()
                            recovered_reset = rr if isinstance(rr, dict) else None
                        with suppress(Exception):
                            if isinstance(tab_id, str) and tab_id:
                                session_manager.close_tab(config, tab_id)
                        new_id = session_manager.new_tab(config, restore_url or "about:blank")
                        recovered = {
                            "mode": "soft",
                            "ok": True,
                            "sessionTabId": new_id,
                            **({"restoredUrl": restore_url} if restore_url else {}),
                            "trigger": "freshRuntimeCheck",
                            "runtimeOk": False,
                            **({"reset": recovered_reset} if isinstance(recovered_reset, dict) else {}),
                        }
                    except Exception as exc2:
                        recovered = {"mode": "soft", "ok": False, "error": str(exc2), "trigger": "freshRuntimeCheck"}

                # If we recovered, re-check Runtime on the new session tab and surface a deterministic flag.
                post_recover_runtime_ok: bool | None = None
                if isinstance(recovered, dict) and recovered.get("ok") is True:
                    try:
                        with get_session(
                            config,
                            timeout=2.0,
                            ensure_diagnostics=False,
                            ensure_telemetry=True,
                            enable_page=False,
                        ) as (post, _t3):
                            ok3, _to3 = _runtime_smoke(post)
                            post_recover_runtime_ok = bool(ok3)
                    except Exception:
                        post_recover_runtime_ok = False
                    recovered["runtimeOk"] = bool(post_recover_runtime_ok)

                result: dict[str, Any] = {"handled": True, "accepted": accept, "target": target["id"]}
                if prompt_text is not None:
                    result["promptText"] = prompt_text
                if opened is not None:
                    result["dialog"] = opened
                if stale_state_cleared:
                    result["staleStateCleared"] = True
                    if timeout_s > 0:
                        result["waited_s"] = timeout_s
                if recovered is not None:
                    result["recovered"] = recovered
                # Always surface a tiny post-check bit for cross-call autonomy.
                try:
                    if isinstance(recovered, dict) and "runtimeOk" in recovered:
                        result["runtimeOk"] = bool(recovered.get("runtimeOk"))
                    else:
                        result["runtimeOk"] = bool(runtime_ok) and bool(fresh_runtime_ok)
                except Exception:
                    pass
                return result
            except HttpClientError:
                raise
            except Exception as exc:
                # Normalize to HttpClientError for retry classification.
                raise HttpClientError(str(exc)) from exc

    try:
        # Attempt 1: fast, low timeout.
        return _attempt(conn_timeout=3.0)
    except Exception as exc1:
        if not _is_cdp_timeout(exc1):
            suggestion = "Ensure there is an active JavaScript dialog to handle"
            raise SmartToolError(
                tool="handle_dialog",
                action="handle",
                reason=str(exc1),
                suggestion=suggestion,
            ) from exc1

        # Attempt 2: fresh connection with a larger timeout.
        try:
            return _attempt(conn_timeout=6.0)
        except Exception as exc2:
            if not _is_cdp_timeout(exc2):
                raise SmartToolError(
                    tool="handle_dialog",
                    action="handle",
                    reason=str(exc2),
                    suggestion="Ensure there is an active JavaScript dialog to handle",
                ) from exc2

            # Emergency: clear local state so subsequent calls do not keep using a bad tab/bus.
            reset = None
            try:
                reset = session_manager.recover_reset()
            except Exception:
                reset = None

            raise SmartToolError(
                tool="handle_dialog",
                action="handle",
                reason=str(exc2),
                suggestion='CDP is stuck (often due to a dialog brick). Try browser(action="recover") to restart CDP/Chrome, then retry.',
                details={"recoverReset": reset} if isinstance(reset, dict) else {},
            ) from exc2
