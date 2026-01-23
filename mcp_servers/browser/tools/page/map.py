"""Capability map for the current page (actions-first, bounded).

Goal
- Reduce agent round-trips by returning a compact "what can I do next" map.

Design
- One call should be enough to:
  - understand page health (errors/network/dialog)
  - get stable action refs (aff:...) for click/focus via run(actions=[{act:{ref:"..."}}])
  - see the main interactive affordances (buttons/links/inputs)
- Best-effort + bounded: partial results are better than failing.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from ...config import BrowserConfig
from ...server.redaction import redact_url
from ...session import session_manager
from ..base import SmartToolError
from .diagnostics import get_page_diagnostics
from .frames import get_page_frames
from .info import get_page_info
from .locators import get_page_locators


@contextmanager
def _maybe_shared_session(config: BrowserConfig) -> Any:  # noqa: ANN401
    """Best-effort shared session wrapper.

    Capability maps are often called in tight loops. Sharing the CDP connection
    reduces latency but must remain fail-soft for unit tests.
    """

    try:
        with session_manager.shared_session(config):
            yield
    except Exception:
        yield


def _label_for_locator(it: dict[str, Any]) -> str:
    for k in ("text", "label", "fillKey", "name", "id", "placeholder"):
        v = it.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _summary_from_snapshot(snapshot: dict[str, Any] | None, *, since: int | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}

    # Delta mode: derive counts from returned arrays (the JS snapshot filters by since).
    if since is not None:
        console_entries = snapshot.get("console") if isinstance(snapshot.get("console"), list) else []
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), list) else []
        network = snapshot.get("network") if isinstance(snapshot.get("network"), list) else []
        rejections = (
            snapshot.get("unhandledRejections") if isinstance(snapshot.get("unhandledRejections"), list) else []
        )

        return {
            "consoleErrors": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "error"]),
            "consoleWarnings": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "warn"]),
            "jsErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "error"]),
            "resourceErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "resource"]),
            "unhandledRejections": len(rejections),
            "failedRequests": len(network),
            **({"dialogOpen": True} if snapshot.get("dialogOpen") is True else {}),
        }

    # Full mode: prefer Tier-1 summary when present.
    summary = snapshot.get("summary")
    return summary if isinstance(summary, dict) else {}


def _compact_actions(loc_payload: dict[str, Any] | None, *, limit: int) -> dict[str, Any] | None:
    locs = loc_payload.get("locators") if isinstance(loc_payload, dict) else None
    if not isinstance(locs, dict):
        return None

    items = locs.get("items") if isinstance(locs.get("items"), list) else []

    compact: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}
    link_edges: list[dict[str, Any]] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip().lower()
        if not kind:
            continue

        kind_counts[kind] = kind_counts.get(kind, 0) + 1

        ref = it.get("ref") if isinstance(it.get("ref"), str) else None
        label = _label_for_locator(it)

        entry: dict[str, Any] = {
            "kind": kind,
            **({"label": label} if label else {}),
            **({"ref": ref} if isinstance(ref, str) and ref else {}),
            **({"inShadowDOM": True} if it.get("inShadowDOM") is True else {}),
            **({"disabled": True} if it.get("disabled") is True else {}),
        }

        # Canonical action hint: act(ref=...) is the shortest stable path.
        if isinstance(ref, str) and ref.startswith("aff:"):
            entry["actionHint"] = f'act(ref="{ref}")'
        elif isinstance(it.get("actionHint"), str) and it.get("actionHint"):
            entry["actionHint"] = it.get("actionHint")

        # Optional link target (redacted for safety).
        href = it.get("href")
        if kind == "link" and isinstance(href, str) and href.strip():
            entry["href"] = redact_url(href)
            if isinstance(ref, str) and ref.startswith("aff:"):
                link_edges.append({"ref": ref, "label": label, "to": redact_url(href)})

        # Optional input hints.
        if kind == "input":
            fill_key = it.get("fillKey")
            if isinstance(fill_key, str) and fill_key.strip():
                entry["fillKey"] = fill_key.strip()
            input_type = it.get("inputType")
            if isinstance(input_type, str) and input_type.strip():
                entry["inputType"] = input_type.strip()
            if isinstance(it.get("formIndex"), int):
                entry["formIndex"] = it.get("formIndex")

        if entry:
            compact.append(entry)
        if len(compact) >= limit:
            break

    return {
        "tier": locs.get("tier") or "tier1",
        **({"total": locs.get("total")} if isinstance(locs.get("total"), int) else {}),
        "byKind": kind_counts,
        "items": compact,
        **({"linkEdges": link_edges} if link_edges else {}),
    }


def get_page_map(
    config: BrowserConfig,
    *,
    since: int | None = None,
    limit: int = 30,
    clear: bool = False,
) -> dict[str, Any]:
    """Return a bounded capability map for agents (actions + health + next hints)."""

    started = time.time()
    limit = max(0, min(int(limit), 60))

    with _maybe_shared_session(config):
        info = None
        try:
            info = get_page_info(config)
        except Exception:
            info = None

        diagnostics = None
        try:
            diag_kwargs: dict[str, Any] = {"limit": max(10, min(limit, 50)), "clear": bool(clear)}
            if since is not None:
                diag_kwargs["since"] = since
            diagnostics = get_page_diagnostics(config, **diag_kwargs)
        except Exception:
            diagnostics = None

        frames = None
        try:
            # Summary-only (limit=0): still computes the tree counts.
            frames = get_page_frames(config, offset=0, limit=0, include_bounds=False)
        except Exception:
            frames = None

        locators = None
        try:
            locators = get_page_locators(config, kind="all", offset=0, limit=max(15, limit))
        except Exception:
            locators = None

    page_info = info.get("pageInfo") if isinstance(info, dict) else None
    diag_snapshot = diagnostics.get("diagnostics") if isinstance(diagnostics, dict) else None
    insights = diagnostics.get("insights") if isinstance(diagnostics, dict) else None

    page: dict[str, Any] = {}
    if isinstance(page_info, dict):
        for k in ("url", "title", "readyState"):
            if k in page_info:
                v = page_info.get(k)
                if k == "url" and isinstance(v, str) and v:
                    page[k] = redact_url(v)
                else:
                    page[k] = v

    if not page and isinstance(diag_snapshot, dict):
        for k in ("url", "title", "readyState"):
            if k in diag_snapshot:
                v = diag_snapshot.get(k)
                if k == "url" and isinstance(v, str) and v:
                    page[k] = redact_url(v)
                else:
                    page[k] = v

    summary = _summary_from_snapshot(diag_snapshot if isinstance(diag_snapshot, dict) else None, since=since)

    top: list[dict[str, Any]] = []
    if isinstance(insights, list):
        top = [i for i in insights if isinstance(i, dict)][:5]

    actions = _compact_actions(locators, limit=limit)

    frames_summary = None
    try:
        frames_obj = frames.get("frames") if isinstance(frames, dict) else None
        if isinstance(frames_obj, dict) and isinstance(frames_obj.get("summary"), dict):
            frames_summary = frames_obj.get("summary")
    except Exception:
        frames_summary = None

    cursor = None
    if isinstance(diagnostics, dict) and diagnostics.get("cursor") is not None:
        cursor = diagnostics.get("cursor")
    elif isinstance(diag_snapshot, dict) and diag_snapshot.get("cursor") is not None:
        cursor = diag_snapshot.get("cursor")

    if not page and not summary and not actions:
        raise SmartToolError(
            tool="page",
            action="map",
            reason="Capability map not available (page snapshot unavailable)",
            suggestion="Navigate to a page first, then retry",
        )

    out: dict[str, Any] = {
        "map": {
            **({"page": page} if page else {}),
            **({"since": since} if since is not None else {}),
            **({"summary": summary} if summary else {}),
            **({"top": top} if top else {}),
            **({"frames": frames_summary} if isinstance(frames_summary, dict) and frames_summary else {}),
            **({"actions": actions} if isinstance(actions, dict) else {}),
            "next": [
                'run(actions=[{page:{detail:"map"}}])  # refresh map in one call',
                "page(detail='locators', with_screenshot=true) for visual disambiguation",
                "page(detail='frames') if UI is iframe-heavy",
                "page(detail='graph') to see visited-page graph",
                "page(detail='diagnostics') for full JS/network snapshot",
            ],
        },
        "cursor": cursor,
        "duration_ms": int((time.time() - started) * 1000),
        "target": (diagnostics.get("target") if isinstance(diagnostics, dict) else None),
        "sessionTabId": (diagnostics.get("sessionTabId") if isinstance(diagnostics, dict) else session_manager.tab_id),
    }

    # If we have link edges, attach a minimal local navigation graph.
    try:
        edges = actions.get("linkEdges") if isinstance(actions, dict) else None
        if isinstance(edges, list) and edges:
            out["map"]["graph"] = {
                "node": {"url": page.get("url")} if isinstance(page.get("url"), str) else {},
                "edges": edges[: min(20, len(edges))],
                "note": "Graph is local: edges represent visible link actions (to=href when available).",
            }
    except Exception:
        pass

    # Persist a bounded navigation graph across calls (best-effort).
    try:
        tab_id = out.get("sessionTabId") if isinstance(out.get("sessionTabId"), str) else session_manager.tab_id
        url = page.get("url")
        if isinstance(tab_id, str) and tab_id and isinstance(url, str) and url:
            link_edges = actions.get("linkEdges") if isinstance(actions, dict) else None
            summary = session_manager.note_nav_graph_observation(
                tab_id,
                url=url,
                title=page.get("title") if isinstance(page.get("title"), str) else None,
                link_edges=link_edges if isinstance(link_edges, list) else None,
            )
            if isinstance(summary, dict):
                out["map"]["history"] = summary
    except Exception:
        pass

    return out
