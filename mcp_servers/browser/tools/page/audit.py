"""Super-report: one-call frontend audit for the current page (cognitive-cheap)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError
from .diagnostics import get_page_diagnostics
from .info import get_page_info
from .locators import get_page_locators
from .performance import get_page_performance
from .resources import get_page_resources


@contextmanager
def _maybe_shared_session(config: BrowserConfig) -> Any:  # noqa: ANN401
    """Best-effort shared session wrapper.

    Holding a single CDP connection across sub-tool calls reduces latency and flake,
    but unit tests run without Chrome. Fail-soft by design.
    """
    try:
        with session_manager.shared_session(config):
            yield
    except Exception:
        yield


def _compact_perf(perf_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    perf = perf_payload.get("performance") if isinstance(perf_payload, dict) else None
    if not isinstance(perf, dict):
        return None

    out: dict[str, Any] = {"tier": perf.get("tier") or "tier1"}

    # Prefer vitals (tier1), otherwise include tier0Perf.
    vitals = perf.get("vitals")
    if isinstance(vitals, dict) and vitals:
        keep = {}
        for k in ("lcp", "cls", "fid", "inp", "ttfb"):
            if k in vitals:
                keep[k] = vitals.get(k)
        if keep:
            out["vitals"] = keep

    timing = perf.get("timing")
    if isinstance(timing, dict) and timing:
        keep_t = {}
        for k in ("ttfb_ms", "domContentLoaded_ms", "load_ms"):
            if k in timing:
                keep_t[k] = timing.get(k)
        if keep_t:
            out["timing"] = keep_t

    tier0_perf = perf.get("tier0Perf") if isinstance(perf.get("tier0Perf"), dict) else perf_payload.get("tier0Perf")
    if isinstance(tier0_perf, dict) and tier0_perf:
        out.setdefault("tier0Perf", {})
        for k in ("timing", "longTasks"):
            v = tier0_perf.get(k)
            if isinstance(v, dict) and v:
                out["tier0Perf"][k] = v

    reason = perf.get("reason")
    if isinstance(reason, str) and reason:
        out["reason"] = reason

    return out


def _compact_network(diag_snapshot: dict[str, Any] | None, *, max_items: int = 6) -> dict[str, Any] | None:
    """Compact Tier-0/Tier-1 network signal into a bounded summary."""
    if not isinstance(diag_snapshot, dict):
        return None

    har = diag_snapshot.get("harLite") if isinstance(diag_snapshot.get("harLite"), list) else []
    net = diag_snapshot.get("network") if isinstance(diag_snapshot.get("network"), list) else []

    if not har and not net:
        return None

    items = [it for it in har if isinstance(it, dict)]
    total = len(items)

    ok = 0
    status_4xx = 0
    status_5xx = 0
    auth_401 = 0
    auth_403 = 0

    failures: list[dict[str, Any]] = []
    slow_api: list[dict[str, Any]] = []

    for it in items:
        st = it.get("status")
        try:
            st_i = int(st) if st is not None else None
        except Exception:
            st_i = None

        ok_flag = it.get("ok") is True
        if ok_flag:
            ok += 1

        if isinstance(st_i, int) and st_i >= 400:
            if st_i >= 500:
                status_5xx += 1
            else:
                status_4xx += 1
            if st_i == 401:
                auth_401 += 1
            elif st_i == 403:
                auth_403 += 1

        # Compact failures (status>=400 or ok=false or loadingFailed)
        if (isinstance(st_i, int) and st_i >= 400) or (it.get("ok") is False) or it.get("errorText"):
            failures.append(it)

        # Slow API calls (XHR/Fetch) are the most common debugging target.
        rtype = it.get("type")
        if isinstance(rtype, str) and rtype in {"XHR", "Fetch"}:
            dur = it.get("durationMs")
            if isinstance(dur, (int, float)):
                slow_api.append(it)

    failures.sort(
        key=lambda it: (
            0 if isinstance(it.get("status"), int) and int(it["status"]) >= 500 else 1,
            -(float(it.get("durationMs") or 0.0)),
        )
    )
    slow_api.sort(key=lambda it: -(float(it.get("durationMs") or 0.0)))

    def _take(src: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in src[: max(0, int(max_items))]:
            entry: dict[str, Any] = {}
            for k in (
                "url",
                "method",
                "status",
                "type",
                "ok",
                "durationMs",
                "encodedDataLength",
                "errorText",
                "blockedReason",
            ):
                if k in it and it.get(k) is not None:
                    entry[k] = it.get(k)
            if entry:
                out.append(entry)
        return out

    # From tier snapshot network failures, detect blocked-by-client counts (adblock).
    blocked_by_client = 0
    for it in net:
        if not isinstance(it, dict):
            continue
        err = str(it.get("errorText") or "").lower()
        br = str(it.get("blockedReason") or "").lower()
        if "err_blocked_by_client" in err or br == "blockedbyclient":
            blocked_by_client += 1

    out: dict[str, Any] = {
        "tier": diag_snapshot.get("tier") or "tier0",
        "harLiteTotal": total,
        "okApprox": ok,
        "http4xx": status_4xx,
        "http5xx": status_5xx,
        "auth401": auth_401,
        "auth403": auth_403,
        **({"blockedByClient": blocked_by_client} if blocked_by_client else {}),
        **({"failures": _take(failures)} if failures else {}),
        **({"slowApi": _take(slow_api)} if slow_api else {}),
    }

    return out


def _compact_resources(resources_payload: dict[str, Any] | None, *, max_items: int = 8) -> dict[str, Any] | None:
    resources = resources_payload.get("resources") if isinstance(resources_payload, dict) else None
    if not isinstance(resources, dict):
        return None

    out: dict[str, Any] = {"tier": resources.get("tier") or "tier1"}
    if isinstance(resources.get("summary"), dict):
        out["summary"] = resources.get("summary")

    items = resources.get("items") if isinstance(resources.get("items"), list) else []
    compact: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        entry: dict[str, Any] = {}
        for k in ("url", "status", "type", "durationMs", "encodedDataLength", "ok"):
            if k in it:
                entry[k] = it.get(k)
        if entry:
            compact.append(entry)
        if len(compact) >= max(0, int(max_items)):
            break
    out["items"] = compact

    reason = resources.get("reason")
    if isinstance(reason, str) and reason:
        out["reason"] = reason

    return out


def _compact_locators(loc_payload: dict[str, Any] | None, *, max_items: int = 10) -> dict[str, Any] | None:
    locs = loc_payload.get("locators") if isinstance(loc_payload, dict) else None
    if not isinstance(locs, dict):
        return None

    items = locs.get("items") if isinstance(locs.get("items"), list) else []
    compact: list[dict[str, Any]] = []
    missing_label = 0

    def _label(it: dict[str, Any]) -> str:
        for k in ("text", "label", "fillKey", "name", "id", "placeholder"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    for it in items:
        if not isinstance(it, dict):
            continue
        lbl = _label(it)
        if not lbl:
            missing_label += 1
        entry: dict[str, Any] = {
            **({"kind": it.get("kind")} if isinstance(it.get("kind"), str) else {}),
            **({"label": lbl} if lbl else {}),
            **({"actionHint": it.get("actionHint")} if isinstance(it.get("actionHint"), str) else {}),
            **({"ref": it.get("ref")} if isinstance(it.get("ref"), str) else {}),
        }
        if entry:
            compact.append(entry)
        if len(compact) >= max(0, int(max_items)):
            break

    out: dict[str, Any] = {
        "tier": locs.get("tier") or "tier1",
        **({"total": locs.get("total")} if isinstance(locs.get("total"), int) else {}),
        "items": compact,
        **({"missingLabelsApprox": missing_label} if missing_label else {}),
    }
    reason = locs.get("reason")
    if isinstance(reason, str) and reason:
        out["reason"] = reason
    return out


def get_page_audit(
    config: BrowserConfig,
    *,
    since: int | None = None,
    limit: int = 30,
    clear: bool = False,
) -> dict[str, Any]:
    """Return a compact super-report for agents (errors + perf + network + next actions).

    Design:
    - Best-effort: partial results are better than failure.
    - Bounded: never dumps huge arrays; prefers summaries + top items.
    - Dialog-safe: relies on underlying tools which already degrade to Tier-0 when dialogs block JS.
    """
    limit = max(0, min(int(limit), 100))
    started = time.time()

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

        performance = None
        try:
            performance = get_page_performance(config)
        except Exception:
            performance = None

        resources = None
        try:
            res_kwargs: dict[str, Any] = {"offset": 0, "limit": max(10, min(limit, 50)), "sort": "duration"}
            if since is not None:
                res_kwargs["since"] = since
            resources = get_page_resources(config, **res_kwargs)
        except Exception:
            resources = None

        locators = None
        try:
            locators = get_page_locators(config, kind="all", offset=0, limit=min(15, max(0, limit)))
        except Exception:
            locators = None

    page_info = info.get("pageInfo") if isinstance(info, dict) else None
    diag_snapshot = diagnostics.get("diagnostics") if isinstance(diagnostics, dict) else None

    # Cursor: prefer diagnostics snapshot cursor, otherwise Tier-0 cursor.
    cursor = None
    if isinstance(diag_snapshot, dict) and diag_snapshot.get("cursor") is not None:
        cursor = diag_snapshot.get("cursor")
    else:
        try:
            tab_id = session_manager.tab_id
            if isinstance(tab_id, str) and tab_id:
                t0 = session_manager.tier0_snapshot(tab_id, since=None, offset=0, limit=0)
                if isinstance(t0, dict) and t0.get("cursor") is not None:
                    cursor = t0.get("cursor")
        except Exception:
            cursor = None

    # Summary + top issues from diagnostics insights (already compact + actionable).
    summary = {}
    top = []
    dialog_open = False
    dialog = None
    if isinstance(diag_snapshot, dict):
        if isinstance(diag_snapshot.get("summary"), dict):
            summary = diag_snapshot.get("summary") or {}
        dialog_open = bool(diag_snapshot.get("dialogOpen"))
        dialog = diag_snapshot.get("dialog") if isinstance(diag_snapshot.get("dialog"), dict) else None

    insights = diagnostics.get("insights") if isinstance(diagnostics, dict) else None
    if isinstance(insights, list):
        top = [i for i in insights if isinstance(i, dict)][:5]

    out: dict[str, Any] = {
        "audit": {
            "page": (
                {
                    "url": page_info.get("url"),
                    "title": page_info.get("title"),
                    "readyState": page_info.get("readyState"),
                }
                if isinstance(page_info, dict)
                else {}
            ),
            **({"since": since} if since is not None else {}),
            **(
                {"framework": diag_snapshot.get("framework")}
                if isinstance(diag_snapshot, dict)
                and isinstance(diag_snapshot.get("framework"), dict)
                and diag_snapshot.get("framework")
                else {}
            ),
            "summary": summary,
            **({"top": top} if top else {}),
            **({"dialogOpen": True, "dialog": dialog} if dialog_open else {}),
            **(
                {"network": _compact_network(diag_snapshot)}
                if isinstance(_compact_network(diag_snapshot), dict)
                else {}
            ),
            **({"performance": _compact_perf(performance)} if isinstance(_compact_perf(performance), dict) else {}),
            **(
                {"resources": _compact_resources(resources, max_items=8)}
                if isinstance(_compact_resources(resources, max_items=8), dict)
                else {}
            ),
            **(
                {"locators": _compact_locators(locators, max_items=10)}
                if isinstance(_compact_locators(locators, max_items=10), dict)
                else {}
            ),
            "next": [
                "page(detail='locators', with_screenshot=true) for numbered UI map",
                "page(detail='resources', sort='duration') for slow assets",
                "page(detail='performance') for vitals/long-tasks",
                "page(detail='diagnostics') for full JS/network/error snapshot",
            ],
        },
        "cursor": cursor,
        "target": (diagnostics.get("target") if isinstance(diagnostics, dict) else None),
        "sessionTabId": (diagnostics.get("sessionTabId") if isinstance(diagnostics, dict) else session_manager.tab_id),
        "duration_ms": int((time.time() - started) * 1000),
    }

    # If network problems exist, suggest a deep, bounded trace capture (request/response bodies).
    try:
        net_compact = out["audit"].get("network") if isinstance(out.get("audit"), dict) else None
        if isinstance(net_compact, dict):
            has_fail = (
                bool(net_compact.get("http5xx"))
                or bool(net_compact.get("auth401"))
                or bool(net_compact.get("auth403"))
                or bool(net_compact.get("failures"))
            )
            if has_fail:
                hint = 'page(detail="audit", trace={"capture":"full"}) for bounded request/response bodies (artifact-backed)'
                nxt = out["audit"].get("next")
                if isinstance(nxt, list) and hint not in nxt:
                    nxt.insert(0, hint)
    except Exception:
        pass

    # If absolutely nothing worked, return a deterministic error.
    if not summary and not top and not out["audit"]["page"]:
        raise SmartToolError(
            tool="page",
            action="audit",
            reason="Audit not available (page snapshot unavailable)",
            suggestion="Navigate to a page first, then retry",
        )

    return out
