"""
Accessibility (AX) based interactions via Chrome DevTools Protocol.

Why this exists:
- Complex SPAs (Miro/Figma/etc.) often have unstable DOM/CSS structure.
- Accessibility tree offers stable "role" + "name" handles.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session, with_retry


def _ax_value(value: Any) -> Any:
    """CDP AXValue is usually a dict with {type,value}. Return the underlying value."""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _norm_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


_AX_ROLE_ALIASES: dict[str, set[str]] = {
    "input": {"textbox", "searchbox", "combobox", "listbox", "textfield", "text"},
    "text": {"textbox", "textfield", "text"},
    "textfield": {"textbox", "textfield", "text"},
    "textbox": {"textbox", "textfield", "text"},
    "searchbox": {"searchbox", "textbox", "textfield", "text"},
    "textarea": {"textbox", "textfield", "text"},
    "combobox": {"combobox"},
    "listbox": {"listbox"},
}


def _normalize_role_query(role: str | None) -> tuple[str | None, set[str] | None]:
    r = _norm_text(role) if isinstance(role, str) and role.strip() else ""
    if not r:
        return None, None
    aliases = _AX_ROLE_ALIASES.get(r)
    if aliases:
        allowed = {a for a in aliases if a}
        # Avoid over-filtering queryAXTree when role has multiple aliases.
        query_role = r if len(allowed) == 1 else None
        return query_role, allowed
    return r, {r}


def _get_ax_nodes(session) -> list[dict[str, Any]]:
    """Fetch full AX tree nodes (best-effort)."""
    try:
        res = session.send("Accessibility.getFullAXTree")
    except Exception as exc:  # noqa: BLE001
        raise SmartToolError(
            tool="ax",
            action="getFullAXTree",
            reason=str(exc),
            suggestion="Try reload, or fall back to click(text=...) / click(selector=...)",
        ) from exc

    nodes = res.get("nodes") if isinstance(res, dict) else None
    if not isinstance(nodes, list):
        raise SmartToolError(
            tool="ax",
            action="parse",
            reason="Accessibility.getFullAXTree returned unexpected payload",
            suggestion="Try again or use non-AX locators",
        )

    out: list[dict[str, Any]] = []
    for n in nodes:
        if isinstance(n, dict):
            out.append(n)
    return out


def _query_ax_tree(session, *, role: str | None, name: str | None) -> list[dict[str, Any]] | None:
    """Try to query AX tree via CDP (more targeted than full tree). Returns None if unsupported."""
    params: dict[str, Any] = {}
    if isinstance(role, str) and role.strip():
        params["role"] = role
    if isinstance(name, str) and name.strip():
        params["accessibleName"] = name
    if not params:
        return None

    try:
        res = session.send("Accessibility.queryAXTree", params)
    except Exception:
        return None

    nodes = res.get("nodes") if isinstance(res, dict) else None
    if not isinstance(nodes, list):
        return None

    out: list[dict[str, Any]] = []
    for n in nodes:
        if isinstance(n, dict):
            out.append(n)
    return out


def _ax_bool_prop(node: dict[str, Any], prop_name: str) -> bool | None:
    props = node.get("properties")
    if not isinstance(props, list):
        return None
    for p in props:
        if not isinstance(p, dict):
            continue
        if p.get("name") != prop_name:
            continue
        v = _ax_value(p.get("value"))
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() in {"true", "false"}:
            return v.lower() == "true"
    return None


def _search_ax_items(
    nodes: list[dict[str, Any]],
    *,
    role: str | None,
    name: str | None,
    allowed_roles: set[str] | None = None,
    hard_limit: int = 2000,
) -> list[dict[str, Any]]:
    if allowed_roles:
        role_set = {_norm_text(r) for r in allowed_roles if isinstance(r, str) and r.strip()}
    else:
        role_set = {_norm_text(role)} if isinstance(role, str) and role.strip() else set()
    q_name = _norm_text(name) if isinstance(name, str) and name.strip() else ""

    scored: list[tuple[int, dict[str, Any]]] = []
    scanned = 0
    for node in nodes:
        scanned += 1
        if scanned > hard_limit:
            break
        if node.get("ignored") is True:
            continue

        node_role = _norm_text(str(_ax_value(node.get("role")) or ""))
        node_name = _norm_text(str(_ax_value(node.get("name")) or ""))

        if role_set and node_role not in role_set:
            continue

        score = _score_match(query_name=q_name, node_name=node_name)
        if q_name and score < 0:
            continue

        backend_id = node.get("backendDOMNodeId") or node.get("backendDomNodeId") or 0
        backend_dom_node_id: int | None = None
        if isinstance(backend_id, (int, float)):
            backend_dom_node_id = int(backend_id)
        focusable = _ax_bool_prop(node, "focusable")
        disabled = _ax_bool_prop(node, "disabled")

        item: dict[str, Any] = {
            "role": str(_ax_value(node.get("role")) or ""),
            "name": str(_ax_value(node.get("name")) or ""),
            "backendDOMNodeId": backend_dom_node_id if backend_dom_node_id is not None else backend_id,
            **({"focusable": focusable} if focusable is not None else {}),
            **({"disabled": disabled} if disabled is not None else {}),
        }
        if backend_dom_node_id:
            item["ref"] = f"dom:{backend_dom_node_id}"

        scored.append((score + (10 if focusable else 0) + (-20 if disabled else 0), item))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [it for _score, it in scored]


def _score_match(*, query_name: str, node_name: str) -> int:
    """Higher is better."""
    if not query_name:
        return 0
    if not node_name:
        return -10
    if node_name == query_name:
        return 100
    if node_name.startswith(query_name):
        return 80
    if query_name in node_name:
        return 50
    return -1


def _pick_index(n: int, index: int) -> int | None:
    if n <= 0:
        return None
    if index == -1:
        return n - 1
    if index < 0:
        return 0
    if index >= n:
        return n - 1
    return index


def _center_for_backend_node(session: Any, backend_id: int) -> tuple[float, float]:
    """Get the on-screen center point for a backend DOM node id (best-effort)."""
    with contextlib.suppress(Exception):
        session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})

    try:
        box = session.send("DOM.getBoxModel", {"backendNodeId": backend_id})
    except Exception as exc:  # noqa: BLE001
        raise SmartToolError(
            tool="ax",
            action="backend_box",
            reason=str(exc),
            suggestion="The node may be detached; re-query via page(detail='ax')",
            details={"backendDOMNodeId": backend_id},
        ) from exc

    model = box.get("model") if isinstance(box, dict) else None
    quad = None
    if isinstance(model, dict):
        quad = model.get("border") or model.get("content") or model.get("padding")
    if not isinstance(quad, list) or len(quad) < 8:
        raise SmartToolError(
            tool="ax",
            action="backend_box",
            reason="Missing box model quad for backend node",
            suggestion="Re-query element handle and retry",
            details={"backendDOMNodeId": backend_id},
        )

    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
    x = sum(xs) / 4.0
    y = sum(ys) / 4.0
    return x, y


@with_retry(max_attempts=2, delay=0.2)
def query_ax(
    config: BrowserConfig,
    *,
    role: str | None = None,
    name: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """Query accessibility nodes by role/name (summary-first)."""
    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 50))

    if not (isinstance(role, str) and role.strip()) and not (isinstance(name, str) and name.strip()):
        raise SmartToolError(
            tool="page",
            action="ax",
            reason="Missing role/name query",
            suggestion="Use page(detail='ax', role='button', name='Save') or click(text='Save', role='button', strategy='ax')",
        )

    with get_session(config) as (session, target):
        query_role, role_filter = _normalize_role_query(role)
        nodes = _query_ax_tree(session, role=query_role, name=name)
        if nodes is None or not nodes:
            nodes = _get_ax_nodes(session)
        items = _search_ax_items(nodes, role=role, name=name, allowed_roles=role_filter)
        total = len(items)
        page_items = items[offset : offset + limit]

        return {
            "ax": {
                "query": {"role": role, "name": name},
                "total": total,
                "offset": offset,
                "limit": limit,
                "items": page_items,
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def click_accessibility(
    config: BrowserConfig,
    *,
    role: str | None,
    name: str | None,
    index: int = 0,
    button: str = "left",
    double: bool = False,
) -> dict[str, Any]:
    """Click by accessibility role+name using CDP AX tree + DOM.getBoxModel."""
    if button not in {"left", "right", "middle"}:
        raise SmartToolError(
            tool="click",
            action="validate",
            reason=f"Invalid mouse button: {button}",
            suggestion="Use one of: left, right, middle",
        )

    with get_session(config) as (session, target):
        query_role, role_filter = _normalize_role_query(role)
        nodes = _query_ax_tree(session, role=query_role, name=name)
        if nodes is None or not nodes:
            nodes = _get_ax_nodes(session)
        items = _search_ax_items(nodes, role=role, name=name, allowed_roles=role_filter)
        if not items:
            raise SmartToolError(
                tool="click",
                action="ax",
                reason="No matching accessibility node found",
                suggestion="Try a different name, omit role, or use click(text=...) / page(detail='locators')",
                details={"role": role, "name": name},
            )

        idx = _pick_index(len(items), int(index))
        if idx is None:
            raise SmartToolError(
                tool="click",
                action="ax",
                reason="No candidates after filtering",
                suggestion="Try broader role/name query",
            )

        chosen = items[idx] if isinstance(items[idx], dict) else {}
        backend_id = chosen.get("backendDOMNodeId")
        if not isinstance(backend_id, int) or backend_id <= 0:
            raise SmartToolError(
                tool="click",
                action="ax",
                reason="Matched node has no backendDOMNodeId (cannot be clicked)",
                suggestion="Try a different match or fall back to click(text=...)",
            )

        with contextlib.suppress(Exception):
            # Best-effort; getBoxModel/click might still succeed.
            session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})

        try:
            box = session.send("DOM.getBoxModel", {"backendNodeId": backend_id})
        except Exception as exc:  # noqa: BLE001
            raise SmartToolError(
                tool="click",
                action="ax_box",
                reason=str(exc),
                suggestion="Try click(text=...) or click(selector=...) as fallback",
                details={"backendDOMNodeId": backend_id},
            ) from exc

        model = box.get("model") if isinstance(box, dict) else None
        quad = None
        if isinstance(model, dict):
            quad = model.get("border") or model.get("content") or model.get("padding")
        if not isinstance(quad, list) or len(quad) < 8:
            raise SmartToolError(
                tool="click",
                action="ax_box",
                reason="Missing box model quad for matched node",
                suggestion="Try a different element or fall back to click(text=...) / click(selector=...)",
            )

        try:
            xs = [float(quad[i]) for i in (0, 2, 4, 6)]
            ys = [float(quad[i]) for i in (1, 3, 5, 7)]
        except Exception as exc:  # noqa: BLE001
            raise SmartToolError(
                tool="click",
                action="ax_box",
                reason=str(exc),
                suggestion="Try fallback click methods",
            ) from exc

        x = sum(xs) / 4.0
        y = sum(ys) / 4.0
        session.click(x, y, button=button, click_count=2 if double else 1)

        return {
            "result": {
                "strategy": "ax",
                "role": chosen.get("role"),
                "name": chosen.get("name"),
                "backendDOMNodeId": backend_id,
                "index": idx,
                "matchesFound": len(items),
                "clicked": {"x": x, "y": y, "button": button, "clickCount": 2 if double else 1},
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def click_backend_node(
    config: BrowserConfig,
    *,
    backend_dom_node_id: int,
    button: str = "left",
    double: bool = False,
) -> dict[str, Any]:
    """Click by backend DOM node id (stable handle for AX-based workflows)."""
    if button not in {"left", "right", "middle"}:
        raise SmartToolError(
            tool="click",
            action="validate",
            reason=f"Invalid mouse button: {button}",
            suggestion="Use one of: left, right, middle",
        )

    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="click",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )

    with get_session(config) as (session, target):
        x, y = _center_for_backend_node(session, backend_id)
        session.click(x, y, button=button, click_count=2 if double else 1)

        return {
            "result": {
                "strategy": "backendDOMNodeId",
                "backendDOMNodeId": backend_id,
                "clicked": {"x": x, "y": y, "button": button, "clickCount": 2 if double else 1},
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def type_backend_node(
    config: BrowserConfig,
    *,
    backend_dom_node_id: int,
    text: str,
    clear: bool = False,
    submit: bool = False,
) -> dict[str, Any]:
    """Focus an element by backend DOM node id and type text (no text echo in output)."""
    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="type",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )
    if text is None:
        raise SmartToolError(
            tool="type",
            action="validate",
            reason="Missing text",
            suggestion="Provide text='...'",
        )

    with get_session(config) as (session, target):
        with contextlib.suppress(Exception):
            session.enable_dom()

        try:
            session.send("DOM.focus", {"backendNodeId": backend_id})
        except Exception as exc:  # noqa: BLE001
            raise SmartToolError(
                tool="type",
                action="focus",
                reason=str(exc),
                suggestion="The node may be detached; re-query via page(detail='ax')",
                details={"backendDOMNodeId": backend_id},
            ) from exc

        if clear:
            # Best-effort clear of the focused element (cross-platform, works for contenteditable too).
            with contextlib.suppress(Exception):
                session.eval_js(
                    "(() => {"
                    "  const el = document.activeElement;"
                    "  if (!el) return false;"
                    "  try { if (el.isContentEditable) el.textContent = ''; else if ('value' in el) el.value = ''; } catch (e) {}"
                    "  try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}"
                    "  try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}"
                    "  return true;"
                    "})()"
                )

        session.type_text(str(text))
        if submit:
            session.press_key("Enter")

        return {
            "result": {
                "strategy": "backendDOMNodeId",
                "backendDOMNodeId": backend_id,
                "typed_len": len(str(text)),
                **({"cleared": True} if clear else {}),
                **({"submitted": True} if submit else {}),
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def hover_backend_node(
    config: BrowserConfig,
    *,
    backend_dom_node_id: int,
) -> dict[str, Any]:
    """Move mouse to a backend DOM node's center (stable handle hover)."""
    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="mouse",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )

    with get_session(config) as (session, target):
        x, y = _center_for_backend_node(session, backend_id)
        session.move_mouse(x, y)
        return {
            "result": {"strategy": "backendDOMNodeId", "backendDOMNodeId": backend_id, "hovered": {"x": x, "y": y}},
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def drag_backend_nodes(
    config: BrowserConfig,
    *,
    from_backend_dom_node_id: int,
    to_backend_dom_node_id: int,
    steps: int = 10,
) -> dict[str, Any]:
    """Drag from one backend DOM node center to another (stable handle drag)."""
    from_id = int(from_backend_dom_node_id)
    to_id = int(to_backend_dom_node_id)
    if from_id <= 0 or to_id <= 0:
        raise SmartToolError(
            tool="mouse",
            action="validate",
            reason="from_backend_dom_node_id and to_backend_dom_node_id must be positive integers",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId values",
            details={"from_backendDOMNodeId": from_id, "to_backendDOMNodeId": to_id},
        )

    steps = max(1, min(int(steps), 200))

    with get_session(config) as (session, target):
        from_x, from_y = _center_for_backend_node(session, from_id)
        to_x, to_y = _center_for_backend_node(session, to_id)
        session.drag(from_x, from_y, to_x, to_y, steps)
        return {
            "result": {
                "strategy": "backendDOMNodeId",
                "from_backendDOMNodeId": from_id,
                "to_backendDOMNodeId": to_id,
                "from": {"x": from_x, "y": from_y},
                "to": {"x": to_x, "y": to_y},
                "steps": steps,
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def scroll_backend_node(
    config: BrowserConfig,
    *,
    backend_dom_node_id: int,
) -> dict[str, Any]:
    """Scroll a backend DOM node into view (stable handle scroll)."""
    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="scroll",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )

    with get_session(config) as (session, target):
        try:
            session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})
        except Exception as exc:  # noqa: BLE001
            raise SmartToolError(
                tool="scroll",
                action="scrollIntoViewIfNeeded",
                reason=str(exc),
                suggestion="The node may be detached; re-query via page(detail='ax')",
                details={"backendDOMNodeId": backend_id},
            ) from exc

        return {
            "result": {"strategy": "backendDOMNodeId", "backendDOMNodeId": backend_id, "scrolled": True},
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def drag_backend_node_to_xy(
    config: BrowserConfig,
    *,
    backend_dom_node_id: int,
    to_x: float,
    to_y: float,
    steps: int = 10,
) -> dict[str, Any]:
    """Drag from a backend DOM node center to a target coordinate."""
    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="mouse",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )

    steps = max(1, min(int(steps), 200))

    with get_session(config) as (session, target):
        from_x, from_y = _center_for_backend_node(session, backend_id)
        session.drag(from_x, from_y, float(to_x), float(to_y), steps)
        return {
            "result": {
                "strategy": "backendDOMNodeId->coords",
                "backendDOMNodeId": backend_id,
                "from": {"x": from_x, "y": from_y},
                "to": {"x": float(to_x), "y": float(to_y)},
                "steps": steps,
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }


@with_retry(max_attempts=2, delay=0.2)
def drag_xy_to_backend_node(
    config: BrowserConfig,
    *,
    from_x: float,
    from_y: float,
    backend_dom_node_id: int,
    steps: int = 10,
) -> dict[str, Any]:
    """Drag from a coordinate to a backend DOM node center."""
    backend_id = int(backend_dom_node_id)
    if backend_id <= 0:
        raise SmartToolError(
            tool="mouse",
            action="validate",
            reason="backend_dom_node_id must be a positive integer",
            suggestion="Use page(detail='ax') to obtain backendDOMNodeId",
        )

    steps = max(1, min(int(steps), 200))

    with get_session(config) as (session, target):
        to_x, to_y = _center_for_backend_node(session, backend_id)
        session.drag(float(from_x), float(from_y), to_x, to_y, steps)
        return {
            "result": {
                "strategy": "coords->backendDOMNodeId",
                "backendDOMNodeId": backend_id,
                "from": {"x": float(from_x), "y": float(from_y)},
                "to": {"x": to_x, "y": to_y},
                "steps": steps,
            },
            "target": target["id"],
            "sessionTabId": session_manager.tab_id,
        }
