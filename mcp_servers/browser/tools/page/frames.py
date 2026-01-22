"""Frames/iframes map for the current page (AI-native, bounded).

Goal:
- Give agents a reliable mental model of frame complexity (including cross-origin frames).
- Provide a visual overlay path for "where is that iframe / captcha / SSO box?" debugging.

Design:
- Prefer CDP Page.getFrameTree (works even when in-page JS is blocked).
- Optionally compute viewport bounds for frame owners via DOM.getFrameOwner + DOM.getBoxModel
  (best-effort, bounded scan).
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from ...config import BrowserConfig
from ...server.redaction import redact_url
from ...session import session_manager
from ..base import SmartToolError, get_session


def get_page_frames(
    config: BrowserConfig,
    *,
    offset: int = 0,
    limit: int = 50,
    include_bounds: bool = False,
    overlay_limit: int = 15,
) -> dict[str, Any]:
    """Return a compact frame tree map.

    Args:
        config: Browser configuration
        offset: Pagination offset for the flattened frame list
        limit: Pagination limit for the flattened frame list (clamped to [0..200])
        include_bounds: If true, compute viewport bounds for some frame owners (best-effort)
        overlay_limit: Max number of visible frame boxes to include when include_bounds=True
    """

    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 200))
    overlay_limit = max(0, min(int(overlay_limit), 30))

    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            tier0 = session_manager.ensure_telemetry(session)

            # CDP-only: should work even when Runtime.evaluate is blocked/hardened.
            with suppress(Exception):
                session.enable_page()
            with suppress(Exception):
                session.enable_dom()

            tree = session.send("Page.getFrameTree")
            frame_tree = tree.get("frameTree") if isinstance(tree, dict) else None
            if not isinstance(frame_tree, dict):
                raise SmartToolError(
                    tool="page",
                    action="frames",
                    reason="Page.getFrameTree returned no frameTree",
                    suggestion="Navigate to a regular http(s) page and retry",
                )

            flat: list[dict[str, Any]] = []
            root_origin: str | None = None

            def _walk(node: dict[str, Any], *, parent_id: str | None, depth: int) -> None:
                nonlocal root_origin
                frame = node.get("frame") if isinstance(node.get("frame"), dict) else None
                children = node.get("childFrames") if isinstance(node.get("childFrames"), list) else []

                frame_id = frame.get("id") if isinstance(frame, dict) else None
                url = frame.get("url") if isinstance(frame, dict) else None
                origin = frame.get("securityOrigin") if isinstance(frame, dict) else None
                name = frame.get("name") if isinstance(frame, dict) else None
                unreachable = frame.get("unreachableUrl") if isinstance(frame, dict) else None
                mime = frame.get("mimeType") if isinstance(frame, dict) else None

                if depth == 0 and isinstance(origin, str) and origin:
                    root_origin = origin

                item: dict[str, Any] = {
                    **({"frameId": frame_id} if isinstance(frame_id, str) and frame_id else {}),
                    **({"parentFrameId": parent_id} if isinstance(parent_id, str) and parent_id else {}),
                    "depth": int(depth),
                    **({"url": redact_url(url)} if isinstance(url, str) and url else {}),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                    **({"name": name} if isinstance(name, str) and name else {}),
                    **({"mimeType": mime} if isinstance(mime, str) and mime else {}),
                    **(
                        {"unreachableUrl": redact_url(unreachable)}
                        if isinstance(unreachable, str) and unreachable
                        else {}
                    ),
                }

                # Cross-origin heuristic: compare securityOrigin to the main frame.
                # Note: "null" origins happen with sandboxed frames; treat as cross-origin.
                if depth > 0:
                    if (
                        isinstance(origin, str)
                        and origin
                        and origin != "null"
                        and isinstance(root_origin, str)
                        and root_origin
                    ):
                        if origin != root_origin:
                            item["crossOrigin"] = True
                    elif origin == "null":
                        item["crossOrigin"] = True

                flat.append(item)

                for child in children:
                    if not isinstance(child, dict):
                        continue
                    child_frame = child.get("frame") if isinstance(child.get("frame"), dict) else None
                    child_frame.get("id") if isinstance(child_frame, dict) else None
                    _walk(child, parent_id=frame_id if isinstance(frame_id, str) else parent_id, depth=depth + 1)

            _walk(frame_tree, parent_id=None, depth=0)

            total = len(flat)
            cross_origin = len([f for f in flat if isinstance(f, dict) and f.get("crossOrigin") is True])

            paged = flat[offset : offset + limit] if limit else []

            payload: dict[str, Any] = {
                "frames": {
                    "summary": {
                        "total": total,
                        "crossOrigin": cross_origin,
                        "sameOrigin": max(0, total - cross_origin),
                    },
                    **({"offset": offset} if offset else {}),
                    **({"limit": limit} if limit else {}),
                    "items": paged,
                    "note": "Same-origin iframes are already included in locators/click search; cross-origin frames require CDP/coordinate-based interactions.",
                    "next": [
                        "page(detail='frames', with_screenshot=true) to see visible iframe boxes",
                        "page(detail='locators') to find interactive elements (includes same-origin iframes + open shadow DOM)",
                        'run(actions=[{captcha:{action:"analyze"}}]) if this is a CAPTCHA flow',
                    ],
                },
                "tier0": tier0,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

            if include_bounds and overlay_limit > 0:
                overlay = _build_visible_frame_overlay(session, flat, max_items=overlay_limit)
                if overlay:
                    payload["frames"]["overlay"] = overlay.get("overlay")
                    payload["frames"]["overlayBoxes"] = overlay.get("boxes")

            return payload
        except SmartToolError:
            raise
        except Exception as exc:
            raise SmartToolError(
                tool="page",
                action="frames",
                reason=str(exc),
                suggestion="Ensure the page is loaded and responsive",
            ) from exc


def _build_visible_frame_overlay(session: Any, flat: list[dict[str, Any]], *, max_items: int) -> dict[str, Any] | None:
    """Best-effort: compute viewport boxes for some frame owners and return a small overlay pack."""

    # Viewport (best-effort).
    vw: float | None = None
    vh: float | None = None
    with suppress(Exception):
        metrics = session.send("Page.getLayoutMetrics")
        if isinstance(metrics, dict):
            vv = metrics.get("visualViewport") if isinstance(metrics.get("visualViewport"), dict) else None
            if isinstance(vv, dict):
                try:
                    vw = float(vv.get("clientWidth"))
                    vh = float(vv.get("clientHeight"))
                except Exception:
                    vw = None
                    vh = None

    def _overlaps_viewport(b: dict[str, Any]) -> bool:
        try:
            x = float(b.get("x", 0))
            y = float(b.get("y", 0))
            w = float(b.get("width", 0))
            h = float(b.get("height", 0))
        except Exception:
            return False
        if w < 2 or h < 2:
            return False
        if vw is None or vh is None:
            return True
        return (x + w) > 0 and (y + h) > 0 and x < vw and y < vh

    def _frame_owner_bounds(frame_id: str) -> dict[str, Any] | None:
        if not frame_id:
            return None
        owner = session.send("DOM.getFrameOwner", {"frameId": frame_id})
        if not isinstance(owner, dict):
            return None
        backend = owner.get("backendNodeId") or owner.get("backendDOMNodeId")
        if not isinstance(backend, int) or backend <= 0:
            return None
        box = session.send("DOM.getBoxModel", {"backendNodeId": backend})
        model = box.get("model") if isinstance(box, dict) else None
        if not isinstance(model, dict):
            return None
        quad = model.get("border") or model.get("content") or model.get("padding")
        if not isinstance(quad, list) or len(quad) < 8:
            return None
        xs = [float(quad[i]) for i in (0, 2, 4, 6)]
        ys = [float(quad[i]) for i in (1, 3, 5, 7)]
        x = min(xs)
        y = min(ys)
        w = max(xs) - x
        h = max(ys) - y
        if w < 2 or h < 2:
            return None
        return {"x": x, "y": y, "width": w, "height": h}

    # Scan bounded number of frames to avoid heavy work on ad-heavy pages.
    scan_limit = min(80, max(10, max_items * 5))
    visible: list[dict[str, Any]] = []
    scanned = 0

    for it in flat:
        if scanned >= scan_limit:
            break
        if not isinstance(it, dict):
            continue
        frame_id = it.get("frameId")
        if not isinstance(frame_id, str) or not frame_id:
            continue
        # Skip main frame (owner is not an iframe).
        if int(it.get("depth") or 0) <= 0:
            continue

        scanned += 1
        try:
            bounds = _frame_owner_bounds(frame_id)
        except Exception:
            bounds = None
        if not isinstance(bounds, dict):
            continue
        if not _overlaps_viewport(bounds):
            continue

        area = float(bounds["width"]) * float(bounds["height"])
        visible.append(
            {
                "frameId": frame_id,
                **({"url": it.get("url")} if isinstance(it.get("url"), str) else {}),
                **({"origin": it.get("origin")} if isinstance(it.get("origin"), str) else {}),
                **({"crossOrigin": True} if it.get("crossOrigin") is True else {}),
                "bounds": bounds,
                "area": area,
            }
        )

    # Prefer larger frames first (usually the actual app iframe vs tiny trackers).
    visible.sort(key=lambda x: float(x.get("area") or 0), reverse=True)
    visible = visible[:max_items]

    overlay_items: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    for idx, v in enumerate(visible, start=1):
        b = v.get("bounds") if isinstance(v.get("bounds"), dict) else None
        if not isinstance(b, dict):
            continue
        try:
            cx = float(b.get("x", 0)) + float(b.get("width", 0)) / 2.0
            cy = float(b.get("y", 0)) + float(b.get("height", 0)) / 2.0
        except Exception:
            cx = 0.0
            cy = 0.0
        overlay_items.append(
            {
                "n": idx,
                "frameId": v.get("frameId"),
                **({"url": v.get("url")} if isinstance(v.get("url"), str) else {}),
                **({"origin": v.get("origin")} if isinstance(v.get("origin"), str) else {}),
                **({"crossOrigin": True} if v.get("crossOrigin") is True else {}),
                "center": {"x": cx, "y": cy},
                "bounds": b,
                "actionHint": f"click(x={cx:.1f}, y={cy:.1f})  # focus/click inside iframe {idx}",
            }
        )
        boxes.append({"n": idx, "x": b.get("x"), "y": b.get("y"), "width": b.get("width"), "height": b.get("height")})

    if not overlay_items:
        return None

    return {
        "overlay": {
            "enabled": True,
            "count": len(overlay_items),
            "scanned": scanned,
            "items": overlay_items,
            "note": "Overlay shows visible iframe boxes. Use actionHint click(x,y) to focus/click inside a specific iframe.",
        },
        "boxes": boxes,
        "generatedAt": int(time.time() * 1000),
    }
