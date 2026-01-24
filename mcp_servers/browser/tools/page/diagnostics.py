"""Frontend diagnostics snapshot for the current page.

Captures console errors/warnings, uncaught exceptions, unhandled rejections, and
failed fetch/XHR requests (best-effort).

Instrumentation is installed automatically via SessionManager.ensure_diagnostics().
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def get_page_diagnostics(
    config: BrowserConfig,
    *,
    since: int | None = None,
    offset: int = 0,
    limit: int = 50,
    sort: str = "start",
    clear: bool = False,
) -> dict[str, Any]:
    """Return a diagnostics snapshot for the current page.

    Args:
        config: Browser configuration
        limit: Max events per category (console/errors/network). Clamped to [0..200].
        clear: Clear buffers after returning the snapshot.
    """

    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 200))
    sort = str(sort or "start")

    # Do not force Tier-1 diagnostics injection at session creation time:
    # JS dialogs (alert/confirm/prompt) can block Runtime.evaluate and cause tool timeouts.
    with get_session(config, ensure_diagnostics=False) as (session, target):
        try:
            tier0 = session_manager.ensure_telemetry(session)

            # If a JS dialog is open, Tier-1 (page injection) may be blocked; prefer Tier-0.
            dialog_blocking = False
            try:
                tab_id = session.tab_id
                if tab_id:
                    now_ms = int(time.time() * 1000)
                    recent = session_manager.tier0_snapshot(
                        tab_id,
                        since=max(0, now_ms - 30_000),
                        offset=0,
                        limit=5,
                    )
                    if isinstance(recent, dict) and recent.get("dialogOpen") is True:
                        dialog_blocking = True
            except Exception:
                dialog_blocking = False

            install: dict[str, Any]
            if dialog_blocking:
                install = {"enabled": True, "available": False, "skipped": True, "reason": "dialog_open"}
            else:
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
                "  if (!d || typeof d.snapshot !== 'function') return null;"
                f"  return d.snapshot({json.dumps(opts)});"
                "})()"
            )
            snapshot = None
            if not dialog_blocking:
                try:
                    snapshot = session.eval_js(js)
                except Exception:
                    snapshot = None

            if not snapshot:
                # Tier-0 fallback: CDP event buffers (no page injection).
                if session.tab_id is None:
                    raise SmartToolError(
                        tool="page",
                        action="diagnostics",
                        reason="Diagnostics not available (tier0+injection unavailable)",
                        suggestion="Try navigate() to a regular http(s) page, then retry. If this persists, enable MCP_TIER0=1 and MCP_DIAGNOSTICS=1.",
                    )

                url = None
                title = None
                ready_state = None
                # Avoid Runtime.evaluate here (may hang if dialog is open).
                try:
                    nav = session.send("Page.getNavigationHistory")
                    if isinstance(nav, dict):
                        idx = nav.get("currentIndex")
                        entries = nav.get("entries")
                        if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                            cur = entries[idx] if isinstance(entries[idx], dict) else None
                            if isinstance(cur, dict):
                                if isinstance(cur.get("url"), str) and cur.get("url"):
                                    url = cur.get("url")
                                if isinstance(cur.get("title"), str) and cur.get("title"):
                                    title = cur.get("title")
                except Exception:
                    url = None
                    title = None

                snapshot = session_manager.tier0_snapshot(
                    session.tab_id,
                    since=since,
                    offset=offset,
                    limit=limit,
                    url=url if isinstance(url, str) else None,
                    title=title if isinstance(title, str) else None,
                    ready_state=ready_state if isinstance(ready_state, str) else None,
                )
                if snapshot is None:
                    raise SmartToolError(
                        tool="page",
                        action="diagnostics",
                        reason="Tier-0 telemetry not available for this tab",
                        suggestion="Ensure MCP_TIER0=1 and retry. If it still fails, re-open the tab by navigate() to a regular http(s) page.",
                    )
            else:
                # Tier-1 snapshot exists: opportunistically attach Tier-0 HAR-lite (best-effort).
                # This gives network insight even when Performance/ResourceTiming is blocked.
                if session.tab_id is not None:
                    try:
                        t0 = session_manager.tier0_snapshot(
                            session.tab_id,
                            since=since,
                            offset=0,
                            limit=min(limit, 50),
                        )
                        if isinstance(t0, dict) and isinstance(t0.get("harLite"), list) and t0.get("harLite"):
                            snapshot["harLite"] = t0.get("harLite")[: min(limit, 50)]
                    except Exception:
                        pass

            if isinstance(snapshot, dict):
                snapshot = _filter_diagnostics_noise(snapshot)

            insights = _derive_insights(snapshot)

            if clear:
                # Clear Tier-1 buffers if present, then Tier-0 buffers.
                with suppress(Exception):
                    session.eval_js(
                        "globalThis.__mcpDiag && globalThis.__mcpDiag.clear && globalThis.__mcpDiag.clear()"
                    )
                with suppress(Exception):
                    session_manager.clear_telemetry(session.tab_id)

            return {
                "diagnostics": snapshot,
                "insights": insights,
                "installed": install,
                "tier0": tier0,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
                "cursor": snapshot.get("cursor") if isinstance(snapshot, dict) else None,
                **({"cleared": True} if clear else {}),
            }
        except SmartToolError:
            raise
        except Exception as exc:
            raise SmartToolError(
                tool="page",
                action="diagnostics",
                reason=str(exc),
                suggestion="Ensure the page is loaded and responsive",
            ) from exc


_HYDRATION_PATTERNS = [
    re.compile(r"hydration", re.IGNORECASE),
    re.compile(r"did not match", re.IGNORECASE),
    re.compile(r"text content does not match", re.IGNORECASE),
    re.compile(r"expected server html", re.IGNORECASE),
]


_CORS_PATTERNS = [
    re.compile(r"blocked by cors policy", re.IGNORECASE),
    re.compile(r"access-control-allow-origin", re.IGNORECASE),
    re.compile(r"cors request did not succeed", re.IGNORECASE),
    re.compile(r"preflight.*(failed|blocked)", re.IGNORECASE),
]

_CSP_PATTERNS = [
    re.compile(r"content security policy", re.IGNORECASE),
    re.compile(r"refused to .* because it violates the following content security policy directive", re.IGNORECASE),
    re.compile(r"violat.*csp", re.IGNORECASE),
]

_MIXED_CONTENT_PATTERNS = [
    re.compile(r"mixed content", re.IGNORECASE),
    re.compile(r"was loaded over https, but requested an insecure", re.IGNORECASE),
]

_COOKIE_PATTERNS = [
    re.compile(r"samesite", re.IGNORECASE),
    re.compile(r"this set-cookie was blocked", re.IGNORECASE),
    re.compile(r"cookie .* was blocked", re.IGNORECASE),
]

_FRAME_BLOCK_PATTERNS = [
    re.compile(r"x-frame-options", re.IGNORECASE),
    re.compile(r"frame-ancestors", re.IGNORECASE),
    re.compile(r"refused to display .* in a frame", re.IGNORECASE),
]

_EXTENSION_NOISE_PATTERNS = [
    re.compile(r"cannot redefine property: ethereum", re.IGNORECASE),
    re.compile(r"defineproperty.*ethereum", re.IGNORECASE),
]

_EXTENSION_SCHEME_PATTERNS = [
    re.compile(r"chrome-extension://", re.IGNORECASE),
    re.compile(r"moz-extension://", re.IGNORECASE),
    re.compile(r"safari-extension://", re.IGNORECASE),
    re.compile(r"ms-browser-extension://", re.IGNORECASE),
    re.compile(r"extension://", re.IGNORECASE),
]


def _is_extension_noise_text(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    if any(pat.search(text) for pat in _EXTENSION_NOISE_PATTERNS):
        return True
    return any(pat.search(text) for pat in _EXTENSION_SCHEME_PATTERNS)


def _filter_diagnostics_noise(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove known extension-origin noise (wallet/content scripts) from diagnostics reports."""
    if not isinstance(snapshot, dict):
        return snapshot

    def console_keep(entry: dict[str, Any]) -> bool:
        args = entry.get("args")
        if isinstance(args, list):
            for arg in args:
                if _is_extension_noise_text(str(arg)):
                    return False
        return True

    def error_keep(entry: dict[str, Any]) -> bool:
        msg = entry.get("message") if isinstance(entry, dict) else None
        if isinstance(msg, str) and _is_extension_noise_text(msg):
            return False
        filename = entry.get("filename") if isinstance(entry, dict) else None
        if isinstance(filename, str) and _is_extension_noise_text(filename):
            return False
        url = entry.get("url") if isinstance(entry, dict) else None
        return not (isinstance(url, str) and _is_extension_noise_text(url))

    def rejection_keep(entry: dict[str, Any]) -> bool:
        msg = entry.get("message") if isinstance(entry, dict) else None
        if isinstance(msg, str) and _is_extension_noise_text(msg):
            return False
        stack = entry.get("stack") if isinstance(entry, dict) else None
        return not (isinstance(stack, str) and _is_extension_noise_text(stack))

    cleaned = dict(snapshot)
    console_entries = cleaned.get("console")
    if isinstance(console_entries, list):
        cleaned["console"] = [e for e in console_entries if isinstance(e, dict) and console_keep(e)]
    errors = cleaned.get("errors")
    if isinstance(errors, list):
        cleaned["errors"] = [e for e in errors if isinstance(e, dict) and error_keep(e)]
    rejections = cleaned.get("unhandledRejections")
    if isinstance(rejections, list):
        cleaned["unhandledRejections"] = [e for e in rejections if isinstance(e, dict) and rejection_keep(e)]
    return cleaned


