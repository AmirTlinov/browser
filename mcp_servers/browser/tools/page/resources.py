"""Resource timing snapshot (waterfall-ish) for the current page."""

from __future__ import annotations

import json
import time
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def _tier0_resources_from_snapshot(
    snap: dict[str, Any] | None,
    *,
    offset: int,
    limit: int,
    sort: str,
    reason: str,
    since: int | None,
    dialog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    har = snap.get("harLite") if isinstance(snap, dict) and isinstance(snap.get("harLite"), list) else []
    items = [it for it in har if isinstance(it, dict)]

    sort = str(sort or "start")

    def key_start(it: dict[str, Any]) -> tuple[int, int]:
        st = it.get("startTs")
        ts = it.get("ts")
        try:
            st_i = int(st) if isinstance(st, (int, float)) else None
        except Exception:
            st_i = None
        try:
            ts_i = int(ts) if isinstance(ts, (int, float)) else 0
        except Exception:
            ts_i = 0
        return (st_i if st_i is not None else ts_i, ts_i)

    def key_duration(it: dict[str, Any]) -> int:
        d = it.get("durationMs")
        try:
            return int(d) if isinstance(d, (int, float)) else -1
        except Exception:
            return -1

    def key_size(it: dict[str, Any]) -> int:
        b = it.get("encodedDataLength")
        try:
            return int(b) if isinstance(b, (int, float)) else -1
        except Exception:
            return -1

    if sort == "duration":
        items.sort(key=key_duration, reverse=True)
    elif sort == "size":
        items.sort(key=key_size, reverse=True)
    else:
        items.sort(key=key_start)

    total = len(items)
    page_items = items[offset : offset + limit] if limit else items[offset:]

    failed = len([it for it in items if it.get("ok") is False])
    bytes_total = 0
    for it in items:
        b = it.get("encodedDataLength")
        if isinstance(b, (int, float)) and b >= 0:
            bytes_total += int(b)

    return {
        "available": True,
        "tier": "tier0",
        "reason": reason,
        "sort": sort,
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": {"failed": failed, "bytesApprox": bytes_total},
        "items": page_items,
        **({"since": since} if since is not None else {}),
        **({"dialog": dialog} if isinstance(dialog, dict) else {}),
        "note": "Tier-0 resources from CDP Network telemetry (HAR-lite; bounded)",
    }


def get_page_resources(
    config: BrowserConfig,
    *,
    since: int | None = None,
    offset: int = 0,
    limit: int = 50,
    sort: str = "start",
) -> dict[str, Any]:
    """Return a resource-timing snapshot.

    Tier-1 (ResourceTiming via injection) is best-effort. On hardened pages, degrade
    to Tier-0 HAR-lite (slow requests + failures) instead of hard failing.

    Args:
        config: Browser configuration
        offset: Pagination offset
        limit: Pagination limit (clamped to [0..200])
        sort: Sorting mode: start|duration|size
    """

    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 200))
    sort = str(sort or "start")

    # Do not force diagnostics injection at session-creation time:
    # dialogs can block Runtime.evaluate and cause tool timeouts.
    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            tier0 = session_manager.ensure_telemetry(session)

            # If a JS dialog is open, Runtime.evaluate will likely hang. Return Tier-0 only.
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
                        "resources": _tier0_resources_from_snapshot(
                            t0,
                            offset=offset,
                            limit=limit,
                            sort=sort,
                            reason="dialog_open",
                            since=None,
                            dialog=t0.get("dialog") if isinstance(t0.get("dialog"), dict) else None,
                        ),
                        "tier0": tier0,
                        "target": target["id"],
                        "sessionTabId": session_manager.tab_id,
                    }
            except Exception:
                pass

            install = session_manager.ensure_diagnostics(session)

            opts: dict[str, Any] = {"offset": offset, "limit": limit, "sort": sort}
            if since is not None:
                try:
                    opts["since"] = int(since)
                except Exception:
                    opts["since"] = since

            js = (
                "(() => {"
                "  const d = globalThis.__mcpDiag;"
                "  if (!d || typeof d.resources !== 'function') return null;"
                f"  return d.resources({json.dumps(opts)});"
                "})()"
            )
            res = session.eval_js(js)
            if not res:
                # Tier-1 unavailable (CSP/blocked). Provide Tier-0 HAR-lite instead.
                t0 = None
                try:
                    if session.tab_id:
                        t0 = session_manager.tier0_snapshot(session.tab_id, since=since, offset=0, limit=0)
                except Exception:
                    t0 = None
                return {
                    "resources": _tier0_resources_from_snapshot(
                        t0 if isinstance(t0, dict) else {},
                        offset=offset,
                        limit=limit,
                        sort=sort,
                        reason="tier1_unavailable",
                        since=since,
                    ),
                    "installed": install,
                    "tier0": tier0,
                    "target": target["id"],
                    "sessionTabId": session_manager.tab_id,
                }

            return {
                "resources": res,
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
                action="resources",
                reason=str(exc),
                suggestion="Ensure the page is loaded and responsive",
            ) from exc
