"""Triage: minimal high-signal frontend issue summary for the current page."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from .diagnostics import get_page_diagnostics
from .locators import get_page_locators


@contextmanager
def _maybe_shared_session(config: BrowserConfig) -> Any:  # noqa: ANN401
    """Best-effort shared session wrapper.

    Triage often runs in tight loops (proofs/deltas). Sharing the CDP connection
    reduces latency. Must be fail-soft for unit tests.
    """
    try:
        with session_manager.shared_session(config):
            yield
    except Exception:
        yield


def get_page_triage(
    config: BrowserConfig,
    *,
    since: int | None = None,
    limit: int = 30,
    clear: bool = False,
) -> dict[str, Any]:
    """Return a compact triage summary based on the diagnostics snapshot.

    This is intentionally summary-first: counts + top insights + next actions.
    """
    loc_payload: dict[str, Any] | None = None
    with _maybe_shared_session(config):
        diag = get_page_diagnostics(config, since=since, limit=max(0, min(int(limit), 100)), clear=clear)
        snapshot = diag.get("diagnostics") if isinstance(diag, dict) else None
        insights = diag.get("insights") if isinstance(diag, dict) else None
        if since is None:
            try:
                loc_payload = get_page_locators(config, kind="all", offset=0, limit=15)
            except Exception:
                loc_payload = None

    # Summary should match what the agent needs to decide next:
    # - default (since=None): total counts
    # - delta mode (since!=None): counts of *new* events only
    summary: dict[str, Any] = {}
    if isinstance(snapshot, dict) and since is not None:
        # Delta mode: derive from filtered arrays returned by the diagnostics script.
        console_entries = snapshot.get("console") if isinstance(snapshot.get("console"), list) else []
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), list) else []
        network = snapshot.get("network") if isinstance(snapshot.get("network"), list) else []
        rejections = (
            snapshot.get("unhandledRejections") if isinstance(snapshot.get("unhandledRejections"), list) else []
        )

        summary = {
            "consoleErrors": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "error"]),
            "consoleWarnings": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "warn"]),
            "jsErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "error"]),
            "resourceErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "resource"]),
            "unhandledRejections": len(rejections),
            "failedRequests": len(network),
        }
    elif isinstance(snapshot, dict) and isinstance(snapshot.get("summary"), dict):
        # Full mode: use script-provided summary (total buffer counts).
        summary = snapshot["summary"]
    elif isinstance(snapshot, dict):
        # Fallback: compute totals from arrays (best-effort).
        console_entries = snapshot.get("console") if isinstance(snapshot.get("console"), list) else []
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), list) else []
        network = snapshot.get("network") if isinstance(snapshot.get("network"), list) else []
        rejections = (
            snapshot.get("unhandledRejections") if isinstance(snapshot.get("unhandledRejections"), list) else []
        )

        summary = {
            "consoleErrors": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "error"]),
            "consoleWarnings": len([e for e in console_entries if isinstance(e, dict) and e.get("level") == "warn"]),
            "jsErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "error"]),
            "resourceErrors": len([e for e in errors if isinstance(e, dict) and e.get("type") == "resource"]),
            "unhandledRejections": len(rejections),
            "failedRequests": len(network),
        }

    top_insights: list[dict[str, Any]] = []
    if isinstance(insights, list):
        # Prefer errors, then warnings; keep it small.
        def rank(item: dict[str, Any]) -> tuple[int, int]:
            sev = str(item.get("severity") or "")
            sev_rank = 0 if sev == "error" else 1
            return (sev_rank, 0)

        filtered = [i for i in insights if isinstance(i, dict)]
        top_insights = sorted(filtered, key=rank)[:5]

    page_meta: dict[str, Any] = {}
    if isinstance(snapshot, dict):
        for key in ("url", "title", "readyState"):
            if key in snapshot:
                page_meta[key] = snapshot.get(key)

    # Affordances: small interactive map (best-effort, cheap).
    # Only include on full triage (since=None). Delta-mode triage is often called
    # from proofs and must stay extremely small.
    affordances: dict[str, Any] | None = None
    if since is None:
        toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
        is_v2 = toolset in {"v2", "northstar", "north-star"}
        try:
            if not isinstance(loc_payload, dict):
                raise RuntimeError("locators_unavailable")
            locs = loc_payload.get("locators") if isinstance(loc_payload, dict) else None
            items = locs.get("items") if isinstance(locs, dict) else None
            total = locs.get("total") if isinstance(locs, dict) else None

            compact_items: list[dict[str, Any]] = []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kind = it.get("kind")
                    action_hint = it.get("actionHint")
                    selector = it.get("selector")
                    ref = it.get("ref") if isinstance(it.get("ref"), str) else None

                    label = (
                        it.get("text")
                        if isinstance(it.get("text"), str) and it.get("text")
                        else it.get("label")
                        if isinstance(it.get("label"), str) and it.get("label")
                        else it.get("fillKey")
                        if isinstance(it.get("fillKey"), str) and it.get("fillKey")
                        else it.get("name")
                        if isinstance(it.get("name"), str) and it.get("name")
                        else it.get("id")
                        if isinstance(it.get("id"), str) and it.get("id")
                        else it.get("placeholder")
                        if isinstance(it.get("placeholder"), str) and it.get("placeholder")
                        else ""
                    )

                    compact: dict[str, Any] = {
                        **({"kind": kind} if isinstance(kind, str) and kind else {}),
                        **({"label": label} if isinstance(label, str) and label else {}),
                        **({"actionHint": action_hint} if isinstance(action_hint, str) and action_hint else {}),
                        **({"selector": selector} if isinstance(selector, str) and selector else {}),
                        **({"inShadowDOM": True} if it.get("inShadowDOM") is True else {}),
                    }

                    # Keep small but useful for form filling / disambiguation.
                    if isinstance(it.get("index"), int):
                        compact["index"] = it.get("index")
                    if isinstance(it.get("formIndex"), int):
                        compact["formIndex"] = it.get("formIndex")
                    if isinstance(it.get("inputType"), str) and it.get("inputType"):
                        compact["inputType"] = it.get("inputType")

                    # Prefer refs produced by page(detail="locators") (stable hashes) for act(ref) usage.
                    if isinstance(ref, str) and ref.startswith("aff:"):
                        compact["ref"] = ref
                        if is_v2:
                            compact["actionHint"] = f'act(ref="{ref}")'

                    if compact:
                        compact_items.append(compact)
                    if len(compact_items) >= 12:
                        break

            affordances = {
                "available": True,
                **({"total": total} if isinstance(total, int) else {}),
                "items": compact_items,
            }
            first_ref = next(
                (it.get("ref") for it in compact_items if isinstance(it, dict) and isinstance(it.get("ref"), str)),
                None,
            )
            if isinstance(first_ref, str) and first_ref.startswith("aff:"):
                affordances["usage"] = (
                    f'run(actions=[{{act:{{ref:"{first_ref}"}}}}])  # uses refs from triage.affordances.items[*].ref'
                )
        except Exception:
            affordances = {"available": False, "reason": "locators_unavailable"}

    return {
        "triage": {
            **page_meta,
            **({"since": since} if since is not None else {}),
            "summary": summary,
            "top": top_insights,
            **({"affordances": affordances} if isinstance(affordances, dict) else {}),
            "next": [
                "page(detail='locators') for interactive map",
                "page(detail='frames') for iframe/cross-origin map",
                "page(detail='diagnostics') for full snapshot",
                "page(detail='resources', sort='duration') for slow assets",
                "page(detail='performance') for vitals/long-tasks",
            ],
        },
        # Preserve original keys that are useful for correlation.
        "target": diag.get("target") if isinstance(diag, dict) else None,
        "sessionTabId": diag.get("sessionTabId") if isinstance(diag, dict) else None,
        "cursor": diag.get("cursor") if isinstance(diag, dict) else None,
    }