def _derive_insights(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a raw diagnostics snapshot to a compact list of actionable insights."""

    insights: list[dict[str, Any]] = []
    toolset = (os.environ.get("MCP_TOOLSET") or "").strip().lower()
    is_v2 = toolset in {"v2", "northstar", "north-star"}

    def add(
        *,
        severity: str,
        kind: str,
        message: str,
        suggestion: str | None = None,
        evidence: dict[str, Any] | None = None,
        score: float = 0.0,
    ) -> None:
        insights.append(
            {
                "severity": severity,
                "kind": kind,
                "message": message,
                **({"suggestion": suggestion} if suggestion else {}),
                **({"evidence": evidence} if evidence else {}),
                "_score": float(score or 0.0),
            }
        )

    console_entries = snapshot.get("console") if isinstance(snapshot, dict) else None
    errors = snapshot.get("errors") if isinstance(snapshot, dict) else None
    rejections = snapshot.get("unhandledRejections") if isinstance(snapshot, dict) else None
    failed_network = snapshot.get("network") if isinstance(snapshot, dict) else None
    har_lite = snapshot.get("harLite") if isinstance(snapshot, dict) else None
    dialog_open = bool(snapshot.get("dialogOpen")) if isinstance(snapshot, dict) else False
    dialog_meta = snapshot.get("dialog") if isinstance(snapshot, dict) else None
    dialogs = snapshot.get("dialogs") if isinstance(snapshot, dict) else None
    navigation = snapshot.get("navigation") if isinstance(snapshot, dict) else None

    net_trace_hint = (
        'run(actions=[{net:{action:"trace", capture:"full", store:true}}])'
        if is_v2
        else 'run(actions=[{"tool":"net","args":{"action":"trace","capture":"full","store":true}}])'
    )

    def _norm_ws(s: str) -> str:
        return " ".join(str(s or "").split())

    def _console_text(entry: dict[str, Any]) -> str:
        args = entry.get("args")
        if isinstance(args, list):
            return _norm_ws(" ".join(str(a) for a in args if a is not None))
        return _norm_ws(str(args or ""))

    def _top_fingerprints(texts: list[str], *, max_items: int = 3) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        sample: dict[str, str] = {}
        for t in texts:
            tt = _norm_ws(t)
            if not tt:
                continue
            key = tt[:300]
            counts[key] = counts.get(key, 0) + 1
            sample[key] = tt
        items = [{"count": c, "text": sample.get(k, k)} for k, c in counts.items()]
        items.sort(key=lambda i: (-int(i["count"]), str(i["text"])))
        return items[: max(0, int(max_items))]

    def _url_origin(url: str) -> str | None:
        try:
            parts = urlsplit(str(url))
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
        except Exception:
            return None
        return None

    # Console pattern scanning (CORS/CSP/mixed-content/cookies/xfo)
    console_warn_error_texts: list[str] = []
    if isinstance(console_entries, list):
        for entry in console_entries:
            if not isinstance(entry, dict):
                continue
            lvl = entry.get("level")
            if lvl not in {"warn", "error"}:
                continue
            txt = _console_text(entry)
            if txt:
                console_warn_error_texts.append(txt)

    def _pattern_hits(patterns: list[re.Pattern[str]], texts: list[str]) -> list[str]:
        hits: list[str] = []
        for t in texts:
            if any(p.search(t) for p in patterns):
                hits.append(t)
        return hits

    cors_hits = _pattern_hits(_CORS_PATTERNS, console_warn_error_texts)
    if cors_hits:
        add(
            severity="error",
            kind="cors",
            message=f"CORS blocked (signals: {len(cors_hits)})",
            suggestion=(
                "Fix CORS headers (Access-Control-Allow-Origin / -Credentials) and preflight; "
                f"for deep request/response capture use {net_trace_hint}"
            ),
            evidence={"examples": _top_fingerprints(cors_hits, max_items=2)},
            score=50 + len(cors_hits),
        )

    csp_hits = _pattern_hits(_CSP_PATTERNS, console_warn_error_texts)
    if csp_hits:
        add(
            severity="error",
            kind="csp",
            message=f"CSP violation detected (signals: {len(csp_hits)})",
            suggestion="Inspect the Content-Security-Policy header (script-src/style-src/frame-ancestors) and fix blocked resource/inline usage.",
            evidence={"examples": _top_fingerprints(csp_hits, max_items=2)},
            score=45 + len(csp_hits),
        )

    mixed_hits = _pattern_hits(_MIXED_CONTENT_PATTERNS, console_warn_error_texts)
    if mixed_hits:
        add(
            severity="error",
            kind="mixed_content",
            message=f"Mixed Content detected (signals: {len(mixed_hits)})",
            suggestion="Ensure all resources/APIs use HTTPS; fix hardcoded http:// links and redirects.",
            evidence={"examples": _top_fingerprints(mixed_hits, max_items=2)},
            score=40 + len(mixed_hits),
        )

    cookie_hits = _pattern_hits(_COOKIE_PATTERNS, console_warn_error_texts)
    if cookie_hits:
        add(
            severity="warn",
            kind="cookie_policy",
            message=f"Cookie/SameSite warnings detected (signals: {len(cookie_hits)})",
            suggestion="Check SameSite/ Secure / Domain / Path for auth cookies; verify third-party cookie assumptions and ITP/Chrome changes.",
            evidence={"examples": _top_fingerprints(cookie_hits, max_items=2)},
            score=20 + len(cookie_hits),
        )

    frame_hits = _pattern_hits(_FRAME_BLOCK_PATTERNS, console_warn_error_texts)
    if frame_hits:
        add(
            severity="warn",
            kind="frame_block",
            message=f"Frame/embed blocked (X-Frame-Options / frame-ancestors) (signals: {len(frame_hits)})",
            suggestion="If embedding is intended: adjust X-Frame-Options / CSP frame-ancestors; otherwise ignore.",
            evidence={"examples": _top_fingerprints(frame_hits, max_items=2)},
            score=15 + len(frame_hits),
        )

    # Blocking dialogs (alert/confirm/prompt)
    if dialog_open:
        d0 = dialog_meta if isinstance(dialog_meta, dict) else None
        if not isinstance(d0, dict):
            # Fallback: find the last "open" event in the dialog buffer.
            last_open: dict[str, Any] | None = None
            if isinstance(dialogs, list):
                for item in reversed(dialogs):
                    if isinstance(item, dict) and item.get("event") == "open":
                        last_open = item
                        break
            d0 = last_open or {}

        dtype = d0.get("type")
        msg = d0.get("message")
        suggestion = (
            'run(actions=[{dialog:{accept:true}}])  # or accept:false / text:"..."'
            if is_v2
            else "dialog(accept=true)  # or accept=false / text='...'"
        )
        add(
            severity="error",
            kind="dialog",
            message=f"Blocking JS dialog detected: {dtype or 'dialog'}",
            suggestion=suggestion,
            evidence={"type": dtype, "message": msg},
            score=90,
        )

    # JS errors
    if isinstance(errors, list):
        js_errors = [e for e in errors if isinstance(e, dict) and e.get("type") == "error" and e.get("message")]
        if js_errors:
            # Prefer the most frequent JS error message (reduces noise when the same error repeats in a loop).
            counts: dict[str, int] = {}
            last_by_msg: dict[str, dict[str, Any]] = {}
            for e in js_errors:
                msg = _norm_ws(str(e.get("message") or ""))
                if not msg:
                    continue
                counts[msg] = counts.get(msg, 0) + 1
                last_by_msg[msg] = e
            if counts:
                msg0, c0 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                e0 = last_by_msg.get(msg0) or js_errors[-1]
                add(
                    severity="error",
                    kind="js_error",
                    message=f"{msg0}" + (f" (x{c0})" if c0 > 1 else ""),
                    suggestion="Open the stack trace and fix the root cause; then reload and re-check diagnostics.",
                    evidence={
                        "count": c0,
                        "filename": e0.get("filename"),
                        "lineno": e0.get("lineno"),
                        "colno": e0.get("colno"),
                    },
                    score=80 + min(20, c0),
                )

        resource_errors = [e for e in errors if isinstance(e, dict) and e.get("type") == "resource"]
        if resource_errors:
            e0 = resource_errors[-1]
            add(
                severity="error",
                kind="resource_load_failed",
                message=f"{e0.get('tag')} failed to load",
                suggestion="Check URL, network/CSP/adblock, and whether the asset exists; then inspect resource timings.",
                evidence={"url": e0.get("url")},
                score=35,
            )

    # Unhandled promise rejections
    if isinstance(rejections, list) and rejections:
        e0 = rejections[-1] if isinstance(rejections[-1], dict) else {"message": str(rejections[-1])}
        add(
            severity="error",
            kind="unhandled_rejection",
            message=str(e0.get("message") or "Unhandled promise rejection"),
            suggestion="Find the rejecting promise and add proper error handling; check console stack trace.",
            score=60,
        )

    # Failed fetch/xhr
    if isinstance(failed_network, list) and failed_network:
        # Group by URL+status/error (avoid showing the same failure 50 times).
        fails: list[dict[str, Any]] = [e for e in failed_network if isinstance(e, dict)]
        by_key: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        blocked_by_client = 0
        for e in fails:
            url = _norm_ws(str(e.get("url") or ""))
            method = _norm_ws(str(e.get("method") or ""))
            status = e.get("status")
            try:
                status_i = int(status) if status is not None else None
            except Exception:
                status_i = None
            err_text = _norm_ws(str(e.get("errorText") or ""))
            blocked_reason = _norm_ws(str(e.get("blockedReason") or ""))
            if "err_blocked_by_client" in err_text.lower() or blocked_reason.lower() == "blockedbyclient":
                blocked_by_client += 1

            key = f"{method} {url} {status_i or ''} {err_text or blocked_reason}".strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            by_key[key] = {
                "url": url,
                "method": method,
                "status": status_i,
                "errorText": err_text,
                "blockedReason": blocked_reason,
            }

        if blocked_by_client:
            add(
                severity="warn",
                kind="blocked_by_client",
                message=f"Requests blocked by client (adblock/extension) (signals: {blocked_by_client})",
                suggestion="Retry in a clean profile or disable adblock/privacy extensions; verify corporate proxy/filters.",
                score=25 + blocked_by_client,
            )

        if counts:
            key0, c0 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            meta = by_key.get(key0, {})
            status0 = meta.get("status")
            sev = "error" if isinstance(status0, int) and status0 >= 500 else "warn"
            add(
                severity=sev,
                kind="network_failure",
                message=(
                    f"Network requests failing: {len(fails)} total; top failure x{c0}: "
                    f"{meta.get('method', '')} {meta.get('url', '')} ({status0})"
                ),
                suggestion=(f"Check API availability/CORS/auth; for deep trace capture use {net_trace_hint}"),
                evidence={"topFailure": meta, "count": c0},
                score=(70 if sev == "error" else 30) + min(30, c0),
            )

    # HAR-lite: status distribution / auth issues / 5xx clusters (Tier-0 or attached).
    if isinstance(har_lite, list) and har_lite:
        items = [it for it in har_lite if isinstance(it, dict)]
        auth: list[dict[str, Any]] = []
        s5: list[dict[str, Any]] = []
        s4: list[dict[str, Any]] = []
        origins: set[str] = set()
        for it in items:
            st = it.get("status")
            try:
                st_i = int(st) if st is not None else None
            except Exception:
                st_i = None
            url = it.get("url")
            if isinstance(url, str) and url:
                o = _url_origin(url)
                if o:
                    origins.add(o)
            if st_i in (401, 403):
                auth.append(it)
            elif isinstance(st_i, int) and st_i >= 500:
                s5.append(it)
            elif isinstance(st_i, int) and st_i >= 400:
                s4.append(it)

        def _top_urls(iters: list[dict[str, Any]], *, max_items: int = 3) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            sample: dict[str, dict[str, Any]] = {}
            for it in iters:
                u = it.get("url")
                if not isinstance(u, str) or not u:
                    continue
                counts[u] = counts.get(u, 0) + 1
                sample[u] = it
            out = []
            for u, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[: max(0, int(max_items))]:
                s = sample.get(u) or {}
                out.append(
                    {
                        "url": u,
                        "count": c,
                        **({"status": s.get("status")} if s.get("status") is not None else {}),
                        **({"type": s.get("type")} if isinstance(s.get("type"), str) else {}),
                    }
                )
            return out

        if auth:
            add(
                severity="error",
                kind="auth",
                message=f"Auth failures detected (401/403): {len(auth)} request(s)",
                suggestion="Check cookies/tokens/CSRF and whether third-party cookies are blocked; verify user segment/region gating.",
                evidence={"top": _top_urls(auth), "origins": sorted(origins)[:4]},
                score=75 + len(auth),
            )

        if s5:
            add(
                severity="error",
                kind="server_5xx",
                message=f"Server errors detected (5xx): {len(s5)} request(s)",
                suggestion=f"Identify the failing endpoint(s) and capture the response via {net_trace_hint} (redacted by default).",
                evidence={"top": _top_urls(s5)},
                score=70 + len(s5),
            )
        elif s4 and not auth:
            # 4xx without auth failures usually means validation/feature gating.
            add(
                severity="warn",
                kind="http_4xx",
                message=f"HTTP 4xx responses detected: {len(s4)} request(s)",
                suggestion="Inspect request parameters/feature flags; check validation and release gating. Use net(trace) to capture request bodies when needed.",
                evidence={"top": _top_urls(s4)},
                score=25 + len(s4),
            )

    # Navigation loops / SPA thrash (Tier-0 only, best-effort)
    if isinstance(navigation, list) and len(navigation) >= 6:
        urls: list[str] = []
        for it in navigation[-50:]:
            if not isinstance(it, dict):
                continue
            u = it.get("url")
            if isinstance(u, str) and u.strip():
                urls.append(_norm_ws(u))
        if urls:
            counts: dict[str, int] = {}
            for u in urls:
                counts[u] = counts.get(u, 0) + 1
            u0, c0 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            # If the same URL repeats a lot, the app may be stuck in a redirect/login loop.
            if c0 >= 4 or (len(urls) >= 10 and c0 >= 3):
                add(
                    severity="warn",
                    kind="navigation_loop",
                    message=f"Navigation loop/SPA thrash suspected: {c0} nav events to the same URL",
                    suggestion="Check auth redirects, router guards, and whether an API 401 triggers infinite retries; inspect Network/Console around the loop.",
                    evidence={"url": u0, "events": len(urls)},
                    score=15 + c0,
                )

    # Hydration hints (best-effort)
    hydration_hit = False
    if isinstance(console_entries, list):
        for entry in console_entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("level") not in {"warn", "error"}:
                continue
            args = entry.get("args")
            if not isinstance(args, list):
                continue
            joined = " ".join(str(a) for a in args if a is not None)
            if any(p.search(joined) for p in _HYDRATION_PATTERNS):
                hydration_hit = True
                break

    if hydration_hit:
        add(
            severity="error",
            kind="hydration",
            message="Detected hydration mismatch signals in console output",
            suggestion="If this is SSR/SPA: compare server HTML vs client render, check conditional rendering and locale-dependent formatting.",
            score=55,
        )

    # Performance hints
    vitals = snapshot.get("vitals") if isinstance(snapshot, dict) else None
    if isinstance(vitals, dict):
        cls = vitals.get("cls")
        if isinstance(cls, (int, float)) and cls >= 0.1:
            add(
                severity="warn" if cls < 0.25 else "error",
                kind="cls",
                message=f"High Cumulative Layout Shift (CLS): {cls:.3f}",
                suggestion="Reserve layout space for images/fonts, avoid inserting content above existing content.",
                score=10 + float(cls),
            )

        lcp = vitals.get("lcp")
        if isinstance(lcp, dict) and isinstance(lcp.get("startTime"), (int, float)):
            lcp_ms = float(lcp["startTime"])
            if lcp_ms >= 2500:
                add(
                    severity="warn" if lcp_ms < 4000 else "error",
                    kind="lcp",
                    message=f"Slow LCP: {int(lcp_ms)}ms",
                    suggestion="Optimize the LCP element (often hero image/text): reduce JS, compress images, preconnect critical origins.",
                    evidence={"element": lcp.get("element"), "url": lcp.get("url")},
                    score=10 + (lcp_ms / 1000.0),
                )

    # Dev error overlay (vite/next/webpack)
    dev_overlay = snapshot.get("devOverlay") if isinstance(snapshot, dict) else None
    if isinstance(dev_overlay, dict) and dev_overlay.get("type"):
        add(
            severity="error",
            kind="dev_overlay",
            message=f"Dev error overlay detected ({dev_overlay.get('type')})",
            suggestion="Fix the runtime/build error shown in the overlay (it usually includes a stack trace), then reload and re-check diagnostics.",
            evidence={"text": dev_overlay.get("text")},
            score=85,
        )

    # Resource / network performance hints
    resources = snapshot.get("resources") if isinstance(snapshot, dict) else None
    if isinstance(resources, dict):
        summary = resources.get("summary")
        if isinstance(summary, dict):
            total_transfer = summary.get("totalTransferSize")
            if isinstance(total_transfer, (int, float)) and total_transfer >= 5_000_000:
                add(
                    severity="warn" if total_transfer < 10_000_000 else "error",
                    kind="transfer_size",
                    message=f"High total transfer size: {total_transfer / 1_000_000:.1f}MB",
                    suggestion="Reduce bundle/asset size (compression, code-splitting, remove unused deps), and optimize images.",
                    score=5 + (float(total_transfer) / 1_000_000.0),
                )

            largest = summary.get("largest")
            if isinstance(largest, list) and largest:
                r0 = largest[0] if isinstance(largest[0], dict) else {}
                size = r0.get("transferSize")
                if isinstance(size, (int, float)) and size >= 1_000_000:
                    add(
                        severity="warn" if size < 2_000_000 else "error",
                        kind="largest_resource",
                        message=f"Large resource: {size / 1_000_000:.1f}MB",
                        suggestion="Compress/split the largest assets (often JS bundles or hero images).",
                        evidence={"url": r0.get("url"), "initiatorType": r0.get("initiatorType")},
                        score=5 + (float(size) / 1_000_000.0),
                    )

            slowest = summary.get("slowest")
            if isinstance(slowest, list) and slowest:
                r0 = slowest[0] if isinstance(slowest[0], dict) else {}
                dur = r0.get("duration")
                if isinstance(dur, (int, float)) and dur >= 3000:
                    add(
                        severity="warn" if dur < 8000 else "error",
                        kind="slow_resource",
                        message=f"Slow resource: {int(dur)}ms",
                        suggestion="Look for server latency, compression, caching headers, and reduce critical-path requests.",
                        evidence={"url": r0.get("url"), "initiatorType": r0.get("initiatorType")},
                        score=5 + (float(dur) / 1000.0),
                    )

        longtasks = vitals.get("longTasks")
        if isinstance(longtasks, dict) and isinstance(longtasks.get("maxDuration"), (int, float)):
            max_dur = float(longtasks["maxDuration"])
            if max_dur >= 50:
                add(
                    severity="warn" if max_dur < 200 else "error",
                    kind="long_tasks",
                    message=f"Long tasks detected (max {int(max_dur)}ms)",
                    suggestion="Break up heavy JS work, defer non-critical scripts, and consider code-splitting.",
                    score=5 + (max_dur / 100.0),
                )

    # Keep output compact: top 10 by severity order
    severity_rank = {"error": 0, "warn": 1, "info": 2}
    insights.sort(key=lambda i: (severity_rank.get(str(i.get("severity")), 3), -float(i.get("_score", 0.0))))
    out: list[dict[str, Any]] = []
    for it in insights:
        if not isinstance(it, dict):
            continue
        it.pop("_score", None)
        out.append(it)
        if len(out) >= 10:
            break
    return out
