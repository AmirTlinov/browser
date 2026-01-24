"""Tier-0 CDP telemetry (server-side, no page injection required).

Goal:
- Capture high-signal frontend events even when page injection is unavailable.
- Keep outputs cognitively-cheap: bounded buffers + delta cursors.

This is intentionally minimal and best-effort:
- We do NOT try to replicate the full DevTools protocol surface.
- We store only events that usually change decisions (errors/warnings/failures/navigation/dialogs).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .server.redaction import redact_url_brief as redact_url


def _sha256_hex(text: str) -> str:
    try:
        import hashlib

        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    except Exception:
        return ""


def _is_sensitive_header_name(name: str) -> bool:
    lk = str(name or "").strip().lower()
    if not lk:
        return True
    if lk.startswith("cookie") or lk.startswith("set-cookie") or lk.startswith("authorization"):
        return True
    # Heuristic: if it looks like it can contain secrets, redact.
    return any(frag in lk for frag in ("token", "secret", "password", "pass", "pwd", "key", "session"))


def _select_headers(
    headers: Any, *, max_keys: int = 48, max_selected: int = 24, max_value_len: int = 180
) -> dict[str, Any] | None:
    """Keep a small, redacted header preview suitable for Tier-0 telemetry.

    Notes:
    - Never store Cookie/Authorization values (hash-only redaction).
    - Prefer keeping 'x-*' and content-type-ish headers for debugging.
    """
    if not isinstance(headers, dict) or not headers:
        return None

    keys: list[str] = []
    selected: dict[str, Any] = {}

    def _want_value(lk: str) -> bool:
        if lk.startswith("x-"):
            return True
        return lk in {"content-type", "accept", "accept-language", "origin", "referer", "user-agent"}

    for k, v in headers.items():
        lk = str(k or "").strip().lower()
        if not lk:
            continue
        keys.append(lk)
        if len(keys) > max(0, int(max_keys)):
            continue
        if len(selected) >= max(0, int(max_selected)):
            continue
        if not _want_value(lk):
            continue

        if _is_sensitive_header_name(lk):
            # Redact value but keep a stable fingerprint for correlation.
            sv = _str(v, max_len=600)
            selected[lk] = {
                "redacted": True,
                **({"len": len(sv)} if isinstance(sv, str) else {}),
                **({"sha256": _sha256_hex(sv)} if isinstance(sv, str) and sv else {}),
            }
            continue

        # Non-sensitive: keep a short value preview.
        selected[lk] = _str(v, max_len=max(40, int(max_value_len)))

    out: dict[str, Any] = {"keys": keys[: max(0, int(max_keys))]}
    if selected:
        out["selected"] = selected
    return out


def _initiator_top(params: Any) -> dict[str, Any] | None:
    """Extract a tiny initiator fingerprint from Network.requestWillBeSent params."""
    if not isinstance(params, dict):
        return None
    initiator = params.get("initiator")
    if not isinstance(initiator, dict):
        return None

    out: dict[str, Any] = {}
    itype = initiator.get("type")
    if isinstance(itype, str) and itype:
        out["type"] = _str(itype, max_len=40)

    # Prefer top stack frame (script-initiated requests).
    stack = initiator.get("stack")
    if isinstance(stack, dict):
        call_frames = stack.get("callFrames")
        if isinstance(call_frames, list) and call_frames:
            top = call_frames[0] if isinstance(call_frames[0], dict) else None
            if isinstance(top, dict):
                u = top.get("url")
                if isinstance(u, str) and u:
                    out["url"] = redact_url(u)
                fn = top.get("functionName")
                if isinstance(fn, str) and fn:
                    out["function"] = _str(fn, max_len=120)
                ln = top.get("lineNumber")
                cn = top.get("columnNumber")
                if isinstance(ln, int):
                    out["line"] = ln
                if isinstance(cn, int):
                    out["col"] = cn

    # Some Chrome versions include 'url' directly on initiator (parser/preload).
    iu = initiator.get("url")
    if "url" not in out and isinstance(iu, str) and iu:
        out["url"] = redact_url(iu)

    return out or None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp_int(value: Any, *, default: int, min_v: int, max_v: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = default
    return max(min_v, min(v, max_v))


def _str(x: Any, *, max_len: int = 500) -> str:
    try:
        s = str(x)
    except Exception:
        s = "<unstringifiable>"
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"… <truncated len={len(s)}>"


def _remote_obj_to_str(obj: Any) -> str:
    """Best-effort conversion of CDP RemoteObject to short string."""
    if not isinstance(obj, dict):
        return _str(obj)
    for k in ("value", "unserializableValue", "description"):
        if k in obj and obj.get(k) is not None:
            return _str(obj.get(k))
    # Fallback: type/subtype preview
    typ = obj.get("type")
    subtype = obj.get("subtype")
    return _str(f"<{typ}{('/' + subtype) if subtype else ''}>")


def _stack_top(params: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the top stack frame (if present) from CDP event params."""
    st = params.get("stackTrace")
    if not isinstance(st, dict):
        return None
    frames = st.get("callFrames")
    if not isinstance(frames, list) or not frames:
        return None
    f0 = frames[0]
    if not isinstance(f0, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(f0.get("url"), str) and f0.get("url"):
        out["url"] = redact_url(f0["url"])
    if isinstance(f0.get("functionName"), str) and f0.get("functionName"):
        out["function"] = _str(f0["functionName"], max_len=120)
    if isinstance(f0.get("lineNumber"), int):
        out["line"] = int(f0["lineNumber"])
    if isinstance(f0.get("columnNumber"), int):
        out["col"] = int(f0["columnNumber"])
    return out or None


def _header_value(headers: dict[str, Any], name: str) -> str | None:
    """Case-insensitive header lookup (best-effort)."""
    if not isinstance(headers, dict) or not headers:
        return None
    want = str(name or "").strip().lower()
    if not want:
        return None
    for k, v in headers.items():
        if str(k).strip().lower() == want:
            if isinstance(v, str) and v:
                return v
            try:
                s = str(v)
            except Exception:
                s = ""
            return s if s else None
    return None


@dataclass(slots=True)
class Tier0Telemetry:
    """Bounded, high-signal CDP event buffers for one tab."""

    max_events: int = 200
    max_request_map: int = 800

    console: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    network: list[dict[str, Any]] = field(default_factory=list)
    harLite: list[dict[str, Any]] = field(default_factory=list)
    dialogs: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[dict[str, Any]] = field(default_factory=list)

    # Dialog state (for fail-fast waits and robust cross-call handling).
    dialog_open: bool = False
    dialog_last: dict[str, Any] | None = None

    # requestId -> request metadata (for attaching URL/method to failures)
    _req: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    # requestId -> *recently completed* request metadata (for deep, on-demand tracing)
    _req_done: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    cursor: int = 0

    def _push(self, buf: list[dict[str, Any]], item: dict[str, Any]) -> None:
        buf.append(item)
        if len(buf) > self.max_events:
            del buf[: len(buf) - self.max_events]

    def _remember_request(self, request_id: str, meta: dict[str, Any]) -> None:
        if not request_id:
            return
        self._req[request_id] = meta
        if len(self._req) > self.max_request_map:
            # Drop oldest-ish entries deterministically: by insertion order (Py3.7+ preserves order).
            drop = len(self._req) - self.max_request_map
            for k in list(self._req.keys())[:drop]:
                self._req.pop(k, None)

    def _remember_done_request(self, request_id: str, meta: dict[str, Any]) -> None:
        if not request_id:
            return
        self._req_done[request_id] = meta
        if len(self._req_done) > self.max_request_map:
            drop = len(self._req_done) - self.max_request_map
            for k in list(self._req_done.keys())[:drop]:
                self._req_done.pop(k, None)

    def ingest(self, event: dict[str, Any]) -> None:
        """Ingest a raw CDP event dict (best-effort, bounded)."""
        if not isinstance(event, dict):
            return

        method = event.get("method")
        if not isinstance(method, str) or not method:
            return

        params = event.get("params")
        if not isinstance(params, dict):
            params = {}

        ts = _now_ms()
        self.cursor = max(self.cursor, ts)

        # ──────────────────────────────────────────────────────────────────
        # Console
        # ──────────────────────────────────────────────────────────────────
        if method == "Runtime.consoleAPICalled":
            level = params.get("type")
            if level == "warning":
                level = "warn"
            level = level if isinstance(level, str) else "log"
            args = params.get("args")
            if isinstance(args, list):
                msg = " ".join(_remote_obj_to_str(a) for a in args[:8])
            else:
                msg = ""
            entry: dict[str, Any] = {"ts": ts, "level": level, "args": [msg] if msg else []}
            top = _stack_top(params)
            if top:
                entry["stackTop"] = top
            # High-signal only: keep warn/error always; keep a small amount of info/debug.
            if level in {"error", "warn"}:
                self._push(self.console, entry)
            else:
                # Keep at most a few non-error console messages (useful for login flows).
                if len(self.console) < max(20, self.max_events // 10):
                    self._push(self.console, entry)
            return

        # ──────────────────────────────────────────────────────────────────
        # Exceptions
        # ──────────────────────────────────────────────────────────────────
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails")
            if not isinstance(details, dict):
                details = {}
            msg = details.get("text") or "Uncaught exception"
            url = details.get("url")
            lineno = details.get("lineNumber")
            colno = details.get("columnNumber")

            exception = details.get("exception")
            if isinstance(exception, dict):
                msg = exception.get("description") or exception.get("value") or msg

            err: dict[str, Any] = {
                "ts": ts,
                "type": "error",
                "message": _str(msg, max_len=1200),
            }
            if isinstance(url, str) and url:
                err["filename"] = redact_url(url)
            if isinstance(lineno, int):
                err["lineno"] = lineno
            if isinstance(colno, int):
                err["colno"] = colno

            top = _stack_top(details)  # exceptionDetails sometimes contains stackTrace
            if top:
                err["stackTop"] = top

            self._push(self.errors, err)
            return

        # ──────────────────────────────────────────────────────────────────
        # Network (capture failures + error statuses)
        # ──────────────────────────────────────────────────────────────────
        if method == "Network.requestWillBeSent":
            request_id = params.get("requestId")
            req = params.get("request")
            if isinstance(request_id, str) and isinstance(req, dict):
                url = req.get("url")
                meta: dict[str, Any] = {
                    "ts": ts,
                    "method": req.get("method") if isinstance(req.get("method"), str) else None,
                }
                if isinstance(url, str) and url:
                    meta["url"] = redact_url(url)
                    # Keep the full URL (incl. query) for deep, on-demand tracing only.
                    # This is NOT exposed in Tier-0 snapshots by default.
                    meta["urlFull"] = _str(url, max_len=2000)
                if isinstance(params.get("type"), str):
                    meta["type"] = params.get("type")

                    # Keep a small header preview for XHR/Fetch (helps debug pricing/auth bugs).
                    # Never store full cookies/authorization values (redacted+hashed only).
                    if meta.get("type") in {"XHR", "Fetch"}:
                        hdrs = req.get("headers")
                        sel = _select_headers(hdrs)
                        if isinstance(sel, dict) and sel:
                            meta["reqHeaders"] = sel

                init = _initiator_top(params)
                if isinstance(init, dict) and init:
                    meta["initiator"] = init
                self._remember_request(request_id, meta)
            return

        if method == "Network.responseReceived":
            resp = params.get("response")
            if not isinstance(resp, dict):
                resp = {}
            status = resp.get("status")
            try:
                status_i = int(status) if status is not None else None
            except Exception:
                status_i = None

            # Track status for HAR-lite correlation.
            req_id = params.get("requestId") if isinstance(params.get("requestId"), str) else ""
            if req_id:
                meta = self._req.get(req_id)
                if isinstance(meta, dict) and status_i is not None:
                    meta["status"] = status_i

                    # Best-effort: store MIME / content-type for trace UX (tiny, bounded).
                    mime = resp.get("mimeType")
                    if isinstance(mime, str) and mime:
                        meta["mimeType"] = _str(mime, max_len=120)
                    headers = resp.get("headers")
                    if isinstance(headers, dict):
                        ct = _header_value(headers, "content-type")
                        if isinstance(ct, str) and ct:
                            meta["contentType"] = _str(ct, max_len=200)

                        # Keep a small response header preview for XHR/Fetch.
                        if meta.get("type") in {"XHR", "Fetch"}:
                            sel = _select_headers(headers)
                            if isinstance(sel, dict) and sel:
                                meta["respHeaders"] = sel

            # Keep only error-ish statuses to avoid noise.
            if status_i is not None and status_i >= 400:
                url = resp.get("url")
                meta = self._req.get(req_id, {}) if req_id else {}
                method = meta.get("method")
                item: dict[str, Any] = {
                    "ts": ts,
                    "url": redact_url(url) if isinstance(url, str) else meta.get("url", ""),
                    "status": status_i,
                    **({"method": method} if isinstance(method, str) and method else {}),
                }
                rtype = params.get("type")
                if isinstance(rtype, str) and rtype:
                    item["type"] = rtype
                self._push(self.network, item)
            return

        if method == "Network.loadingFailed":
            req_id = params.get("requestId") if isinstance(params.get("requestId"), str) else ""
            meta = self._req.get(req_id, {}) if req_id else {}
            item = {
                "ts": ts,
                "url": meta.get("url", ""),
                **({"method": meta.get("method")} if isinstance(meta.get("method"), str) else {}),
                "status": None,
                "errorText": _str(params.get("errorText")),
            }
            blocked = params.get("blockedReason")
            if isinstance(blocked, str) and blocked:
                item["blockedReason"] = blocked
            self._push(self.network, item)

            # HAR-lite: failed request summary (duration best-effort).
            try:
                started = int(meta.get("ts")) if isinstance(meta.get("ts"), int) else None
                duration_ms = ts - started if isinstance(started, int) and started > 0 else None
                har_item: dict[str, Any] = {
                    "ts": ts,
                    "url": meta.get("url", ""),
                    **({"method": meta.get("method")} if isinstance(meta.get("method"), str) else {}),
                    "status": None,
                    "ok": False,
                    "errorText": _str(params.get("errorText")),
                    **({"durationMs": duration_ms} if isinstance(duration_ms, int) and duration_ms >= 0 else {}),
                }
                self._push(self.harLite, har_item)
            except Exception:
                pass

            # Trace buffer: keep a compact completed-record keyed by requestId.
            if req_id:
                try:
                    started = int(meta.get("ts")) if isinstance(meta.get("ts"), int) else None
                    duration_ms = ts - started if isinstance(started, int) and started > 0 else None
                except Exception:
                    duration_ms = None
                done: dict[str, Any] = {
                    **(meta if isinstance(meta, dict) else {}),
                    "endTs": ts,
                    **({"durationMs": duration_ms} if isinstance(duration_ms, int) and duration_ms >= 0 else {}),
                    "ok": False,
                    "errorText": _str(params.get("errorText")),
                }
                blocked = params.get("blockedReason")
                if isinstance(blocked, str) and blocked:
                    done["blockedReason"] = blocked
                self._remember_done_request(req_id, done)

            # Cleanup request map entry (avoid leaks).
            if req_id:
                self._req.pop(req_id, None)
            return

        if method == "Network.loadingFinished":
            # HAR-lite: compact request summaries (bounded, delta-friendly).
            req_id = params.get("requestId") if isinstance(params.get("requestId"), str) else ""
            meta = self._req.get(req_id, {}) if req_id else {}
            try:
                started = int(meta.get("ts")) if isinstance(meta.get("ts"), int) else None
                duration_ms = ts - started if isinstance(started, int) and started > 0 else None
            except Exception:
                duration_ms = None

            status_i = meta.get("status")
            try:
                status_i = int(status_i) if status_i is not None else None
            except Exception:
                status_i = None

            encoded_len = (
                params.get("encodedDataLength") if isinstance(params.get("encodedDataLength"), (int, float)) else None
            )
            rtype = meta.get("type") if isinstance(meta.get("type"), str) else None

            ok = True
            if isinstance(status_i, int) and status_i >= 400:
                ok = False

            # Keep signal without dumping full waterfall noise:
            # - Always keep failures.
            # - Keep primary resource types (document/script/css/xhr/fetch).
            # - Keep anything slow-ish or large-ish.
            high_signal_types = {"Document", "XHR", "Fetch", "Script", "Stylesheet"}
            slow_ms = 300
            large_bytes = 20_000

            keep = (not ok) or (rtype in high_signal_types)
            if not keep and isinstance(duration_ms, int) and duration_ms >= slow_ms:
                keep = True
            if not keep and isinstance(encoded_len, (int, float)) and float(encoded_len) >= large_bytes:
                keep = True

            if keep:
                har_item: dict[str, Any] = {
                    "ts": ts,
                    "url": meta.get("url", ""),
                    **({"method": meta.get("method")} if isinstance(meta.get("method"), str) else {}),
                    **({"status": status_i} if isinstance(status_i, int) else {}),
                    **({"type": rtype} if isinstance(rtype, str) and rtype else {}),
                    **({"startTs": started} if isinstance(started, int) and started > 0 else {}),
                    "ok": bool(ok),
                    **({"durationMs": duration_ms} if isinstance(duration_ms, int) and duration_ms >= 0 else {}),
                    **({"encodedDataLength": encoded_len} if isinstance(encoded_len, (int, float)) else {}),
                }
                self._push(self.harLite, har_item)

            # Trace buffer: keep a compact completed-record keyed by requestId.
            if req_id:
                done: dict[str, Any] = {
                    **(meta if isinstance(meta, dict) else {}),
                    "endTs": ts,
                    "ok": bool(ok),
                    **({"durationMs": duration_ms} if isinstance(duration_ms, int) and duration_ms >= 0 else {}),
                    **({"encodedDataLength": encoded_len} if isinstance(encoded_len, (int, float)) else {}),
                }
                self._remember_done_request(req_id, done)

            # Cleanup request map entry (avoid leaks).
            if req_id:
                self._req.pop(req_id, None)
            return

        # ──────────────────────────────────────────────────────────────────
        # Dialogs
        # ──────────────────────────────────────────────────────────────────
        if method == "Page.javascriptDialogOpening":
            msg = params.get("message")
            dtype = params.get("type")
            url = params.get("url")
            entry: dict[str, Any] = {"ts": ts, "event": "open"}
            if isinstance(dtype, str) and dtype:
                entry["type"] = dtype
            if isinstance(msg, str) and msg:
                entry["message"] = _str(msg, max_len=800)
            if isinstance(url, str) and url:
                entry["url"] = redact_url(url)
            self.dialog_open = True
            self.dialog_last = entry
            self._push(self.dialogs, entry)
            return

        if method == "Page.javascriptDialogClosed":
            # Note: params may include:
            # - result: bool (true if accepted)
            # - userInput: string (prompt text)
            entry: dict[str, Any] = {"ts": ts, "event": "closed"}
            if isinstance(params.get("result"), bool):
                entry["accepted"] = bool(params.get("result"))
            if isinstance(params.get("userInput"), str) and params.get("userInput"):
                entry["userInput"] = _str(params.get("userInput"), max_len=200)
            self.dialog_open = False
            # Keep dialog_last for context (useful for triage), but do not mutate it.
            self._push(self.dialogs, entry)
            return

        # ──────────────────────────────────────────────────────────────────
        # Navigation (keep small)
        # ──────────────────────────────────────────────────────────────────
        if method == "Page.navigatedWithinDocument":
            url = params.get("url")
            if isinstance(url, str) and url:
                self._push(self.navigation, {"ts": ts, "url": redact_url(url), "kind": "spa"})
            return

        if method == "Page.frameNavigated":
            frame = params.get("frame")
            if isinstance(frame, dict):
                url = frame.get("url")
                parent_id = frame.get("parentId")
                # Prefer top-level frame only (reduces noise).
                if isinstance(url, str) and url and not parent_id:
                    self._push(self.navigation, {"ts": ts, "url": redact_url(url), "kind": "frame"})
            return

    def snapshot(
        self,
        *,
        since: int | None = None,
        offset: int = 0,
        limit: int = 50,
        url: str | None = None,
        title: str | None = None,
        ready_state: str | None = None,
    ) -> dict[str, Any]:
        """Return a diagnostics-like snapshot (shape-compatible with Tier-1 injection)."""
        since_i = None
        if since is not None:
            try:
                since_i = int(since)
            except Exception:
                since_i = None

        offset = _clamp_int(offset, default=0, min_v=0, max_v=1000000)
        limit = _clamp_int(limit, default=50, min_v=0, max_v=self.max_events)

        def filt(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if since_i is None:
                out = items
            else:
                out = [e for e in items if isinstance(e, dict) and isinstance(e.get("ts"), int) and e["ts"] > since_i]
            if offset:
                out = out[offset:]
            if limit:
                out = out[:limit]
            return out

        console = filt(self.console)
        errors = filt(self.errors)
        network = filt(self.network)
        dialogs = filt(self.dialogs)
        navigation = filt(self.navigation)
        har_lite = filt(self.harLite)

        summary = {
            "consoleErrors": len([e for e in console if e.get("level") == "error"]),
            "consoleWarnings": len([e for e in console if e.get("level") == "warn"]),
            "jsErrors": len([e for e in errors if e.get("type") == "error"]),
            "resourceErrors": 0,
            "unhandledRejections": 0,
            "failedRequests": len(network),
            "lastError": (errors[-1].get("message") if errors else None),
        }

        snap: dict[str, Any] = {
            "tier": "tier0",
            "cursor": self.cursor or _now_ms(),
            "summary": summary,
            "console": console,
            "errors": errors,
            "unhandledRejections": [],
            "network": network,
            "harLite": har_lite,
            "dialogs": dialogs,
            "dialogOpen": bool(self.dialog_open),
            "navigation": navigation,
        }
        if self.dialog_open and isinstance(self.dialog_last, dict):
            # Keep only stable, high-signal fields (avoid noise).
            d = self.dialog_last
            snap["dialog"] = {
                "type": d.get("type"),
                "message": d.get("message"),
                "url": d.get("url"),
                "ts": d.get("ts"),
            }
        if isinstance(url, str) and url:
            snap["url"] = url
        if isinstance(title, str) and title:
            snap["title"] = title
        if isinstance(ready_state, str) and ready_state:
            snap["readyState"] = ready_state

        if since_i is not None:
            snap["since"] = since_i

        return snap
