"""
Unified tool handlers.

Maps new unified tools to existing implementations.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ... import tools
from ..artifacts import artifact_store
from ..hints import artifact_export_hint, artifact_get_hint, artifact_list_hint
from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


def _parse_dom_ref(value: Any) -> int | None:
    """Parse a stable element ref like 'dom:123' into backendDOMNodeId."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    if v.startswith("dom:"):
        rest = v[4:].strip()
        try:
            return int(rest)
        except Exception:
            return None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_navigate(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified navigation: URL or action (back/forward/reload)."""
    wait_type = str(args.get("wait", "load") or "load").lower()

    before_url: str | None = None
    if wait_type != "none":
        before_url = _best_effort_current_url(config)

    if "url" in args:
        # Do not block on CDP loadEventFired inside navigate_to; unified tool owns waiting semantics.
        result = tools.navigate_to(config, args["url"], wait_load=False)
    elif "action" in args:
        action = args["action"]
        if action == "back":
            result = tools.go_back(config)
        elif action == "forward":
            result = tools.go_forward(config)
        elif action == "reload":
            result = tools.reload_page(config)
        else:
            return ToolResult.error(f"Unknown action: {action}")
    else:
        return ToolResult.error("Either 'url' or 'action' is required")

    # Auto-wait (post-navigate stabilization).
    if wait_type == "navigation":
        new_url = _wait_for_url_change(config, before_url, timeout=10.0)
        if new_url:
            result["page_changed"] = True
            result["navigation"] = {"old_url": before_url, "new_url": new_url}
            result["url"] = new_url
        else:
            result["page_changed"] = False
    elif wait_type != "none":
        # Best-effort: first wait for URL to change (helps when readyState is already 'complete').
        new_url = _wait_for_url_change(config, before_url, timeout=5.0)
        if new_url:
            result["page_changed"] = True
            result["navigation"] = {"old_url": before_url, "new_url": new_url}
            result["url"] = new_url
        else:
            result["page_changed"] = False

        wait_res = _wait_for_condition(config, wait_type, timeout=10.0)
        result["wait_found"] = bool(wait_res.get("found"))
        time.sleep(0.1)  # small stabilization for hydration/handlers

    result["waited"] = wait_type
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SCROLL
# ═══════════════════════════════════════════════════════════════════════════════


def handle_scroll(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified scroll: direction, to element, or to top/bottom."""
    backend_dom_node_id: int | None = None
    if "backendDOMNodeId" in args:
        try:
            backend_dom_node_id = int(args.get("backendDOMNodeId"))
        except Exception:
            return ToolResult.error("backendDOMNodeId must be an integer")
    elif "ref" in args:
        backend_dom_node_id = _parse_dom_ref(args.get("ref"))
        if backend_dom_node_id is None:
            return ToolResult.error("ref must be a string like 'dom:123' (from page(detail='ax'))")

    if backend_dom_node_id is not None:
        result = tools.scroll_backend_node(config, backend_dom_node_id=backend_dom_node_id)
    elif args.get("to"):
        result = tools.scroll_to_element(config, args["to"])
    elif args.get("to_top"):
        result = tools.scroll_page(config, 0, -99999)
        result["atTop"] = True
    elif args.get("to_bottom"):
        result = tools.scroll_page(config, 0, 99999)
        result["atBottom"] = True
    elif args.get("direction"):
        direction = args["direction"]
        amount = args.get("amount", 300)

        delta_x, delta_y = 0, 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        result = tools.scroll_page(config, delta_x, delta_y)
    else:
        # Default: scroll down
        result = tools.scroll_page(config, 0, 300)

    # Add scroll position info
    page_info = tools.get_page_info(config)
    result["scrollX"] = page_info.get("pageInfo", {}).get("scrollX", 0)
    result["scrollY"] = page_info.get("pageInfo", {}).get("scrollY", 0)

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CLICK
# ═══════════════════════════════════════════════════════════════════════════════


def handle_click(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified click: text, selector, or coordinates."""
    wait_after = args.get("wait_after", "auto")
    double = args.get("double", False)
    button = args.get("button", "left")
    strategy = str(args.get("strategy", "auto") or "auto").lower()
    if strategy not in {"auto", "ax", "dom"}:
        return ToolResult.error(f"Unknown strategy: {strategy}")

    before_url: str | None = None
    if wait_after in {"auto", "navigation"}:
        before_url = _best_effort_current_url(config)

    result: dict[str, Any] = {"success": False}

    # By stable handle (backend DOM node id)
    backend_dom_node_id: int | None = None
    if "backendDOMNodeId" in args:
        try:
            backend_dom_node_id = int(args.get("backendDOMNodeId"))
        except Exception:
            return ToolResult.error("backendDOMNodeId must be an integer")
    elif "ref" in args:
        backend_dom_node_id = _parse_dom_ref(args.get("ref"))
        if backend_dom_node_id is None:
            return ToolResult.error("ref must be a string like 'dom:123' (from page(detail='ax'))")

    if backend_dom_node_id is not None:
        click_result = tools.click_backend_node(
            config,
            backend_dom_node_id=backend_dom_node_id,
            button=button,
            double=bool(double),
        )
        result = click_result
        result["method"] = "backendDOMNodeId"

    # By text (preferred - uses smart click_element)
    elif args.get("text"):
        did_ax = False
        if strategy in {"auto", "ax"} and not args.get("near") and (strategy == "ax" or args.get("role")):
            try:
                click_result = tools.click_accessibility(
                    config,
                    role=args.get("role"),
                    name=args["text"],
                    index=args.get("index", 0),
                    button=button,
                    double=bool(double),
                )
                result = click_result
                result["method"] = "ax"
                did_ax = True
            except tools.SmartToolError:
                if strategy == "ax":
                    raise
                did_ax = False

        if not did_ax:
            try:
                click_result = tools.click_element(
                    config,
                    text=args["text"],
                    role=args.get("role"),
                    near_text=args.get("near"),
                    index=args.get("index", 0),
                    button=button,
                    double=bool(double),
                )
                result = click_result
                result["method"] = "text"
            except tools.SmartToolError as exc:
                # Fallback: fuzzy match against Tier-0/Tier-1 locators (stable backend DOM node ids).
                # This helps when UI labels drift ("Upload" -> "Import") or when the DOM is complex.
                #
                # Safety: only auto-fallback when the click wasn't executed (pre-click failures).
                reason_l = str(exc.reason or "").lower()
                pre_click = (
                    "element not found" in reason_l
                    or "missing element bounds" in reason_l
                    or "index out of range" in reason_l
                    or "no matching accessibility node found" in reason_l
                    or "click evaluation returned null" in reason_l
                )
                if not pre_click or strategy == "ax":
                    raise

                query = str(args.get("text") or "").strip()
                if not query:
                    raise

                def _norm(s: str) -> str:
                    return " ".join(str(s or "").lower().split())

                def _tokens(s: str) -> set[str]:
                    parts = [p for p in _norm(s).replace("/", " ").replace("-", " ").split(" ") if p]
                    # Drop ultra-short tokens (noise) but keep 1-char if query is 1-char (rare).
                    return {p for p in parts if len(p) >= 2} or set(parts[:4])

                qn = _norm(query)
                qt = _tokens(query)

                # Use locators (may fall back to Tier-0 AX) and score candidates.
                loc_payload = tools.get_page_locators(config, kind="all", offset=0, limit=80)
                locs = loc_payload.get("locators") if isinstance(loc_payload, dict) else None
                items = locs.get("items") if isinstance(locs, dict) else None
                if not isinstance(items, list) or not items:
                    raise

                role_hint = str(args.get("role") or "").strip().lower()
                wanted_kind = role_hint if role_hint in {"button", "link"} else ""

                scored: list[tuple[int, dict[str, Any]]] = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    backend_id = it.get("backendDOMNodeId")
                    if not isinstance(backend_id, int) or backend_id <= 0:
                        continue
                    kind = str(it.get("kind") or "").strip().lower()
                    if wanted_kind and kind and kind != wanted_kind:
                        continue

                    label = (
                        it.get("text")
                        if isinstance(it.get("text"), str) and it.get("text")
                        else it.get("name")
                        if isinstance(it.get("name"), str) and it.get("name")
                        else ""
                    )
                    cn = _norm(label)
                    if not cn:
                        continue

                    score = 0
                    if cn == qn:
                        score = 100
                    elif qn and qn in cn:
                        score = 85
                    else:
                        ct = _tokens(label)
                        if qt and ct:
                            inter = len(qt & ct)
                            # Weighted Jaccard-ish score
                            score = int(round(70 * inter / max(1, len(qt))))

                    # Small boosts for typical action verbs (more likely the right control).
                    if kind == "button":
                        score += 5
                    if score > 0:
                        scored.append((score, it))

                if not scored:
                    raise

                scored.sort(key=lambda x: x[0], reverse=True)
                best_score, best = scored[0]
                second_score = scored[1][0] if len(scored) > 1 else -1

                # Guard against ambiguous matches: require a clear winner.
                if best_score < 70 or (second_score >= 0 and best_score - second_score < 8):
                    raise

                clicked = tools.click_backend_node(
                    config,
                    backend_dom_node_id=int(best.get("backendDOMNodeId")),
                    button=button,
                    double=bool(double),
                )
                result = clicked
                result["method"] = "locators_fuzzy"
                result["matched"] = {
                    "label": best.get("text") or best.get("name"),
                    "score": best_score,
                    "kind": best.get("kind"),
                }

    # By selector
    elif args.get("selector"):
        result = tools.dom_action_click(
            config,
            args["selector"],
            index=args.get("index", 0),
            button=button,
            click_count=2 if double else 1,
        )
        result["method"] = "selector"

    # By coordinates
    elif "x" in args and "y" in args:
        x, y = float(args["x"]), float(args["y"])
        result = tools.click_at_pixel(config, x, y, button=button, click_count=2 if double else 1)
        result["method"] = "coordinates"
        result["clicked"] = {"x": x, "y": y}

    else:
        return ToolResult.error("Specify 'text', 'selector', or 'x'+'y' coordinates")

    # Auto-wait after click
    if wait_after == "auto":
        new_url = _wait_for_url_change(config, before_url, timeout=2.0) if before_url else None
        if new_url:
            _wait_for_condition(config, "load", timeout=5)
            result["page_changed"] = True
            result["navigation"] = {"old_url": before_url, "new_url": new_url}
        else:
            time.sleep(0.1)  # Brief stabilization
            result["page_changed"] = False
    elif wait_after == "navigation":
        new_url = _wait_for_url_change(config, before_url, timeout=10.0) if before_url else None
        if new_url:
            _wait_for_condition(config, "load", timeout=10)
            result["page_changed"] = True
            result["navigation"] = {"old_url": before_url, "new_url": new_url}
        else:
            result["page_changed"] = False

    result["success"] = True
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TYPE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_type(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Unified type: into element, into focused, or press key."""
    result: dict[str, Any] = {"success": False}

    # Build modifiers bitmask
    modifiers = 0
    if args.get("alt"):
        modifiers |= 1
    if args.get("ctrl"):
        modifiers |= 2
    if args.get("meta"):
        modifiers |= 4
    if args.get("shift"):
        modifiers |= 8

    # Press single key
    if args.get("key"):
        result = tools.press_key(config, args["key"], modifiers=modifiers)
        result["action"] = "key_press"

    # Type into element by stable handle
    else:
        backend_dom_node_id: int | None = None
        if "backendDOMNodeId" in args:
            try:
                backend_dom_node_id = int(args.get("backendDOMNodeId"))
            except Exception:
                return ToolResult.error("backendDOMNodeId must be an integer")
        elif "ref" in args:
            backend_dom_node_id = _parse_dom_ref(args.get("ref"))
            if backend_dom_node_id is None:
                return ToolResult.error("ref must be a string like 'dom:123' (from page(detail='ax'))")

        # Type into element by stable handle
        if backend_dom_node_id is not None and args.get("text") is not None:
            result = tools.type_backend_node(
                config,
                backend_dom_node_id=backend_dom_node_id,
                text=str(args.get("text") or ""),
                clear=bool(args.get("clear", False)),
                submit=bool(args.get("submit", False)),
            )
            result["action"] = "type_into_backend_node"

        # Type into specific element
        elif args.get("selector") and args.get("text"):
            result = tools.dom_action_type(
                config,
                selector=args["selector"],
                text=args["text"],
                clear=args.get("clear", False),
            )
            result["action"] = "type_into_element"

            if args.get("submit"):
                tools.press_key(config, "Enter")
                result["submitted"] = True

        # Type into focused element
        elif args.get("text"):
            result = tools.type_text(config, args["text"])
            result["action"] = "type_into_focused"

            if args.get("submit"):
                tools.press_key(config, "Enter")
                result["submitted"] = True

        else:
            return ToolResult.error("Specify 'text' or 'key'")

    result["success"] = True
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# MOUSE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_mouse(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Low-level mouse: move, hover, drag."""
    action = args.get("action")

    if action == "move":
        if "x" not in args or "y" not in args:
            return ToolResult.error("'x' and 'y' required for move")
        result = tools.move_mouse_to(config, float(args["x"]), float(args["y"]))

    elif action == "hover":
        backend_dom_node_id: int | None = None
        if "backendDOMNodeId" in args:
            try:
                backend_dom_node_id = int(args.get("backendDOMNodeId"))
            except Exception:
                return ToolResult.error("backendDOMNodeId must be an integer")
        elif "ref" in args:
            backend_dom_node_id = _parse_dom_ref(args.get("ref"))
            if backend_dom_node_id is None:
                return ToolResult.error("ref must be a string like 'dom:123' (from page(detail='ax'))")

        if backend_dom_node_id is not None:
            result = tools.hover_backend_node(config, backend_dom_node_id=backend_dom_node_id)
        elif "selector" in args:
            result = tools.hover_element(config, args["selector"])
        else:
            return ToolResult.error("hover requires one of: ref, backendDOMNodeId, selector")

    elif action == "drag":
        steps = args.get("steps", 10)

        from_backend: int | None = None
        to_backend: int | None = None
        if "from_backendDOMNodeId" in args:
            try:
                from_backend = int(args.get("from_backendDOMNodeId"))
            except Exception:
                return ToolResult.error("from_backendDOMNodeId must be an integer")
        elif "from_ref" in args:
            from_backend = _parse_dom_ref(args.get("from_ref"))
            if from_backend is None:
                return ToolResult.error("from_ref must be a string like 'dom:123' (from page(detail='ax'))")

        if "to_backendDOMNodeId" in args:
            try:
                to_backend = int(args.get("to_backendDOMNodeId"))
            except Exception:
                return ToolResult.error("to_backendDOMNodeId must be an integer")
        elif "to_ref" in args:
            to_backend = _parse_dom_ref(args.get("to_ref"))
            if to_backend is None:
                return ToolResult.error("to_ref must be a string like 'dom:123' (from page(detail='ax'))")

        # Mixed modes:
        # - from_ref/from_backendDOMNodeId -> to_ref/to_backendDOMNodeId
        # - from_ref/from_backendDOMNodeId -> to_x/to_y
        # - from_x/from_y -> to_ref/to_backendDOMNodeId
        # - from_x/from_y -> to_x/to_y
        has_from_xy = "from_x" in args and "from_y" in args
        has_to_xy = "to_x" in args and "to_y" in args

        if from_backend is not None:
            if to_backend is not None:
                result = tools.drag_backend_nodes(
                    config,
                    from_backend_dom_node_id=from_backend,
                    to_backend_dom_node_id=to_backend,
                    steps=steps,
                )
            elif has_to_xy:
                result = tools.drag_backend_node_to_xy(
                    config,
                    backend_dom_node_id=from_backend,
                    to_x=float(args["to_x"]),
                    to_y=float(args["to_y"]),
                    steps=steps,
                )
            else:
                return ToolResult.error(
                    "drag requires a target: to_ref/to_backendDOMNodeId or to_x/to_y (when using from_ref/from_backendDOMNodeId)"
                )

        elif to_backend is not None:
            if not has_from_xy:
                return ToolResult.error(
                    "drag requires a start: from_ref/from_backendDOMNodeId or from_x/from_y (when using to_ref/to_backendDOMNodeId)"
                )
            result = tools.drag_xy_to_backend_node(
                config,
                from_x=float(args["from_x"]),
                from_y=float(args["from_y"]),
                backend_dom_node_id=to_backend,
                steps=steps,
            )

        else:
            required = ["from_x", "from_y", "to_x", "to_y"]
            if not all(k in args for k in required):
                return ToolResult.error(f"Required for drag: {required} or stable handle refs")
            result = tools.drag_from_to(
                config,
                float(args["from_x"]),
                float(args["from_y"]),
                float(args["to_x"]),
                float(args["to_y"]),
                steps=steps,
            )

    else:
        return ToolResult.error("'action' required: move, hover, or drag")

    result["action"] = action
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# RESIZE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_resize(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Resize viewport or window."""
    width = int(args["width"])
    height = int(args["height"])
    target = args.get("target", "viewport")

    if target == "viewport":
        result = tools.resize_viewport(config, width, height)
    else:
        result = tools.resize_window(config, width, height)

    result["target"] = target
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# FORM
# ═══════════════════════════════════════════════════════════════════════════════


def handle_form(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Form operations: fill, select, focus, clear, wait."""
    result: dict[str, Any] = {}

    if args.get("fill"):
        fill_result = tools.fill_form(
            config,
            data=args["fill"],
            submit=args.get("submit", False),
            form_index=args.get("form_index", 0),
        )
        result = fill_result
        result["action"] = "fill"

    elif args.get("select"):
        sel = args["select"]
        select_result = tools.select_option(
            config,
            selector=sel["selector"],
            value=sel["value"],
            by=sel.get("by", "value"),
        )
        result = select_result
        result["action"] = "select"

    elif args.get("focus_key"):
        # Focus by semantic key (label/name/id/placeholder) across open shadow DOM and same-origin iframes.
        result = tools.focus_field(config, key=str(args["focus_key"]), form_index=args.get("form_index", 0))
        result["action"] = "focus_key"

    elif args.get("focus"):
        result = tools.focus_element(config, args["focus"])
        result["action"] = "focus"

    elif args.get("clear"):
        result = tools.clear_input(config, args["clear"])
        result["action"] = "clear"

    elif args.get("wait_for"):
        result = tools.wait_for_element(
            config,
            selector=args["wait_for"],
            timeout=args.get("timeout", 10),
        )
        result["action"] = "wait"

    else:
        return ToolResult.error("Specify 'fill', 'select', 'focus_key', 'focus', 'clear', or 'wait_for'")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════


def handle_tabs(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Tab management: list, switch, new, close."""
    action = args.get("action", "list")

    if action == "list":
        result = tools.list_tabs(config, url_filter=args.get("url_contains"))
        result["action"] = "list"

    elif action == "switch":
        if args.get("tab_id"):
            result = tools.switch_tab(config, tab_id=args["tab_id"])
        elif args.get("url_contains"):
            result = tools.switch_tab(config, url_pattern=args["url_contains"])
        else:
            return ToolResult.error("'tab_id' or 'url_contains' required for switch")
        result["action"] = "switch"

    elif action == "new":
        result = tools.new_tab(config, url=args.get("url", "about:blank"))
        result["action"] = "new"

    elif action == "close":
        result = tools.close_tab(config, tab_id=args.get("tab_id"))
        result["action"] = "close"

    elif action == "rescue":
        # Rescue UX: create a fresh tab for this session without restarting Chrome.
        # Useful when the current tab is bricked (dialogs, stuck target, broken state).
        from ...session import session_manager as _session_manager

        before_tab = _session_manager.tab_id
        before_url = None
        try:
            before_url = _best_effort_current_url(config)
        except Exception:
            before_url = None

        url = args.get("url")
        if not (isinstance(url, str) and url.strip()):
            url = before_url or "about:blank"

        close_old = bool(args.get("close_old", True))
        new_id = _session_manager.new_tab(config, str(url))

        closed_old = False
        if close_old and isinstance(before_tab, str) and before_tab and before_tab != new_id:
            try:
                closed_old = bool(_session_manager.close_tab(config, before_tab))
            except Exception:
                closed_old = False

        result = {
            "result": {
                "success": True,
                "mode": "rescue",
                "before": {"sessionTabId": before_tab, **({"url": before_url} if before_url else {})},
                "after": {"sessionTabId": new_id, "url": str(url)},
                "closedOld": closed_old,
            }
        }
        result["action"] = "rescue"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# COOKIES
# ═══════════════════════════════════════════════════════════════════════════════


def handle_cookies(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Cookie management: get, set, delete."""
    action = args.get("action", "get")

    if action == "get":
        result = tools.get_all_cookies(
            config,
            name_filter=args.get("name_filter"),
        )
        result["action"] = "get"

    elif action == "set":
        if args.get("cookies"):
            result = tools.set_cookies_batch(config, args["cookies"])
        elif args.get("name") and args.get("value") and args.get("domain"):
            result = tools.set_cookie(
                config,
                name=args["name"],
                value=args["value"],
                domain=args["domain"],
                path=args.get("path", "/"),
                secure=args.get("secure", False),
                http_only=args.get("httpOnly", False),
                expires=args.get("expires"),
                same_site=args.get("sameSite", "Lax"),
            )
        else:
            return ToolResult.error("For set: need 'name', 'value', 'domain' or 'cookies' array")
        result["action"] = "set"

    elif action == "delete":
        if not args.get("name"):
            return ToolResult.error("'name' required for delete")
        result = tools.delete_cookie(
            config,
            name=args["name"],
            domain=args.get("domain"),
            path=args.get("path"),
        )
        result["action"] = "delete"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CAPTCHA
# ═══════════════════════════════════════════════════════════════════════════════


def handle_captcha(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """CAPTCHA detection and interaction."""
    action = args.get("action", "analyze")

    if action == "analyze":
        result = tools.analyze_captcha(config, force_grid_size=args.get("grid_size", 0))

    elif action == "screenshot":
        result = tools.get_captcha_screenshot(
            config,
            grid_size=args.get("grid_size"),
        )
        result["action"] = action

        # Avoid dumping base64 into the text channel.
        screenshot_b64 = ""
        if isinstance(result, dict):
            screenshot_b64 = str(result.pop("screenshot_b64", "") or "")

        from ..ai_format import render_ctx_markdown

        return ToolResult.with_image(render_ctx_markdown(result), screenshot_b64, "image/png", data=result)

    elif action == "click_checkbox":
        result = tools.click_captcha_area(config, area_id=1)

    elif action == "click_blocks":
        if not args.get("blocks"):
            return ToolResult.error("'blocks' array required")
        result = tools.click_captcha_blocks(
            config,
            blocks=args["blocks"],
            grid_size=args.get("grid_size", 0),
        )

    elif action == "click_area":
        result = tools.click_captcha_area(
            config,
            area_id=args.get("area_id", 1),
        )

    elif action == "submit":
        result = tools.submit_captcha(config)

    else:
        return ToolResult.error(f"Unknown action: {action}")

    result["action"] = action
    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════════════════════════════════


def handle_page(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Page analysis - primary tool for understanding page."""
    store = bool(args.get("store", False))
    if args.get("info"):
        result = tools.get_page_info(config)
    elif args.get("detail") == "triage":
        limit = args.get("limit") if "limit" in args else 30
        triage_kwargs: dict[str, Any] = {
            "limit": limit,
            "clear": bool(args.get("clear", False)),
        }
        if "since" in args:
            triage_kwargs["since"] = args.get("since")
        triage = tools.get_page_triage(config, **triage_kwargs)
        if store:
            _attach_artifact_ref(config, triage, args, kind="page_triage")
        if args.get("with_screenshot"):
            from ..ai_format import render_ctx_markdown

            shot = tools.screenshot(config)
            data = shot.get("content_b64") or shot.get("data", "")
            if store:
                _attach_screenshot_ref(config, triage, args, data_b64=str(data or ""), kind="page_screenshot")
            return ToolResult.with_image(render_ctx_markdown(triage), data, "image/png")
        result = triage
    elif args.get("detail") == "audit":
        # Super-report: combine triage/diagnostics/perf/resources/locators into one bounded snapshot.
        limit = args.get("limit") if "limit" in args else 30
        audit_kwargs: dict[str, Any] = {"limit": limit, "clear": bool(args.get("clear", False))}
        if "since" in args:
            audit_kwargs["since"] = args.get("since")

        trace_arg = args.get("trace")

        # NOTE: Some clients/tooling layers may coerce JSON objects into strings.
        # We accept:
        # - trace=true/false (bool)
        # - trace={...} (dict)
        # - trace="{...}" (JSON string)
        trace_cfg: dict[str, Any] = {}
        if isinstance(trace_arg, bool):
            trace_enabled = bool(trace_arg)
        elif isinstance(trace_arg, dict):
            trace_cfg = trace_arg
            trace_enabled = True
        elif isinstance(trace_arg, str):
            raw = trace_arg.strip()
            lowered = raw.lower()
            if not raw or lowered in {"false", "0", "no", "off"}:
                trace_enabled = False
            elif lowered in {"true", "1", "yes", "on"}:
                trace_enabled = True
            else:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        trace_cfg = parsed
                        trace_enabled = True
                    else:
                        # Unknown shape, but user asked for trace; fall back to defaults.
                        trace_enabled = True
                except Exception:
                    # Not JSON, but user asked for trace; fall back to defaults.
                    trace_enabled = True
        else:
            trace_enabled = bool(trace_arg)

        # If trace is requested, prefer a shared session so CDP fetches for bodies (request/response)
        # can reuse the same connection as audit collection. This must be fail-soft (tests run without Chrome).
        if trace_enabled:
            from contextlib import contextmanager

            from ...session import session_manager as _session_manager

            @contextmanager
            def _maybe_shared_session() -> Any:  # noqa: ANN401
                try:
                    with _session_manager.shared_session(config):
                        yield
                except Exception:
                    yield

            with _maybe_shared_session():
                audit = tools.get_page_audit(config, **audit_kwargs)

                # Optional deep network trace capture (bounded + artifact-backed).
                try:
                    from ...net_trace import build_net_trace

                    # trace_cfg is parsed above (dict | json-string | bool)
                    # and defaults to {} when trace was requested without extra configuration.

                    include = trace_cfg.get("include")
                    if include is None:
                        include = trace_cfg.get("includeUrlPatterns")
                    exclude = trace_cfg.get("exclude")
                    if exclude is None:
                        exclude = trace_cfg.get("excludeUrlPatterns")
                    types_raw = trace_cfg.get("types")
                    if types_raw is None:
                        types_raw = trace_cfg.get("resourceTypes")
                    capture = trace_cfg.get("capture", "meta")

                    redact = trace_cfg.get("redact")
                    if redact is None:
                        redact = True

                    max_body_bytes = trace_cfg.get("maxBodyBytes", 80_000)
                    max_total_bytes = trace_cfg.get("maxTotalBytes", 600_000)

                    def _to_int(value: Any, default: int) -> int:
                        try:
                            if value is None or isinstance(value, bool):
                                raise ValueError
                            if isinstance(value, (int, float)):
                                return int(value)
                            return int(float(str(value).strip()))
                        except Exception:
                            return int(default)

                    trace_since_raw = (
                        trace_cfg.get("since")
                        if isinstance(trace_cfg, dict) and "since" in trace_cfg
                        else args.get("since")
                    )
                    trace_since = _to_int(trace_since_raw, default=0) if trace_since_raw is not None else None
                    trace_offset = _to_int(trace_cfg.get("offset", 0), default=0)
                    trace_limit = _to_int(trace_cfg.get("limit", 20), default=20)

                    trace_store = trace_cfg.get("store")
                    if trace_store is None:
                        trace_store = True

                    trace_export = bool(trace_cfg.get("export", False))
                    trace_overwrite = bool(trace_cfg.get("overwrite", False))
                    trace_name = trace_cfg.get("name")
                    trace_name_str = str(trace_name) if isinstance(trace_name, str) and trace_name.strip() else None
                    trace_clear = bool(trace_cfg.get("clear", False))

                    cursor = audit.get("cursor") if isinstance(audit, dict) else None
                    cursor_i = cursor if isinstance(cursor, int) else None
                    tab_id = audit.get("sessionTabId") if isinstance(audit, dict) else None

                    trace_out = build_net_trace(
                        config,
                        tab_id=tab_id if isinstance(tab_id, str) else None,
                        cursor=cursor_i,
                        since=trace_since if isinstance(trace_since, int) and trace_since > 0 else None,
                        offset=int(trace_offset),
                        limit=int(trace_limit),
                        include=include,
                        exclude=exclude,
                        types_raw=types_raw,
                        capture=str(capture or "meta"),
                        redact=bool(redact),
                        max_body_bytes=_to_int(max_body_bytes, default=80_000),
                        max_total_bytes=_to_int(max_total_bytes, default=600_000),
                        store=bool(trace_store) or trace_export,
                        export=trace_export,
                        overwrite=trace_overwrite,
                        name=trace_name_str,
                        clear=trace_clear,
                    )

                    audit_obj = audit.get("audit") if isinstance(audit, dict) else None
                    if isinstance(audit_obj, dict):
                        if isinstance(trace_out.get("trace"), dict):
                            trace_payload = dict(trace_out.get("trace") or {})
                            items = trace_payload.get("items") if isinstance(trace_payload.get("items"), list) else []
                            preview_n = min(6, len(items))
                            if preview_n < len(items):
                                trace_payload["items"] = items[:preview_n]
                                trace_payload["itemsTruncated"] = True
                                trace_payload["itemsPreview"] = preview_n
                            audit_obj["netTrace"] = trace_payload
                        if isinstance(trace_out.get("artifact"), dict):
                            audit_obj["netTraceArtifact"] = trace_out.get("artifact")
                        if isinstance(trace_out.get("export"), dict):
                            audit_obj["netTraceExport"] = trace_out.get("export")
                        nxt = trace_out.get("next")
                        if isinstance(nxt, list) and nxt:
                            audit_obj.setdefault("next", [])
                            if isinstance(audit_obj.get("next"), list):
                                audit_obj["next"] = [*nxt, *audit_obj["next"]]
                except Exception as e:
                    audit_obj = audit.get("audit") if isinstance(audit, dict) else None
                    if isinstance(audit_obj, dict):
                        audit_obj["netTraceError"] = str(e)
        else:
            audit = tools.get_page_audit(config, **audit_kwargs)

        if store:
            _attach_artifact_ref(config, audit, args, kind="page_audit")
        if args.get("with_screenshot"):
            from ..ai_format import render_ctx_markdown

            shot = tools.screenshot(config)
            data = shot.get("content_b64") or shot.get("data", "")
            if store:
                _attach_screenshot_ref(config, audit, args, data_b64=str(data or ""), kind="page_screenshot")
            return ToolResult.with_image(render_ctx_markdown(audit), data, "image/png")
        result = audit
    elif args.get("detail") == "diagnostics":
        limit = args.get("limit") if "limit" in args else 50
        offset = args.get("offset") if "offset" in args else 0
        sort = args.get("sort") if "sort" in args else "start"
        diag_kwargs: dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "sort": sort,
            "clear": bool(args.get("clear", False)),
        }
        if "since" in args:
            diag_kwargs["since"] = args.get("since")
        result = tools.get_page_diagnostics(config, **diag_kwargs)
        if store:
            _attach_artifact_ref(config, result, args, kind="page_diagnostics")
    elif args.get("detail") == "ax":
        limit = args.get("limit") if "limit" in args else 20
        offset = args.get("offset") if "offset" in args else 0
        role = args.get("role")
        name = args.get("name")
        with_screenshot = bool(args.get("with_screenshot", False))
        overlay = bool(args.get("overlay", True))
        if with_screenshot:
            try:
                overlay_limit = int(args.get("overlay_limit", 20))
            except Exception:
                overlay_limit = 20
            limit = min(int(limit), max(0, overlay_limit))

            from ...session import session_manager as _session_manager
            from ..ai_format import render_ctx_markdown

            with _session_manager.shared_session(config):
                ax_payload = tools.get_page_ax(
                    config,
                    role=role,
                    name=name,
                    offset=offset,
                    limit=limit,
                )

                boxes: list[dict[str, Any]] = []
                try:
                    ax = ax_payload.get("ax") if isinstance(ax_payload, dict) else None
                    items = ax.get("items") if isinstance(ax, dict) else None
                except Exception:
                    ax = None
                    items = None

                compact_items: list[dict[str, Any]] = []
                if isinstance(items, list):
                    # Build overlay bounds without scrolling (we want a stable screenshot of the current viewport).
                    box_by_n: dict[int, dict[str, Any]] = {}
                    try:
                        with tools.get_session(config) as (session, _target):
                            with suppress(Exception):
                                session.enable_dom()

                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                backend_id = it.get("backendDOMNodeId")
                                if not isinstance(backend_id, int) or backend_id <= 0:
                                    continue
                                n = len(box_by_n) + 1
                                if n > max(0, overlay_limit):
                                    break
                                try:
                                    box = session.send("DOM.getBoxModel", {"backendNodeId": backend_id})
                                    model = box.get("model") if isinstance(box, dict) else None
                                    quad = None
                                    if isinstance(model, dict):
                                        quad = model.get("border") or model.get("content") or model.get("padding")
                                    if not isinstance(quad, list) or len(quad) < 8:
                                        continue
                                    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
                                    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
                                    x = min(xs)
                                    y = min(ys)
                                    w = max(xs) - x
                                    h = max(ys) - y
                                    if w >= 2 and h >= 2:
                                        box_by_n[n] = {"n": n, "x": x, "y": y, "width": w, "height": h}
                                except Exception:
                                    continue
                    except Exception:
                        box_by_n = {}

                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        n = len(compact_items) + 1
                        if n > max(0, overlay_limit):
                            break
                        backend_id = it.get("backendDOMNodeId")
                        ref = it.get("ref")

                        compact: dict[str, Any] = {
                            "n": n,
                            **({"role": it.get("role")} if isinstance(it.get("role"), str) else {}),
                            **({"name": it.get("name")} if isinstance(it.get("name"), str) else {}),
                            **({"ref": ref} if isinstance(ref, str) and ref else {}),
                            **({"backendDOMNodeId": backend_id} if isinstance(backend_id, int) else {}),
                            **({"focusable": it.get("focusable")} if isinstance(it.get("focusable"), bool) else {}),
                            **({"disabled": it.get("disabled")} if isinstance(it.get("disabled"), bool) else {}),
                        }

                        if isinstance(ref, str) and ref:
                            compact["actionHint"] = f'click(ref="{ref}")'
                        elif isinstance(backend_id, int) and backend_id > 0:
                            compact["actionHint"] = f"click(backendDOMNodeId={backend_id})"

                        if overlay:
                            box = box_by_n.get(n)
                            if isinstance(box, dict):
                                boxes.append(box)
                                with suppress(Exception):
                                    compact["center"] = {
                                        "x": float(box.get("x", 0)) + float(box.get("width", 0)) / 2.0,
                                        "y": float(box.get("y", 0)) + float(box.get("height", 0)) / 2.0,
                                    }

                        compact_items.append(compact)

                if isinstance(ax, dict):
                    ax["items"] = compact_items

                if isinstance(ax_payload, dict):
                    ax_payload["overlay"] = {"enabled": overlay, "count": len(boxes)}

                overlay_id = "__mcp_overlay_ax"
                remove_js = (
                    "(() => {"
                    f"  const el = document.getElementById({json.dumps(overlay_id)});"
                    "  if (el) el.remove();"
                    "  return true;"
                    "})()"
                )
                inject_js = (
                    "(() => {"
                    f"  const id = {json.dumps(overlay_id)};"
                    "  const old = document.getElementById(id);"
                    "  if (old) old.remove();"
                    "  const root = document.createElement('div');"
                    "  root.id = id;"
                    "  root.style.position = 'fixed';"
                    "  root.style.left = '0';"
                    "  root.style.top = '0';"
                    "  root.style.width = '100%';"
                    "  root.style.height = '100%';"
                    "  root.style.pointerEvents = 'none';"
                    "  root.style.zIndex = '2147483647';"
                    "  root.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';"
                    f"  const boxes = {json.dumps(boxes)};"
                    "  for (const b of boxes) {"
                    "    if (!b) continue;"
                    "    const box = document.createElement('div');"
                    "    box.style.position = 'fixed';"
                    "    box.style.left = `${Math.max(0, b.x)}px`;"
                    "    box.style.top = `${Math.max(0, b.y)}px`;"
                    "    box.style.width = `${Math.max(0, b.width)}px`;"
                    "    box.style.height = `${Math.max(0, b.height)}px`;"
                    "    box.style.border = '2px solid rgba(0, 160, 255, 0.95)';"
                    "    box.style.background = 'rgba(0, 160, 255, 0.08)';"
                    "    box.style.boxSizing = 'border-box';"
                    "    const badge = document.createElement('div');"
                    "    badge.textContent = String(b.n);"
                    "    badge.style.position = 'absolute';"
                    "    badge.style.left = '-2px';"
                    "    badge.style.top = '-18px';"
                    "    badge.style.padding = '1px 6px';"
                    "    badge.style.fontSize = '12px';"
                    "    badge.style.lineHeight = '14px';"
                    "    badge.style.borderRadius = '10px';"
                    "    badge.style.color = 'white';"
                    "    badge.style.background = 'rgba(0, 160, 255, 0.95)';"
                    "    box.appendChild(badge);"
                    "    root.appendChild(box);"
                    "  }"
                    "  document.documentElement.appendChild(root);"
                    "  return { ok: true, count: boxes.length };"
                    "})()"
                )

                try:
                    if overlay and boxes:
                        with suppress(Exception):
                            tools.eval_js(config, inject_js)
                    shot = tools.screenshot(config)
                    data = shot.get("content_b64") or shot.get("data", "")
                    if store:
                        _attach_artifact_ref(config, ax_payload, args, kind="page_ax")
                    return ToolResult.with_image(render_ctx_markdown(ax_payload), data, "image/png")
                finally:
                    if overlay:
                        with suppress(Exception):
                            tools.eval_js(config, remove_js)

        result = tools.get_page_ax(
            config,
            role=role,
            name=name,
            offset=offset,
            limit=limit,
        )
        if store:
            _attach_artifact_ref(config, result, args, kind="page_ax")
    elif args.get("detail") == "resources":
        res_kwargs: dict[str, Any] = {
            "offset": args.get("offset", 0),
            "limit": args.get("limit", 50),
            "sort": args.get("sort", "start"),
        }
        if "since" in args:
            res_kwargs["since"] = args.get("since")
        result = tools.get_page_resources(config, **res_kwargs)
        if store:
            _attach_artifact_ref(config, result, args, kind="page_resources")
    elif args.get("detail") == "performance":
        result = tools.get_page_performance(config)
        if store:
            _attach_artifact_ref(config, result, args, kind="page_performance")
    elif args.get("detail") == "frames":
        offset = args.get("offset", 0)
        limit = args.get("limit", 50)

        with_screenshot = bool(args.get("with_screenshot", False))
        overlay = bool(args.get("overlay", True))
        if with_screenshot:
            try:
                overlay_limit = int(args.get("overlay_limit", 15))
            except Exception:
                overlay_limit = 15
            overlay_limit = max(0, min(overlay_limit, 30))

            from ...session import session_manager as _session_manager
            from ..ai_format import render_ctx_markdown

            with _session_manager.shared_session(config):
                frames_payload = tools.get_page_frames(
                    config,
                    offset=offset,
                    limit=limit,
                    include_bounds=overlay,
                    overlay_limit=overlay_limit,
                )

                boxes: list[dict[str, Any]] = []
                try:
                    frames = frames_payload.get("frames") if isinstance(frames_payload, dict) else None
                    raw_boxes = frames.get("overlayBoxes") if isinstance(frames, dict) else None
                    if isinstance(raw_boxes, list):
                        boxes = [b for b in raw_boxes if isinstance(b, dict)]
                except Exception:
                    boxes = []

                overlay_id = "__mcp_overlay_frames"
                remove_js = (
                    "(() => {"
                    f"  const el = document.getElementById({json.dumps(overlay_id)});"
                    "  if (el) el.remove();"
                    "  return true;"
                    "})()"
                )
                inject_js = (
                    "(() => {"
                    f"  const id = {json.dumps(overlay_id)};"
                    "  const old = document.getElementById(id);"
                    "  if (old) old.remove();"
                    "  const root = document.createElement('div');"
                    "  root.id = id;"
                    "  root.style.position = 'fixed';"
                    "  root.style.left = '0';"
                    "  root.style.top = '0';"
                    "  root.style.width = '100%';"
                    "  root.style.height = '100%';"
                    "  root.style.pointerEvents = 'none';"
                    "  root.style.zIndex = '2147483647';"
                    "  root.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';"
                    f"  const boxes = {json.dumps(boxes)};"
                    "  for (const b of boxes) {"
                    "    if (!b) continue;"
                    "    const box = document.createElement('div');"
                    "    box.style.position = 'fixed';"
                    "    box.style.left = `${Math.max(0, b.x)}px`;"
                    "    box.style.top = `${Math.max(0, b.y)}px`;"
                    "    box.style.width = `${Math.max(0, b.width)}px`;"
                    "    box.style.height = `${Math.max(0, b.height)}px`;"
                    "    box.style.border = '2px solid rgba(255, 0, 120, 0.95)';"
                    "    box.style.background = 'rgba(255, 0, 120, 0.08)';"
                    "    box.style.boxSizing = 'border-box';"
                    "    const badge = document.createElement('div');"
                    "    badge.textContent = String(b.n);"
                    "    badge.style.position = 'absolute';"
                    "    badge.style.left = '-2px';"
                    "    badge.style.top = '-18px';"
                    "    badge.style.padding = '1px 6px';"
                    "    badge.style.fontSize = '12px';"
                    "    badge.style.lineHeight = '14px';"
                    "    badge.style.borderRadius = '10px';"
                    "    badge.style.color = 'white';"
                    "    badge.style.background = 'rgba(255, 0, 120, 0.95)';"
                    "    box.appendChild(badge);"
                    "    root.appendChild(box);"
                    "  }"
                    "  document.documentElement.appendChild(root);"
                    "  return { ok: true, count: boxes.length };"
                    "})()"
                )

                try:
                    if overlay and boxes:
                        with suppress(Exception):
                            tools.eval_js(config, inject_js)
                    shot = tools.screenshot(config)
                    data = shot.get("content_b64") or shot.get("data", "")
                    if store:
                        _attach_artifact_ref(config, frames_payload, args, kind="page_frames")
                    return ToolResult.with_image(render_ctx_markdown(frames_payload), data, "image/png")
                finally:
                    if overlay:
                        with suppress(Exception):
                            tools.eval_js(config, remove_js)

        result = tools.get_page_frames(config, offset=offset, limit=limit)
        if store:
            _attach_artifact_ref(config, result, args, kind="page_frames")
    elif args.get("detail") == "locators":
        offset = args.get("offset", 0)
        limit = args.get("limit", 50)
        kind = args.get("kind", "all")

        with_screenshot = bool(args.get("with_screenshot", False))
        overlay = bool(args.get("overlay", True))
        toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
        is_v2 = toolset in {"v2", "northstar", "north-star"}
        if with_screenshot:
            try:
                overlay_limit = int(args.get("overlay_limit", 20))
            except Exception:
                overlay_limit = 20
            limit = min(int(limit), max(0, overlay_limit))

        if with_screenshot:
            from ...session import session_manager as _session_manager
            from ..ai_format import render_ctx_markdown

            with _session_manager.shared_session(config):
                loc_payload = tools.get_page_locators(
                    config,
                    kind=kind,
                    offset=offset,
                    limit=limit,
                )

                # Produce a numbered, compact list that matches the screenshot overlay.
                boxes: list[dict[str, Any]] = []
                try:
                    locs = loc_payload.get("locators") if isinstance(loc_payload, dict) else None
                    items = locs.get("items") if isinstance(locs, dict) else None
                except Exception:
                    locs = None
                    items = None

                compact_items: list[dict[str, Any]] = []
                # Build overlay bounds via DOM.getBoxModel when locators don't include bounds
                # (common for Tier-0 AX locators).
                box_by_n: dict[int, dict[str, Any]] = {}
                if overlay and isinstance(items, list):
                    try:
                        with tools.get_session(config) as (session, _target):
                            with suppress(Exception):
                                session.enable_dom()
                            for idx, it in enumerate(items[: max(0, overlay_limit)], start=1):
                                if not isinstance(it, dict):
                                    continue
                                backend_id = it.get("backendDOMNodeId")
                                if not isinstance(backend_id, int) or backend_id <= 0:
                                    dom_ref = it.get("domRef")
                                    if isinstance(dom_ref, str) and dom_ref.startswith("dom:"):
                                        try:
                                            backend_id = int(dom_ref[4:].strip())
                                        except Exception:
                                            backend_id = None
                                if not isinstance(backend_id, int) or backend_id <= 0:
                                    continue
                                try:
                                    box = session.send("DOM.getBoxModel", {"backendNodeId": backend_id})
                                    model = box.get("model") if isinstance(box, dict) else None
                                    quad = None
                                    if isinstance(model, dict):
                                        quad = model.get("border") or model.get("content") or model.get("padding")
                                    if not isinstance(quad, list) or len(quad) < 8:
                                        continue
                                    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
                                    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
                                    x = min(xs)
                                    y = min(ys)
                                    w = max(xs) - x
                                    h = max(ys) - y
                                    if w >= 2 and h >= 2:
                                        box_by_n[idx] = {"n": idx, "x": x, "y": y, "width": w, "height": h}
                                except Exception:
                                    continue
                    except Exception:
                        box_by_n = {}
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        n = len(compact_items) + 1

                        label = (
                            it.get("text")
                            if isinstance(it.get("text"), str) and it.get("text")
                            else it.get("label")
                            if isinstance(it.get("label"), str) and it.get("label")
                            else it.get("fillKey")
                            if isinstance(it.get("fillKey"), str) and it.get("fillKey")
                            else ""
                        )

                        compact: dict[str, Any] = {
                            "n": n,
                            "kind": it.get("kind"),
                            **({"label": label} if label else {}),
                            **({"selector": it.get("selector")} if isinstance(it.get("selector"), str) else {}),
                            **({"actionHint": it.get("actionHint")} if isinstance(it.get("actionHint"), str) else {}),
                            **({"href": it.get("href")} if isinstance(it.get("href"), str) else {}),
                            **({"inputType": it.get("inputType")} if isinstance(it.get("inputType"), str) else {}),
                            **({"ref": it.get("ref")} if isinstance(it.get("ref"), str) else {}),
                            **({"inShadowDOM": True} if it.get("inShadowDOM") is True else {}),
                        }

                        center = it.get("center")
                        if isinstance(center, dict) and "x" in center and "y" in center:
                            cx = center.get("x")
                            cy = center.get("y")
                            compact["center"] = {"x": cx, "y": cy}
                            if isinstance(cx, (int, float)) and isinstance(cy, (int, float)):
                                coord_hint_v1 = f"click(x={float(cx):.1f}, y={float(cy):.1f})"
                                coord_hint_v2 = f"{{click:{{x:{float(cx):.1f}, y:{float(cy):.1f}}}}}"
                                if is_v2 and isinstance(compact.get("ref"), str):
                                    compact["actionHintAlt"] = coord_hint_v2
                                else:
                                    compact["actionHint"] = coord_hint_v2 if is_v2 else coord_hint_v1

                        bounds = it.get("bounds")
                        if overlay:
                            box = None
                            if isinstance(bounds, dict):
                                try:
                                    x = float(bounds.get("x", 0))
                                    y = float(bounds.get("y", 0))
                                    w = float(bounds.get("width", 0))
                                    h = float(bounds.get("height", 0))
                                    if w >= 2 and h >= 2:
                                        box = {"n": n, "x": x, "y": y, "width": w, "height": h}
                                except Exception:
                                    box = None
                            if box is None:
                                box = box_by_n.get(n)
                            if isinstance(box, dict):
                                boxes.append(box)
                                # Add a deterministic center for coordinate fallbacks (useful when refs fail).
                                if "center" not in compact:
                                    try:
                                        cx = float(box.get("x", 0)) + float(box.get("width", 0)) / 2.0
                                        cy = float(box.get("y", 0)) + float(box.get("height", 0)) / 2.0
                                        compact["center"] = {"x": cx, "y": cy}
                                        coord_hint_v1 = f"click(x={float(cx):.1f}, y={float(cy):.1f})"
                                        coord_hint_v2 = f"{{click:{{x:{float(cx):.1f}, y:{float(cy):.1f}}}}}"
                                        if is_v2 and isinstance(compact.get("ref"), str):
                                            compact["actionHintAlt"] = coord_hint_v2
                                        elif "actionHint" not in compact:
                                            compact["actionHint"] = coord_hint_v2 if is_v2 else coord_hint_v1
                                    except Exception:
                                        pass

                        compact_items.append(compact)

                if isinstance(locs, dict):
                    locs["items"] = compact_items

                loc_payload["overlay"] = {"enabled": overlay, "count": len(boxes)}

                overlay_id = "__mcp_overlay_locators"
                remove_js = (
                    "(() => {"
                    f"  const el = document.getElementById({json.dumps(overlay_id)});"
                    "  if (el) el.remove();"
                    "  return true;"
                    "})()"
                )
                inject_js = (
                    "(() => {"
                    f"  const id = {json.dumps(overlay_id)};"
                    "  const old = document.getElementById(id);"
                    "  if (old) old.remove();"
                    "  const root = document.createElement('div');"
                    "  root.id = id;"
                    "  root.style.position = 'fixed';"
                    "  root.style.left = '0';"
                    "  root.style.top = '0';"
                    "  root.style.width = '100%';"
                    "  root.style.height = '100%';"
                    "  root.style.pointerEvents = 'none';"
                    "  root.style.zIndex = '2147483647';"
                    "  root.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';"
                    f"  const boxes = {json.dumps(boxes)};"
                    "  for (const b of boxes) {"
                    "    if (!b) continue;"
                    "    const box = document.createElement('div');"
                    "    box.style.position = 'fixed';"
                    "    box.style.left = `${Math.max(0, b.x)}px`;"
                    "    box.style.top = `${Math.max(0, b.y)}px`;"
                    "    box.style.width = `${Math.max(0, b.width)}px`;"
                    "    box.style.height = `${Math.max(0, b.height)}px`;"
                    "    box.style.border = '2px solid rgba(0, 160, 255, 0.95)';"
                    "    box.style.background = 'rgba(0, 160, 255, 0.08)';"
                    "    box.style.boxSizing = 'border-box';"
                    "    const badge = document.createElement('div');"
                    "    badge.textContent = String(b.n);"
                    "    badge.style.position = 'absolute';"
                    "    badge.style.left = '-2px';"
                    "    badge.style.top = '-18px';"
                    "    badge.style.padding = '1px 6px';"
                    "    badge.style.fontSize = '12px';"
                    "    badge.style.lineHeight = '14px';"
                    "    badge.style.borderRadius = '10px';"
                    "    badge.style.color = 'white';"
                    "    badge.style.background = 'rgba(0, 160, 255, 0.95)';"
                    "    box.appendChild(badge);"
                    "    root.appendChild(box);"
                    "  }"
                    "  document.documentElement.appendChild(root);"
                    "  return { ok: true, count: boxes.length };"
                    "})()"
                )

                try:
                    if overlay and boxes:
                        with suppress(Exception):
                            tools.eval_js(config, inject_js)
                    shot = tools.screenshot(config)
                    data = shot.get("content_b64") or shot.get("data", "")
                    if store:
                        _attach_artifact_ref(config, loc_payload, args, kind="page_locators")
                    return ToolResult.with_image(render_ctx_markdown(loc_payload), data, "image/png")
                finally:
                    if overlay:
                        with suppress(Exception):
                            tools.eval_js(config, remove_js)

        result = tools.get_page_locators(
            config,
            kind=kind,
            offset=offset,
            limit=limit,
        )
        if store:
            _attach_artifact_ref(config, result, args, kind="page_locators")
    elif args.get("detail"):
        result = tools.analyze_page(
            config,
            detail=args["detail"],
            offset=args.get("offset", 0),
            limit=args.get("limit", 10),
            form_index=args.get("form_index"),
        )
        if store:
            _attach_artifact_ref(config, result, args, kind=f"page_{args.get('detail')}")
    else:
        # AI-native default: return triage (issues + affordances + next actions).
        # Fallback to legacy structural overview if diagnostics/telemetry are unavailable.
        try:
            result = tools.get_page_triage(config)
        except Exception:
            result = tools.analyze_page(config)
        if store:
            _attach_artifact_ref(config, result, args, kind="page_overview")

    return ToolResult.json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════════════


def handle_screenshot(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Take screenshot."""
    backend_dom_node_id: int | None = None
    if "backendDOMNodeId" in args:
        try:
            backend_dom_node_id = int(args.get("backendDOMNodeId"))
        except Exception:
            return ToolResult.error("backendDOMNodeId must be an integer")
    elif "ref" in args:
        backend_dom_node_id = _parse_dom_ref(args.get("ref"))
        if backend_dom_node_id is None:
            return ToolResult.error("ref must be a string like 'dom:123' (from page(detail='ax'))")

    result = tools.screenshot(
        config,
        selector=args.get("selector"),
        full_page=bool(args.get("full_page", False)),
        backend_dom_node_id=backend_dom_node_id,
    )
    # screenshot() returns content_b64, not data
    data = result.get("content_b64") or result.get("data", "")
    return ToolResult.image(data, "image/png")


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════


def handle_js(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Execute JavaScript."""
    result = tools.eval_js(config, args["code"])
    return ToolResult.json(result)


def handle_http(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """HTTP request outside browser."""
    from ...http_client import http_get
    from ...session import session_manager as _session_manager

    try:
        if _session_manager.get_policy().get("mode") == "strict" and not config.allow_hosts:
            return ToolResult.error(
                "Strict policy requires explicit MCP_ALLOW_HOSTS allowlist for http()",
                tool="http",
                suggestion='Set MCP_ALLOW_HOSTS (or switch to permissive via browser(action="policy", mode="permissive"))',
            )
    except Exception:
        pass

    result = http_get(args["url"], config)
    return ToolResult.json(result)


def handle_fetch(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Fetch from browser context."""
    result = tools.browser_fetch(
        config,
        url=args["url"],
        method=args.get("method", "GET"),
        body=args.get("body"),
        headers=args.get("headers"),
    )
    # Keep context window small: if body is large, store it as an artifact and
    # return only a preview + drilldown hint.
    try:
        body = result.get("body") if isinstance(result, dict) else None
        if isinstance(body, str) and len(body) > 2000:
            headers = result.get("headers") if isinstance(result.get("headers"), dict) else {}
            content_type = ""
            if isinstance(headers, dict):
                for k, v in headers.items():
                    if str(k).lower() == "content-type":
                        content_type = str(v or "")
                        break
            mime_type = "application/json" if "json" in content_type.lower() else "text/plain"
            ext = ".json" if mime_type == "application/json" else ".txt"

            total_chars = result.get("bodyLength")
            if not isinstance(total_chars, int):
                total_chars = len(body)
            stored_chars = len(body)
            truncated = bool(result.get("truncated", False))

            meta: dict[str, Any] = {
                "url": result.get("url"),
                "status": result.get("status"),
                "statusText": result.get("statusText"),
                "contentType": content_type,
                "method": args.get("method", "GET"),
            }
            ref = artifact_store.put_text(
                kind="fetch_body",
                text=body,
                mime_type=mime_type,
                ext=ext,
                total_chars=total_chars,
                stored_chars=stored_chars,
                truncated=truncated,
                metadata=meta,
            )

            result.pop("body", None)
            result["bodyPreview"] = body[:800].rstrip()
            result["bodyArtifact"] = {
                "id": ref.id,
                "kind": ref.kind,
                "mimeType": ref.mime_type,
                "bytes": ref.bytes,
                "createdAt": ref.created_at,
                "truncated": ref.truncated,
                **({"totalChars": ref.total_chars} if ref.total_chars is not None else {}),
                **({"storedChars": ref.stored_chars} if ref.stored_chars is not None else {}),
            }
            result["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]
    except Exception:
        pass
    return ToolResult.json(result)


def handle_app(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """High-level app macros/adapters for complex web apps (canvas-heavy UIs)."""
    app_name = str(args.get("app", "auto") or "auto").strip().lower()
    op = args.get("op")
    if not isinstance(op, str) or not op.strip():
        return ToolResult.error(
            "Missing op",
            tool="app",
            suggestion="Provide op='...' (e.g. op='diagram')",
        )
    op = op.strip()

    params = args.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return ToolResult.error(
            "params must be an object",
            tool="app",
            suggestion="Provide params={...}",
        )

    dry_run = bool(args.get("dry_run", False))

    url = _best_effort_current_url(config) or ""

    try:
        from ...apps import app_registry
        from ...apps.base import AppAdapterError
        from ...session import session_manager as _session_manager

        selection = app_registry.select(app=app_name, url=url)
        if selection is None:
            available = app_registry.available()
            return ToolResult.error(
                "No matching app adapter",
                tool="app",
                suggestion=(
                    "Provide app='miro' (or implement a new adapter), "
                    "and ensure you are on the target site in the current tab"
                ),
                details={"app": app_name, "url": url, "available": available},
            )

        try:
            # Hold one CDP connection across the whole macro (massive speedup, less flake).
            with _session_manager.shared_session(config):
                result = selection.adapter.invoke(config=config, op=op, params=params, dry_run=dry_run)
        except AppAdapterError as exc:
            return ToolResult.error(
                exc.reason,
                tool="app",
                suggestion=exc.suggestion,
                details={"app": exc.app, "op": exc.op, **(exc.details or {})},
            )

        if not isinstance(result, dict):
            result = {"result": result}

        out: dict[str, Any] = {
            "ok": True,
            "app": selection.adapter.name,
            "op": op,
            "matchedBy": selection.matched_by,
            **({"url": url} if url else {}),
            **result,
        }
        return ToolResult.json(out)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.error(
            str(exc),
            tool="app",
            suggestion="Check adapter availability and current URL; retry with app='miro' explicitly",
            details={"app": app_name, "op": op, "url": url},
        )


def handle_upload(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Upload file."""
    result = tools.upload_file(
        config,
        file_paths=args["file_paths"],
        selector=args.get("selector"),
    )
    return ToolResult.json(result)


def handle_download(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Wait for a download to complete and store it as an artifact (cognitive-cheap)."""
    try:
        timeout = float(args.get("timeout", 30))
    except Exception:
        timeout = 30.0
    timeout = max(1.0, min(timeout, 180.0))

    store = bool(args.get("store", True))
    sha256_enabled = bool(args.get("sha256", True))
    try:
        sha256_max_bytes = int(args.get("sha256_max_bytes", 209_715_200))
    except Exception:
        sha256_max_bytes = 209_715_200
    sha256_max_bytes = max(0, min(sha256_max_bytes, 2_000_000_000))
    baseline = args.get("_baseline")
    if not isinstance(baseline, list):
        baseline = None
    else:
        baseline = [str(x) for x in baseline if isinstance(x, str) and x]

    result = tools.wait_for_download(
        config,
        timeout=timeout,
        poll_interval=args.get("poll_interval", 0.2),
        stable_ms=args.get("stable_ms", 500),
        baseline=baseline,
    )

    if not store:
        return ToolResult.json(result)

    dl = result.get("download") if isinstance(result, dict) else None
    if not isinstance(dl, dict):
        return ToolResult.json(result)

    file_name = dl.get("fileName") if isinstance(dl.get("fileName"), str) else None
    mime_type = dl.get("mimeType") if isinstance(dl.get("mimeType"), str) else "application/octet-stream"
    rel_path = dl.get("path") if isinstance(dl.get("path"), str) else None

    # Resolve the downloaded file path safely (prefer repo-relative paths).
    src_path: Path | None = None
    if rel_path and not rel_path.startswith("/"):
        try:
            root = Path(artifact_store.base_dir).resolve().parent.parent
            candidate = (root / rel_path).resolve()
            if candidate.exists() and candidate.is_file():
                src_path = candidate
        except Exception:
            src_path = None

    if src_path is None and isinstance(file_name, str) and file_name:
        try:
            from ...session import session_manager as _session_manager

            tab_id = _session_manager.tab_id
            if tab_id:
                dl_dir = _session_manager.get_download_dir(tab_id)
                candidate = (dl_dir / file_name).resolve()
                if candidate.exists() and candidate.is_file():
                    src_path = candidate
        except Exception:
            src_path = None

    if src_path is None:
        # Keep the download metadata, but avoid failing the whole call.
        dl["stored"] = False
        dl["note"] = "Download detected but could not resolve file path for artifact storage"
        return ToolResult.json(result)

    sha256: str | None = None
    sha256_skipped = False
    if sha256_enabled:
        try:
            size = int(src_path.stat().st_size)
        except Exception:
            size = 0
        if sha256_max_bytes and size > sha256_max_bytes:
            sha256_skipped = True
        else:
            try:
                import hashlib

                h = hashlib.sha256()
                with src_path.open("rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
                sha256 = h.hexdigest()
            except Exception:
                sha256 = None

    ext = src_path.suffix if src_path.suffix else None
    ref = artifact_store.put_file(
        kind="download_file",
        src_path=src_path,
        mime_type=mime_type if isinstance(mime_type, str) else "application/octet-stream",
        ext=ext,
        metadata={
            "fileName": file_name,
            "mimeType": mime_type,
            "bytes": dl.get("bytes"),
            **({"sha256": sha256} if isinstance(sha256, str) and sha256 else {}),
            **({"sha256Skipped": True, "sha256MaxBytes": int(sha256_max_bytes)} if sha256_skipped else {}),
            "source": "download",
        },
    )

    # Attach a compact artifact pointer and v2-compatible drilldown hints.
    out = dict(result)
    out["stored"] = True
    out["artifact"] = {
        "id": ref.id,
        "kind": ref.kind,
        "mimeType": ref.mime_type,
        "bytes": ref.bytes,
        "createdAt": ref.created_at,
        **({"sha256": sha256} if isinstance(sha256, str) and sha256 else {}),
    }
    if sha256_skipped:
        out["artifact"]["sha256Skipped"] = True
        out["artifact"]["sha256MaxBytes"] = int(sha256_max_bytes)

    is_textish = (
        str(ref.mime_type or "").startswith("text/")
        or str(ref.mime_type or "")
        in {
            "application/json",
            "application/xml",
        }
        or str(ref.mime_type or "").endswith("+json")
    )
    if str(ref.mime_type or "").startswith("image/") or is_textish:
        out["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]
    else:
        out["next"] = [artifact_export_hint(artifact_id=ref.id, overwrite=False)]

    # Do not leak filesystem paths in the agent-visible output.
    try:
        if isinstance(out.get("download"), dict):
            out["download"].pop("path", None)
            if isinstance(sha256, str) and sha256:
                out["download"]["sha256"] = sha256
            if sha256_skipped:
                out["download"]["sha256Skipped"] = True
                out["download"]["sha256MaxBytes"] = int(sha256_max_bytes)
    except Exception:
        pass

    return ToolResult.json(out)


def handle_storage(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Storage operations (localStorage/sessionStorage) for use inside run/flow."""
    action = args.get("action", "list")
    storage = args.get("storage", "local")
    key = args.get("key")
    value = args.get("value")
    items = args.get("items")
    reveal = bool(args.get("reveal", False))
    store = bool(args.get("store", False))

    result = tools.storage_action(
        config,
        action=str(action or "list"),
        storage=str(storage or "local"),
        key=str(key) if isinstance(key, str) else None,
        value=value,
        items=items if isinstance(items, dict) else None,
        offset=args.get("offset", 0),
        limit=args.get("limit", 20),
        max_chars=args.get("max_chars", 2000),
        reveal=reveal,
    )

    # Optional: store revealed value off-context as an artifact (never by default).
    if store and str(action or "").strip().lower() == "get" and reveal:
        st = result.get("storage") if isinstance(result, dict) else None
        if isinstance(st, dict) and st.get("found") is True and isinstance(st.get("valuePreview"), str):
            text = st.get("valuePreview") or ""
            total_chars = st.get("totalChars") if isinstance(st.get("totalChars"), int) else len(text)
            truncated = bool(st.get("truncated", False)) or (len(text) < int(total_chars or 0))
            ref = artifact_store.put_text(
                kind="storage_value",
                text=str(text),
                mime_type="text/plain",
                ext=".txt",
                total_chars=int(total_chars) if isinstance(total_chars, int) else len(text),
                stored_chars=len(text),
                truncated=truncated,
                metadata={
                    "storage": st.get("storage"),
                    "key": st.get("key"),
                    "origin": st.get("origin"),
                    "url": st.get("url"),
                },
            )
            st.pop("valuePreview", None)
            st["valueArtifact"] = {
                "id": ref.id,
                "kind": ref.kind,
                "mimeType": ref.mime_type,
                "bytes": ref.bytes,
                "createdAt": ref.created_at,
                "truncated": ref.truncated,
                **({"totalChars": ref.total_chars} if ref.total_chars is not None else {}),
                **({"storedChars": ref.stored_chars} if ref.stored_chars is not None else {}),
            }
            st["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]

    return ToolResult.json(result)


def handle_dialog(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Handle JS dialog."""
    result = tools.handle_dialog(
        config,
        accept=args.get("accept", True),
        prompt_text=args.get("text"),
        timeout=args.get("timeout", 2.0),
    )
    return ToolResult.json(result)


def handle_totp(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Generate TOTP code."""
    result = tools.generate_totp(
        secret=args["secret"],
        digits=args.get("digits", 6),
        interval=args.get("interval", 30),
    )
    return ToolResult.json(result)


def handle_wait(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Wait for condition."""
    wait_for = args["for"]
    timeout = args.get("timeout", 10)

    start = time.time()

    if wait_for == "element":
        if not args.get("selector"):
            return ToolResult.error("'selector' required for element wait")
        result = tools.wait_for_element(config, args["selector"], timeout)
    elif wait_for in ("navigation", "load", "domcontentloaded", "networkidle"):
        result = _wait_for_condition(config, wait_for, timeout)
    elif wait_for == "text":
        result = tools.wait_for(config, condition="text", text=args.get("text"), timeout=timeout)
    else:
        return ToolResult.error(f"Unknown wait type: {wait_for}")

    result["waited_for"] = wait_for
    result["duration_ms"] = int((time.time() - start) * 1000)
    return ToolResult.json(result)


def handle_browser(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Browser control: lifecycle + policy + drilldowns (artifacts)."""
    action = args.get("action", "status")

    def _maybe_store_chrome_log(*, log_path: str | None, kind: str, export_name: str) -> dict[str, Any] | None:
        if not isinstance(log_path, str) or not log_path:
            return None
        try:
            p = Path(log_path)
            if not p.exists() or not p.is_file():
                return None
            raw = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        total_chars = len(raw)
        try:
            max_store_chars = int(os.environ.get("MCP_CHROME_LOG_MAX_CHARS", "200000"))
        except Exception:
            max_store_chars = 200_000
        max_store_chars = max(1, min(max_store_chars, 5_000_000))

        truncated = total_chars > max_store_chars
        stored = raw[-max_store_chars:] if truncated else raw

        try:
            ref = artifact_store.put_text(
                kind=kind,
                text=stored,
                mime_type="text/plain",
                ext=".log",
                total_chars=total_chars,
                stored_chars=len(stored),
                truncated=truncated,
                metadata={
                    "cdpPort": getattr(config, "cdp_port", None),
                    "headless": os.environ.get("MCP_HEADLESS", "1"),
                    "sourcePath": str(p.name),
                },
            )
        except Exception:
            return None

        payload: dict[str, Any] = {
            "artifact": {
                "id": ref.id,
                "kind": ref.kind,
                "mimeType": ref.mime_type,
                "bytes": ref.bytes,
                "createdAt": ref.created_at,
                "truncated": ref.truncated,
                **({"totalChars": ref.total_chars} if ref.total_chars is not None else {}),
                **({"storedChars": ref.stored_chars} if ref.stored_chars is not None else {}),
            },
            "next": [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)],
        }

        # Best-effort: export for user-visible debugging (outbox path, no absolute paths).
        try:
            exported = artifact_store.export(artifact_id=ref.id, name=export_name, overwrite=False)
            if isinstance(exported, dict) and isinstance(exported.get("export"), dict):
                payload["export"] = exported["export"]
        except Exception:
            pass
        return payload

    if action == "status":
        if getattr(config, "mode", "launch") == "extension":
            from ...session import session_manager as _session_manager

            gw = _session_manager.get_extension_gateway()
            gw_status = gw.status() if gw is not None else {"listening": False, "connected": False}
            gw_error = _session_manager.get_extension_gateway_error() if gw is None else None

            connected = bool(gw_status.get("connected"))
            listening = bool(gw_status.get("listening"))
            bind_error = gw_status.get("bindError") if isinstance(gw_status, dict) else None

            note = (
                "Extension mode: connected"
                if connected
                else (
                    "Extension mode: install/enable the Browser MCP extension in your normal Chrome. Connection should be automatic."
                )
            )

            if not connected and not listening and isinstance(bind_error, str) and bind_error:
                candidates = (
                    gw_status.get("portCandidates") if isinstance(gw_status.get("portCandidates"), list) else None
                )
                if candidates and all(isinstance(p, int) for p in candidates):
                    lo = int(candidates[0])
                    hi = int(candidates[-1])
                    note = (
                        f"Extension mode: gateway failed to bind (port conflict). "
                        f"Tried {lo}-{hi}; stop other gateway processes or set MCP_EXTENSION_PORT to a free base port."
                    )
                else:
                    note = (
                        "Extension mode: gateway failed to bind (port conflict). "
                        "Stop other gateway processes or set MCP_EXTENSION_PORT to a free base port."
                    )
            result = {
                "action": "status",
                "mode": "extension",
                "running": connected,
                "gateway": gw_status,
                **({"gatewayError": gw_error} if gw_error else {}),
                "note": note,
            }
        else:
            result = launcher.cdp_version()
            result["action"] = "status"
            result["running"] = result.get("status") == 200

    elif action == "launch":
        if getattr(config, "mode", "launch") == "extension":
            # UX: be forgiving. Users often call browser(action="launch") as "start the browser",
            # but in extension mode we control the user's already-running Chrome. Treat this as
            # a no-op "ensure gateway" + return status (non-error) with actionable guidance.
            from ...session import session_manager as _session_manager

            gw = _session_manager.get_extension_gateway()
            gw_error = _session_manager.get_extension_gateway_error() if gw is None else None

            # Best-effort: if the gateway wasn't created at startup (or failed), try again here.
            if gw is None:
                try:
                    from ...extension_gateway_shared import SharedExtensionGateway

                    gw = SharedExtensionGateway(
                        on_cdp_event=lambda tab_id, ev: _session_manager._ingest_tier0_event(tab_id, ev)  # noqa: SLF001
                    )
                    gw.start(wait_timeout=0.5, require_listening=False)
                    _session_manager.set_extension_gateway(gw)  # type: ignore[arg-type]
                    gw_error = None
                except Exception as exc:  # noqa: BLE001
                    gw = None
                    gw_error = str(exc)
                    with suppress(Exception):
                        _session_manager.set_extension_gateway_error(gw_error)

            # Best-effort: nudge the gateway thread to bind/retry.
            if gw is not None:
                try:
                    gw.start(wait_timeout=0.5, require_listening=False)
                except Exception as exc:  # noqa: BLE001
                    gw_error = str(exc)
                    with suppress(Exception):
                        _session_manager.set_extension_gateway_error(gw_error)

            gw_status = gw.status() if gw is not None else {"listening": False, "connected": False}
            return ToolResult.json(
                {
                    "action": "launch",
                    "mode": "extension",
                    "launched": False,
                    "running": bool(gw_status.get("connected")),
                    "gateway": gw_status,
                    **({"gatewayError": gw_error} if gw_error else {}),
                    "note": "Extension mode: nothing to launch (uses your normal Chrome).",
                    "suggestion": "Run browser(action='status') to verify connection, then use tabs/navigate/page/run/app.",
                }
            )
        if getattr(config, "mode", "launch") == "attach":
            return ToolResult.error(
                "Attach mode: cannot launch Chrome (this server is configured to attach to an existing browser)",
                tool="browser",
                suggestion="Start Chrome with --remote-debugging-port, or set MCP_BROWSER_MODE=launch",
            )
        try:
            timeout = float(args.get("timeout", 5.0))
        except Exception:
            timeout = 5.0
        timeout = max(1.0, min(timeout, 30.0))

        lr = None
        try:
            lr = launcher.ensure_running(timeout)
        except TypeError:
            # Backward-compat for tests/mocks that stub ensure_running() without a timeout arg.
            lr = launcher.ensure_running()
        launched = launcher.cdp_ready(timeout=0.6)

        result: dict[str, Any] = {"action": "launch", "launched": bool(launched)}
        if lr is not None and hasattr(lr, "started") and hasattr(lr, "message") and hasattr(lr, "command"):
            result["launch"] = {
                "started": bool(getattr(lr, "started", False)),
                "message": str(getattr(lr, "message", "")),
                "command": list(getattr(lr, "command", []) or []),
            }

            if not launched:
                log_info = _maybe_store_chrome_log(
                    log_path=getattr(lr, "log_path", None),
                    kind="chrome_launch_log",
                    export_name="chrome_launch.log",
                )
                if isinstance(log_info, dict):
                    result["launch"]["log"] = log_info

    elif action == "recover":
        # Emergency recovery for "port open but /json/version hangs" and dialog-brick states.
        from ...session import session_manager as _session_manager

        if getattr(config, "mode", "launch") == "extension":
            gw = _session_manager.get_extension_gateway()
            before_tab = _session_manager.tab_id
            before_connected = bool(gw is not None and gw.is_connected())

            reset = _session_manager.recover_reset()

            # Best-effort: create a fresh tab for the session (visible to the user).
            new_tab: str | None = None
            if before_connected:
                try:
                    if isinstance(before_tab, str) and before_tab:
                        _session_manager.close_tab(config, before_tab)
                except Exception:
                    pass
                try:
                    new_tab = _session_manager.new_tab(config, "about:blank")
                except Exception:
                    new_tab = None

            after_connected = bool(gw is not None and gw.is_connected())
            result = {
                "action": "recover",
                "ok": bool(after_connected and new_tab),
                "mode": "extension",
                "before": {"connected": before_connected, "sessionTabId": before_tab},
                "after": {"connected": after_connected, "sessionTabId": new_tab},
                "reset": reset,
            }
            return ToolResult.json(result)

        attach_mode = getattr(config, "mode", "launch") == "attach"
        hard = bool(args.get("hard", False))
        try:
            timeout = float(args.get("timeout", 5.0))
        except Exception:
            timeout = 5.0
        timeout = max(1.0, min(timeout, 30.0))

        before_ready = launcher.cdp_ready(timeout=0.4)
        before_tab = _session_manager.tab_id

        # Always clear in-memory state to prevent leaks (safe even if Chrome is hung).
        reset = _session_manager.recover_reset()

        if attach_mode:
            # In attach mode we are not allowed to spawn/replace Chrome. Best-effort: if CDP is up,
            # create a fresh isolated tab; otherwise return a deterministic failure.
            new_tab: str | None = None
            if before_ready:
                try:
                    if isinstance(before_tab, str) and before_tab:
                        _session_manager.close_tab(config, before_tab)
                except Exception:
                    pass
                try:
                    new_tab = _session_manager.new_tab(config, "about:blank")
                except Exception:
                    new_tab = None

            after_ready = launcher.cdp_ready(timeout=0.6)
            result = {
                "action": "recover",
                "ok": bool(after_ready and new_tab),
                "mode": "soft",
                "note": "Attach mode: cannot restart Chrome automatically; restart your browser with --remote-debugging-port if CDP is down",
                "before": {"cdpReady": before_ready, "sessionTabId": before_tab},
                "after": {"cdpReady": after_ready, "sessionTabId": new_tab},
                "reset": reset,
            }
            return ToolResult.json(result)

        mode = "soft"
        launch_res: dict[str, Any] | None = None

        if hard or not before_ready:
            mode = "hard"

        if mode == "hard":
            # Prefer autonomous recovery: if we don't own the existing Chrome process,
            # attempt to launch an owned Chrome instance (port fallback may kick in).
            lr = None
            if launcher.process is None:
                try:
                    lr = launcher.ensure_running(timeout)
                except TypeError:
                    lr = launcher.ensure_running()
            else:
                try:
                    lr = launcher.restart(timeout)
                except TypeError:
                    lr = launcher.restart()

            if lr is not None and hasattr(lr, "started") and hasattr(lr, "message") and hasattr(lr, "command"):
                launch_res = {
                    "started": bool(getattr(lr, "started", False)),
                    "message": str(getattr(lr, "message", "")),
                    "command": list(getattr(lr, "command", []) or []),
                }
                if not bool(getattr(lr, "started", False)):
                    log_info = _maybe_store_chrome_log(
                        log_path=getattr(lr, "log_path", None),
                        kind="chrome_recover_log",
                        export_name="chrome_recover.log",
                    )
                    if isinstance(log_info, dict):
                        launch_res["log"] = log_info
            else:
                launch_res = {"started": False, "message": "Recovery attempted", "command": []}
            # Keep the handler's config in sync with the launcher (may have port/profile fallback).
            with suppress(Exception):
                config.cdp_port = launcher.config.cdp_port
            with suppress(Exception):
                config.profile_path = launcher.config.profile_path

        after_ready = launcher.cdp_ready(timeout=0.6)

        # Create a fresh isolated tab to ensure session recovery is complete.
        new_tab: str | None = None
        if after_ready:
            try:
                # Best-effort: close the old isolated tab (keeps browser tidy).
                if isinstance(before_tab, str) and before_tab:
                    _session_manager.close_tab(config, before_tab)
            except Exception:
                pass

            try:
                new_tab = _session_manager.new_tab(config, "about:blank")
            except Exception:
                new_tab = None

        result = {
            "action": "recover",
            "ok": bool(after_ready and new_tab),
            "mode": mode,
            "before": {"cdpReady": before_ready, "sessionTabId": before_tab},
            "after": {"cdpReady": after_ready, "sessionTabId": new_tab},
            "reset": reset,
            **({"launch": launch_res} if launch_res is not None else {}),
        }

    elif action == "policy":
        # Safety-as-mode: strict/permissive.
        from ...session import session_manager as _session_manager

        mode = args.get("mode")
        if isinstance(mode, str) and mode.strip():
            policy = _session_manager.set_policy(mode)
            result = {"action": "policy", "updated": True, "policy": policy}
        else:
            result = {"action": "policy", "policy": _session_manager.get_policy()}

        if isinstance(result.get("policy"), dict):
            pol = result["policy"]
            if pol.get("mode") == "strict" and not config.allow_hosts:
                result["note"] = (
                    "Strict mode: set MCP_ALLOW_HOSTS to an explicit allowlist or navigation/fetch will be blocked"
                )

    elif action == "dom":
        if launcher is not None and getattr(config, "mode", "launch") != "extension":
            launcher.ensure_running()
        if bool(args.get("store", False)):
            # Store full DOM HTML as an artifact (keeps context window small).
            selector = args.get("selector")
            try:
                max_store_chars = int(os.environ.get("MCP_ARTIFACT_MAX_CHARS", "5000000"))
            except Exception:
                max_store_chars = 5_000_000
            max_store_chars = max(1, min(max_store_chars, 50_000_000))

            with tools.get_session(config) as (session, target):
                if selector:
                    # Reuse the existing deep-query implementation, but without the 200k cap.
                    dom_data = tools.get_dom(
                        config, selector=selector, max_chars=max_store_chars, include_metadata=True
                    )
                    html = str(dom_data.get("html") or "")
                    total_chars = int(dom_data.get("totalChars") or len(html))
                else:
                    html = session.get_dom()
                    total_chars = len(html)

                truncated = total_chars > max_store_chars
                html_to_store = html[:max_store_chars] if truncated else html

                url = session.get_url()
                title = session.get_title()

            ref = artifact_store.put_text(
                kind="dom_html",
                text=html_to_store,
                mime_type="text/html",
                ext=".html",
                total_chars=total_chars,
                stored_chars=len(html_to_store),
                truncated=truncated,
                metadata={
                    "url": url,
                    "title": title,
                    **({"selector": selector} if selector else {}),
                },
            )

            result = {
                "action": "dom",
                "stored": True,
                "artifact": {
                    "id": ref.id,
                    "kind": ref.kind,
                    "mimeType": ref.mime_type,
                    "bytes": ref.bytes,
                    "createdAt": ref.created_at,
                    "truncated": ref.truncated,
                    **({"totalChars": ref.total_chars} if ref.total_chars is not None else {}),
                    **({"storedChars": ref.stored_chars} if ref.stored_chars is not None else {}),
                },
                "page": {"url": url, "title": title},
                "next": [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)],
                "target": target["id"],
                "sessionTabId": tools.get_session_tab_id(),
            }
        else:
            result = tools.get_dom(
                config,
                selector=args.get("selector"),
                max_chars=args.get("max_chars", 50000),
            )
            result["action"] = "dom"

    elif action == "artifact":
        # North Star (v2) drilldown path: keep artifacts accessible without exposing a separate tool.
        artifact_action = str(args.get("artifact_action", "list") or "list").lower()
        if artifact_action == "list":
            items = artifact_store.list(limit=args.get("limit", 20), kind=args.get("kind"))
            result = {
                "action": "artifact",
                "artifact_action": "list",
                "ok": True,
                "artifacts": items,
                "total": len(items),
            }
        elif artifact_action == "get":
            artifact_id = args.get("id")
            if not artifact_id:
                return ToolResult.error(
                    "'id' required for get",
                    tool="browser",
                    suggestion=f"Use {artifact_list_hint(limit=20)}",
                )
            try:
                meta = artifact_store.get_meta(artifact_id=artifact_id)
                mime = str(meta.get("mimeType") or "text/plain")
                if mime.startswith("image/"):
                    from ..ai_format import render_ctx_markdown

                    payload, data_b64, mime_type = artifact_store.get_image_b64(artifact_id=artifact_id)
                    # Hide local path in the agent-visible payload (cognitive + privacy).
                    if isinstance(payload, dict):
                        art = payload.get("artifact")
                        if isinstance(art, dict):
                            art.pop("path", None)
                    return ToolResult.with_image(render_ctx_markdown(payload), data_b64, mime_type, data=payload)

                # Binary payloads are not streamable as text; keep output decision-centric.
                is_textish = (
                    mime.startswith("text/")
                    or mime in {"application/json", "application/xml"}
                    or mime.endswith("+json")
                )
                if not is_textish:
                    payload = {
                        "action": "artifact",
                        "artifact_action": "get",
                        "ok": True,
                        "artifact": {
                            "id": meta.get("id"),
                            "kind": meta.get("kind"),
                            "mimeType": meta.get("mimeType"),
                            "bytes": meta.get("bytes"),
                            "createdAt": meta.get("createdAt"),
                        },
                        "note": "Binary artifact is not streamable as text; export it to outbox to access the file",
                        "next": [artifact_export_hint(artifact_id=str(artifact_id), overwrite=False)],
                    }
                    return ToolResult.json(payload)

                offset = args.get("offset", 0)
                max_chars = args.get("max_chars", 4000)
                try:
                    offset_i = int(offset or 0)
                except Exception:
                    offset_i = 0
                offset_i = max(0, offset_i)
                try:
                    max_chars_i = int(max_chars or 4000)
                except Exception:
                    max_chars_i = 4000
                max_chars_i = max(200, min(max_chars_i, 4000))

                data = artifact_store.get_text_slice(artifact_id=artifact_id, offset=offset_i, max_chars=max_chars_i)
                artifact = data.get("artifact") if isinstance(data, dict) else None
                text = data.get("text") if isinstance(data, dict) else ""
                if not isinstance(artifact, dict):
                    return ToolResult.error(
                        "Invalid artifact payload",
                        tool="browser",
                        suggestion=f"Use {artifact_list_hint(limit=20)}",
                    )

                artifact.pop("path", None)

                # Use the same (context-format) layout as the legacy artifact tool: cheap + deterministic.
                lines: list[str] = ["[CONTENT]"]
                lines.append(f"artifact.id: {artifact.get('id')}")
                lines.append(f"artifact.kind: {artifact.get('kind')}")
                lines.append(f"artifact.mimeType: {artifact.get('mimeType')}")
                lines.append(f"artifact.bytes: {artifact.get('bytes')}")
                lines.append(f"artifact.createdAt: {artifact.get('createdAt')}")
                lines.append(f"slice.offset: {artifact.get('offset')}")
                lines.append(f"slice.returnedChars: {artifact.get('returnedChars')}")
                lines.append(f"slice.totalChars: {artifact.get('totalChars')}")
                lines.append(f"slice.truncated: {artifact.get('truncated')}")

                if artifact.get("truncated"):
                    try:
                        next_offset = int(artifact.get("offset") or 0) + int(artifact.get("returnedChars") or 0)
                    except Exception:
                        next_offset = None
                    if next_offset is not None:
                        lines.append(
                            f"next: {artifact_get_hint(artifact_id=str(artifact_id), offset=next_offset, max_chars=max_chars_i)}"
                        )

                mime_type = str(artifact.get("mimeType") or "")
                if mime_type.startswith("text/html"):
                    lang = "html"
                elif mime_type == "application/json":
                    lang = "json"
                else:
                    lang = ""
                fence = "```"
                header = f"{fence}{lang}".rstrip()
                lines.append("text:")
                lines.append(header)
                lines.append(str(text or "").rstrip("\n"))
                lines.append(fence)
                return ToolResult.text("\n".join(lines))
            except FileNotFoundError:
                return ToolResult.error(
                    "Artifact not found", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
            except ValueError:
                return ToolResult.error(
                    "Invalid artifact id", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult.error(str(exc), tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}")
        elif artifact_action == "delete":
            artifact_id = args.get("id")
            if not artifact_id:
                return ToolResult.error(
                    "'id' required for delete",
                    tool="browser",
                    suggestion=f"Use {artifact_list_hint(limit=20)}",
                )
            try:
                ok = artifact_store.delete(artifact_id=artifact_id)
                result = {"action": "artifact", "artifact_action": "delete", "ok": ok, "deleted": ok, "id": artifact_id}
            except FileNotFoundError:
                return ToolResult.error(
                    "Artifact not found", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
            except ValueError:
                return ToolResult.error(
                    "Invalid artifact id", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
        elif artifact_action == "export":
            artifact_id = args.get("id")
            if not artifact_id:
                return ToolResult.error(
                    "'id' required for export",
                    tool="browser",
                    suggestion=f"Use {artifact_list_hint(limit=20)}",
                )
            try:
                name = args.get("name")
                overwrite = bool(args.get("overwrite", False))
                result = artifact_store.export(
                    artifact_id=str(artifact_id), name=str(name) if isinstance(name, str) else None, overwrite=overwrite
                )
            except FileExistsError:
                return ToolResult.error(
                    "Export destination exists",
                    tool="browser",
                    suggestion="Re-run with overwrite=true or choose a different name",
                )
            except FileNotFoundError:
                return ToolResult.error(
                    "Artifact not found", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
            except ValueError:
                return ToolResult.error(
                    "Invalid artifact id", tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}"
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult.error(str(exc), tool="browser", suggestion=f"Use {artifact_list_hint(limit=20)}")
        else:
            return ToolResult.error(
                f"Unknown artifact_action: {artifact_action}",
                tool="browser",
                suggestion='Use artifact_action="list" | "get" | "delete" | "export"',
            )

    elif action == "element":
        if not args.get("selector"):
            return ToolResult.error("'selector' required for element")
        if launcher is not None and getattr(config, "mode", "launch") != "extension":
            launcher.ensure_running()
        result = tools.get_element_info(config, args["selector"])
        result["action"] = "element"

    else:
        return ToolResult.error(f"Unknown action: {action}")

    return ToolResult.json(result)


def handle_artifact(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
    """Artifact store: list/get/delete."""
    from ..ai_format import render_ctx_markdown

    action = args.get("action", "list")

    if action == "list":
        items = artifact_store.list(limit=args.get("limit", 20), kind=args.get("kind"))
        return ToolResult.json({"ok": True, "artifacts": items, "total": len(items)})

    if action == "get":
        artifact_id = args.get("id")
        if not artifact_id:
            return ToolResult.error(
                "'id' required for get",
                tool="artifact",
                suggestion=f"Use {artifact_list_hint(limit=20)}",
            )

        try:
            meta = artifact_store.get_meta(artifact_id=artifact_id)
            mime = str(meta.get("mimeType") or "text/plain")
            if mime.startswith("image/"):
                payload, data_b64, mime_type = artifact_store.get_image_b64(artifact_id=artifact_id)
                return ToolResult.with_image(render_ctx_markdown(payload), data_b64, mime_type)

            is_textish = (
                mime.startswith("text/") or mime in {"application/json", "application/xml"} or mime.endswith("+json")
            )
            if not is_textish:
                payload = {
                    "ok": True,
                    "tool": "artifact",
                    "action": "get",
                    "artifact": {
                        "id": meta.get("id"),
                        "kind": meta.get("kind"),
                        "mimeType": meta.get("mimeType"),
                        "bytes": meta.get("bytes"),
                        "createdAt": meta.get("createdAt"),
                    },
                    "note": "Binary artifact is not streamable as text; export it to outbox to access the file",
                    "next": [artifact_export_hint(artifact_id=str(artifact_id), overwrite=False)],
                }
                return ToolResult.json(payload)

            offset = args.get("offset", 0)
            max_chars = args.get("max_chars", 4000)
            try:
                offset_i = int(offset or 0)
            except Exception:
                offset_i = 0
            offset_i = max(0, offset_i)
            try:
                max_chars_i = int(max_chars or 4000)
            except Exception:
                max_chars_i = 4000
            max_chars_i = max(200, min(max_chars_i, 4000))

            data = artifact_store.get_text_slice(artifact_id=artifact_id, offset=offset_i, max_chars=max_chars_i)
            artifact = data.get("artifact") if isinstance(data, dict) else None
            text = data.get("text") if isinstance(data, dict) else ""
            if not isinstance(artifact, dict):
                return ToolResult.error(
                    "Invalid artifact payload",
                    tool="artifact",
                    suggestion=f"Use {artifact_list_hint(limit=20)}",
                )

            # Keep output cognitively cheap: do not leak local paths by default.
            artifact.pop("path", None)

            lines: list[str] = ["[CONTENT]"]
            lines.append(f"artifact.id: {artifact.get('id')}")
            lines.append(f"artifact.kind: {artifact.get('kind')}")
            lines.append(f"artifact.mimeType: {artifact.get('mimeType')}")
            lines.append(f"artifact.bytes: {artifact.get('bytes')}")
            lines.append(f"artifact.createdAt: {artifact.get('createdAt')}")
            lines.append(f"slice.offset: {artifact.get('offset')}")
            lines.append(f"slice.returnedChars: {artifact.get('returnedChars')}")
            lines.append(f"slice.totalChars: {artifact.get('totalChars')}")
            lines.append(f"slice.truncated: {artifact.get('truncated')}")

            if artifact.get("truncated"):
                try:
                    next_offset = int(artifact.get("offset") or 0) + int(artifact.get("returnedChars") or 0)
                except Exception:
                    next_offset = None
                if next_offset is not None:
                    lines.append(
                        f"next: {artifact_get_hint(artifact_id=str(artifact_id), offset=next_offset, max_chars=max_chars_i)}"
                    )

            mime_type = str(artifact.get("mimeType") or "")
            if mime_type.startswith("text/html"):
                lang = "html"
            elif mime_type == "application/json":
                lang = "json"
            else:
                lang = ""
            fence = "```"
            header = f"{fence}{lang}".rstrip()
            lines.append("text:")
            lines.append(header)
            lines.append(str(text or "").rstrip("\n"))
            lines.append(fence)
            return ToolResult.text("\n".join(lines))
        except FileNotFoundError:
            return ToolResult.error(
                "Artifact not found", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )
        except ValueError:
            return ToolResult.error(
                "Invalid artifact id", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error(str(exc), tool="artifact", suggestion="Try listing artifacts first")

    if action == "delete":
        artifact_id = args.get("id")
        if not artifact_id:
            return ToolResult.error(
                "'id' required for delete",
                tool="artifact",
                suggestion=f"Use {artifact_list_hint(limit=20)}",
            )
        try:
            ok = artifact_store.delete(artifact_id=artifact_id)
            return ToolResult.json({"ok": ok, "deleted": ok, "id": artifact_id})
        except FileNotFoundError:
            return ToolResult.error(
                "Artifact not found", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )
        except ValueError:
            return ToolResult.error(
                "Invalid artifact id", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )

    if action == "export":
        artifact_id = args.get("id")
        if not artifact_id:
            return ToolResult.error(
                "'id' required for export",
                tool="artifact",
                suggestion=f"Use {artifact_list_hint(limit=20)}",
            )
        try:
            name = args.get("name")
            overwrite = bool(args.get("overwrite", False))
            result = artifact_store.export(
                artifact_id=str(artifact_id), name=str(name) if isinstance(name, str) else None, overwrite=overwrite
            )
            return ToolResult.json(result)
        except FileExistsError:
            return ToolResult.error(
                "Export destination exists",
                tool="artifact",
                suggestion="Re-run with overwrite=true or choose a different name",
            )
        except FileNotFoundError:
            return ToolResult.error(
                "Artifact not found", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )
        except ValueError:
            return ToolResult.error(
                "Invalid artifact id", tool="artifact", suggestion=f"Use {artifact_list_hint(limit=20)}"
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error(str(exc), tool="artifact", suggestion="Try listing artifacts first")

    return ToolResult.error(
        f"Unknown action: {action}",
        tool="artifact",
        suggestion="Use action='list' | 'get' | 'delete' | 'export'",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _attach_artifact_ref(config: BrowserConfig, payload: Any, args: dict[str, Any], *, kind: str) -> None:
    """Store full payload as JSON artifact and attach a compact pointer to the response payload.

    This is intentionally mutation-based (in-place) to avoid returning large payloads in tool output.
    """
    if not isinstance(payload, dict):
        return

    # Store a snapshot of the payload BEFORE adding pointers (avoid self-references).
    metadata: dict[str, Any] = {"tool": "page"}
    for k in (
        "detail",
        "offset",
        "limit",
        "since",
        "sort",
        "role",
        "name",
        "kind",
        "info",
        "clear",
        "with_screenshot",
        "overlay",
        "overlay_limit",
        "form_index",
    ):
        if k in args:
            metadata[k] = args.get(k)

    # Best-effort page identity for correlation (never required).
    try:
        info = tools.get_page_info(config)
        pi = info.get("pageInfo") if isinstance(info, dict) else None
        if isinstance(pi, dict):
            url = pi.get("url")
            title = pi.get("title")
            if url or title:
                metadata["page"] = {"url": url, "title": title}
    except Exception:
        pass

    ref = artifact_store.put_json(kind=kind, obj=payload, metadata=metadata)

    payload["stored"] = True
    payload["artifact"] = {
        "id": ref.id,
        "kind": ref.kind,
        "mimeType": ref.mime_type,
        "bytes": ref.bytes,
        "createdAt": ref.created_at,
    }

    hint = artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)
    nxt = payload.get("next")
    if not isinstance(nxt, list):
        payload["next"] = []
        nxt = payload["next"]
    if hint not in nxt:
        nxt.insert(0, hint)


def _attach_screenshot_ref(
    config: BrowserConfig, payload: Any, args: dict[str, Any], *, data_b64: str, kind: str
) -> None:
    """Store a screenshot as an artifact and attach a compact pointer.

    Intended for `page(..., with_screenshot=true, store=true)` so agents can both SEE the image
    and later drill down/share it without re-running the capture.
    """
    if not isinstance(payload, dict):
        return
    if not isinstance(data_b64, str) or not data_b64:
        return

    metadata: dict[str, Any] = {"tool": "page", "mimeType": "image/png"}
    for k in ("detail", "since", "offset", "limit", "sort", "with_screenshot", "overlay", "overlay_limit"):
        if k in args:
            metadata[k] = args.get(k)

    try:
        info = tools.get_page_info(config)
        pi = info.get("pageInfo") if isinstance(info, dict) else None
        if isinstance(pi, dict):
            url = pi.get("url")
            title = pi.get("title")
            if url or title:
                metadata["page"] = {"url": url, "title": title}
    except Exception:
        pass

    try:
        ref = artifact_store.put_image_b64(kind=kind, data_b64=data_b64, mime_type="image/png", metadata=metadata)
    except Exception:
        return

    payload["screenshotArtifact"] = {
        "id": ref.id,
        "kind": ref.kind,
        "mimeType": ref.mime_type,
        "bytes": ref.bytes,
        "createdAt": ref.created_at,
    }

    hint = artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)
    nxt = payload.get("next")
    if not isinstance(nxt, list):
        payload["next"] = []
        nxt = payload["next"]
    if hint not in nxt:
        nxt.insert(0, hint)
    elif nxt:
        payload["next"] = [hint, str(nxt)]
    else:
        payload["next"] = [hint]


def _wait_for_condition(config: BrowserConfig, condition: str, timeout: float = 10) -> dict[str, Any]:
    """Wait for navigation/load condition."""
    try:
        result = tools.wait_for(config, condition=condition, timeout=timeout)
        # Compatibility: some call sites/tests use `found`, canonical tool uses `success`.
        found = bool(result.get("success") if "success" in result else result.get("found"))
        return {"found": found, **result}
    except Exception:
        return {"found": False, "timeout": True}


def _wait_for_url_change(config: BrowserConfig, old_url: str | None, timeout: float = 2.0) -> str | None:
    """Best-effort URL change detection that works for both full navigations and SPA route changes."""

    if not old_url:
        return None

    # Avoid Tier-1 diagnostics injection here; navigation detection must stay cheap and robust.
    with tools.get_session(config, ensure_diagnostics=False) as (session, _target):
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            cur = None

            # Prefer CDP navigation history (works even when JS is blocked by dialogs).
            try:
                nav = session.send("Page.getNavigationHistory")
                if isinstance(nav, dict):
                    idx = nav.get("currentIndex")
                    entries = nav.get("entries")
                    if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                        entry = entries[idx] if isinstance(entries[idx], dict) else None
                        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                            cur = entry.get("url")
            except Exception:
                cur = None

            if cur is None:
                try:
                    cur = session.eval_js("window.location.href")
                except Exception:
                    cur = None

            if isinstance(cur, str) and cur and cur != old_url:
                return cur

            time.sleep(0.15)

    return None


def _best_effort_current_url(config: BrowserConfig) -> str | None:
    """Return current URL without assuming Runtime.evaluate works (dialogs can block JS)."""
    try:
        with tools.get_session(config, ensure_diagnostics=False) as (session, _target):
            try:
                nav = session.send("Page.getNavigationHistory")
                if isinstance(nav, dict):
                    idx = nav.get("currentIndex")
                    entries = nav.get("entries")
                    if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                        entry = entries[idx] if isinstance(entries[idx], dict) else None
                        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                            url = entry.get("url")
                            if isinstance(url, str) and url:
                                return url
            except Exception:
                pass

            try:
                url = session.eval_js("window.location.href")
                return url if isinstance(url, str) and url else None
            except Exception:
                return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

UNIFIED_HANDLERS: dict[str, tuple] = {
    # Core
    "page": (handle_page, True),
    "navigate": (handle_navigate, True),
    "app": (handle_app, True),
    "click": (handle_click, True),
    "type": (handle_type, True),
    "scroll": (handle_scroll, True),
    "form": (handle_form, True),
    "screenshot": (handle_screenshot, True),
    # Management
    "tabs": (handle_tabs, True),
    "cookies": (handle_cookies, True),
    "captcha": (handle_captcha, True),
    # Low-level
    "mouse": (handle_mouse, True),
    "resize": (handle_resize, True),
    # Utility
    "js": (handle_js, True),
    "http": (handle_http, False),
    "fetch": (handle_fetch, True),
    "upload": (handle_upload, True),
    "download": (handle_download, True),
    "storage": (handle_storage, True),
    "dialog": (handle_dialog, True),
    "totp": (handle_totp, False),
    "wait": (handle_wait, True),
    "browser": (handle_browser, False),
    "artifact": (handle_artifact, False),
}
