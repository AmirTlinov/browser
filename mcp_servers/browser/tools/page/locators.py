"""Stable locator suggestions for interactive elements on the current page."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def _stable_aff_ref(*, tool: str, args: dict[str, Any], meta: dict[str, Any]) -> str:
    """Compute a stable affordance ref for `act(ref=...)` workflows.

    Goals:
    - Deterministic across runs.
    - Resistant to item reordering (SPA churn) when semantics are the same.
    - Small enough to copy/paste.
    """
    sig = {"v": 1, "tool": tool, "args": args, "meta": meta}
    blob = json.dumps(sig, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]
    return f"aff:{digest}"


def _ax_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


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


def _tier0_locators_from_ax(*, session: Any, kind: str, offset: int, limit: int) -> dict[str, Any]:
    """Tier-0 locators from CDP Accessibility tree (no page injection)."""
    try:
        res = session.send("Accessibility.getFullAXTree")
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "tier": "tier0",
            "reason": "ax_unavailable",
            "error": str(exc),
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
        }

    nodes = res.get("nodes") if isinstance(res, dict) else None
    if not isinstance(nodes, list):
        return {
            "available": False,
            "tier": "tier0",
            "reason": "ax_unavailable",
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
        }

    kind_norm = str(kind or "all").strip().lower()
    if kind_norm not in {"all", "button", "link", "input"}:
        kind_norm = "all"

    interactive_roles = {
        "button": ("button", None),
        "link": ("link", None),
        "checkbox": ("input", "checkbox"),
        "radio": ("input", "radio"),
        "switch": ("input", "switch"),
        "textbox": ("input", "text"),
        "textfield": ("input", "text"),
        "text": ("input", "text"),
        "textarea": ("input", "text"),
        "searchbox": ("input", "search"),
        "searchfield": ("input", "search"),
        "combobox": ("input", "combobox"),
        "listbox": ("input", "listbox"),
        "menuitem": ("button", None),
        "tab": ("button", None),
    }

    items_all: list[dict[str, Any]] = []
    scanned = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        scanned += 1
        if scanned > 5000:
            break
        if n.get("ignored") is True:
            continue

        role = str(_ax_value(n.get("role")) or "").strip()
        if not role:
            continue
        role_norm = role.lower()
        mapped = interactive_roles.get(role_norm)

        focusable = _ax_bool_prop(n, "focusable")
        disabled = _ax_bool_prop(n, "disabled")
        editable = _ax_bool_prop(n, "editable")

        if mapped is None:
            if focusable is not True:
                continue
            if editable is True:
                kind_name = "input"
                input_type = "text"
            else:
                kind_name = "button"
                input_type = None
        else:
            kind_name, input_type = mapped

        if kind_norm != "all" and kind_name != kind_norm:
            continue

        backend_id = n.get("backendDOMNodeId") or n.get("backendDomNodeId") or 0
        backend_dom_node_id: int | None = None
        if isinstance(backend_id, (int, float)):
            backend_dom_node_id = int(backend_id)
        if not isinstance(backend_dom_node_id, int) or backend_dom_node_id <= 0:
            continue

        name = str(_ax_value(n.get("name")) or "").strip()

        it: dict[str, Any] = {
            "kind": kind_name,
            "role": role,
            "name": name,
            "backendDOMNodeId": backend_dom_node_id,
            "domRef": f"dom:{backend_dom_node_id}",
            "index": len(items_all),
            **({"text": name} if kind_name in {"button", "link"} and name else {}),
            **({"inputType": input_type} if kind_name == "input" and input_type else {}),
            **({"focusable": True} if focusable is True else {}),
            **({"disabled": True} if disabled is True else {}),
        }
        items_all.append(it)

    def _score(item: dict[str, Any]) -> tuple[int, int, int]:
        return (
            1 if item.get("disabled") is not True else 0,
            1 if item.get("focusable") is True else 0,
            1 if isinstance(item.get("name"), str) and item.get("name") else 0,
        )

    items_all.sort(key=_score, reverse=True)
    total = len(items_all)
    page_items = items_all[offset : offset + limit] if limit else items_all[offset:]

    return {
        "available": True,
        "tier": "tier0",
        "kind": kind_norm,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": page_items,
        "note": "Tier-0 locators from CDP Accessibility tree (no page injection)",
    }


def get_page_locators(
    config: BrowserConfig,
    *,
    kind: str = "all",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return stable selector suggestions.

    Args:
        config: Browser configuration
        kind: all|button|link|input
        offset: Pagination offset
        limit: Pagination limit (clamped to [0..200])
    """

    kind = str(kind or "all")
    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 200))

    # Do not force diagnostics injection at session-creation time:
    # dialogs can block Runtime.evaluate and cause tool timeouts.
    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            tier0 = session_manager.ensure_telemetry(session)

            # If a JS dialog is open, avoid Runtime.evaluate-based locators (can hang).
            try:
                tab_id = session.tab_id
                t0 = session_manager.tier0_snapshot(
                    tab_id,
                    since=max(0, int(time.time() * 1000) - 30_000),
                    offset=0,
                    limit=3,
                )
                if isinstance(t0, dict) and t0.get("dialogOpen") is True:
                    return {
                        "locators": {
                            "available": True,
                            "tier": "tier0",
                            "reason": "dialog_open",
                            "items": [],
                            "dialog": t0.get("dialog") if isinstance(t0.get("dialog"), dict) else None,
                        },
                        "tier0": tier0,
                        "target": target["id"],
                        "sessionTabId": session_manager.tab_id,
                    }
            except Exception:
                pass

            install = session_manager.ensure_diagnostics(session)

            js = (
                "(() => {"
                "  const d = globalThis.__mcpDiag;"
                "  if (!d || typeof d.locators !== 'function') return null;"
                f"  return d.locators({json.dumps({'kind': kind, 'offset': offset, 'limit': limit})});"
                "})()"
            )
            locs = None
            try:
                locs = session.eval_js(js)
            except Exception:
                locs = None
            if not locs:
                # Tier-1 injection unavailable (CSP/hardened pages): return Tier-0 AX locators.
                locs = _tier0_locators_from_ax(session=session, kind=kind, offset=offset, limit=limit)

            # v2-safe refs + action hints (cognitive-cheap for agents):
            # - Generate stable `aff:<hash>` refs for items and store them in SessionManager.
            # - In v2 toolset, prefer `act(ref=...)` instead of top-level click/type/form calls.
            toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
            is_v2 = toolset in {"v2", "northstar", "north-star"}

            ref_specs: list[dict[str, Any]] = []
            try:
                items = locs.get("items") if isinstance(locs, dict) else None
            except Exception:
                items = None

            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue

                    kind_name = it.get("kind") if isinstance(it.get("kind"), str) else ""
                    selector = it.get("selector") if isinstance(it.get("selector"), str) else ""
                    text = it.get("text") if isinstance(it.get("text"), str) else ""
                    index = it.get("index") if isinstance(it.get("index"), int) else 0
                    input_type = it.get("inputType") if isinstance(it.get("inputType"), str) else ""
                    dom_ref = it.get("domRef") if isinstance(it.get("domRef"), str) else ""
                    backend_dom_node_id = (
                        it.get("backendDOMNodeId") if isinstance(it.get("backendDOMNodeId"), int) else None
                    )

                    tool: str | None = None
                    args: dict[str, Any] | None = None

                    if dom_ref:
                        tool = "click"
                        args = {"ref": dom_ref}
                    elif backend_dom_node_id is not None and backend_dom_node_id > 0:
                        tool = "click"
                        args = {"backendDOMNodeId": backend_dom_node_id}
                    elif kind_name in {"button", "link"} and text:
                        tool = "click"
                        args = {"text": text, "role": kind_name, "index": index}
                    elif kind_name == "input" and selector:
                        fill_key = it.get("fillKey") if isinstance(it.get("fillKey"), str) else ""
                        form_index = it.get("formIndex") if isinstance(it.get("formIndex"), int) else None

                        if fill_key:
                            # Prefer semantic focus for inputs: works across open shadow DOM + same-origin iframes.
                            tool = "form"
                            args = {
                                "focus_key": fill_key,
                                **({"form_index": form_index} if isinstance(form_index, int) else {}),
                            }
                        elif str(input_type).lower() in {"checkbox", "radio"}:
                            tool = "click"
                            args = {"selector": selector}
                        else:
                            tool = "form"
                            args = {"focus": selector}
                    elif selector:
                        tool = "click"
                        args = {"selector": selector}

                    if tool and isinstance(args, dict):
                        meta = {
                            "kind": kind_name,
                            **({"role": it.get("role")} if isinstance(it.get("role"), str) and it.get("role") else {}),
                            **({"name": it.get("name")} if isinstance(it.get("name"), str) and it.get("name") else {}),
                            **({"text": text} if text else {}),
                            **({"selector": selector} if selector else {}),
                            **({"domRef": dom_ref} if dom_ref else {}),
                            **({"href": it.get("href")} if isinstance(it.get("href"), str) and it.get("href") else {}),
                            **(
                                {"fillKey": it.get("fillKey")}
                                if isinstance(it.get("fillKey"), str) and it.get("fillKey")
                                else {}
                            ),
                            **({"inputType": input_type} if input_type else {}),
                            **({"formIndex": it.get("formIndex")} if isinstance(it.get("formIndex"), int) else {}),
                            **({"inShadowDOM": True} if it.get("inShadowDOM") is True else {}),
                            **(
                                {"backendDOMNodeId": backend_dom_node_id}
                                if isinstance(backend_dom_node_id, int)
                                else {}
                            ),
                        }
                        ref = _stable_aff_ref(tool=tool, args=args, meta=meta)
                        it["ref"] = ref
                        # For v2: avoid suggesting direct top-level tools; prefer the ref path.
                        if is_v2:
                            it["actionHint"] = f'act(ref="{ref}")'
                        ref_specs.append(
                            {
                                "ref": ref,
                                "tool": tool,
                                "args": args,
                                "meta": meta,
                            }
                        )

            # Store affordances for act(ref) resolution (best-effort).
            try:
                tab_id = session.tab_id
                if isinstance(tab_id, str) and tab_id and ref_specs:
                    url = None
                    try:
                        nav = session.send("Page.getNavigationHistory")
                        if isinstance(nav, dict):
                            idx = nav.get("currentIndex")
                            entries = nav.get("entries")
                            if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                                cur = entries[idx] if isinstance(entries[idx], dict) else None
                                if isinstance(cur, dict) and isinstance(cur.get("url"), str):
                                    url = cur.get("url")
                    except Exception:
                        url = None
                    if not url:
                        try:
                            url = session.eval_js("window.location.href")
                        except Exception:
                            url = None
                    session_manager.set_affordances(
                        tab_id,
                        items=ref_specs,
                        url=url if isinstance(url, str) else None,
                        cursor=None,
                    )
                    if isinstance(locs, dict) and ref_specs:
                        locs["usage"] = (
                            f'run(actions=[{{act:{{ref:"{ref_specs[0]["ref"]}"}}}}])  # uses locators.items[*].ref'
                        )
            except Exception:
                pass

            return {
                "locators": locs,
                "installed": install,
                "tier0": tier0,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except SmartToolError:
            raise
        except Exception as exc:
            raise SmartToolError(
                tool="page",
                action="locators",
                reason=str(exc),
                suggestion="Ensure the page is loaded and responsive",
            ) from exc
