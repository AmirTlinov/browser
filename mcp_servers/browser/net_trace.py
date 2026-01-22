"""Tier-0 deep network trace helper (bounded, redacted by default).

This module is shared by:
- run() internal net(action="trace")  (v2 internal action)
- page(detail="audit", trace=...)     (one-call debug bundle)

Design goals:
- Fast and low-noise by default (metadata-only).
- Ability to escalate to request/response capture (bounded + redacted).
- Works in both launch mode (direct CDP) and extension mode.
"""

from __future__ import annotations

import base64
import json
import re
import time
from collections import Counter
from contextlib import suppress
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .config import BrowserConfig
from .server.artifacts import artifact_store
from .server.hints import artifact_get_hint
from .server.redaction import redact_text_content
from .session import session_manager
from .tools.base import SmartToolError, get_session


def _to_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        # allow comma-separated convenience
        if "," in s:
            return [p.strip() for p in s.split(",") if p.strip()]
        return [s]
    if isinstance(v, list):
        out: list[str] = []
        for it in v:
            if isinstance(it, str) and it.strip():
                out.append(it.strip())
        return out
    return []


def _to_int_default(v: Any, *, default: int, min_v: int, max_v: int) -> int:
    try:
        if v is None or isinstance(v, bool):
            raise ValueError
        if isinstance(v, (int, float)):
            n = int(v)
        else:
            n = int(float(str(v).strip()))
    except Exception:
        n = int(default)
    return max(min_v, min(n, max_v))


def _url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _status_bucket(status: Any) -> str:
    try:
        s = int(status)
    except Exception:
        return "unknown"
    if 100 <= s < 200:
        return "1xx"
    if 200 <= s < 300:
        return "2xx"
    if 300 <= s < 400:
        return "3xx"
    if 400 <= s < 500:
        return "4xx"
    if 500 <= s < 600:
        return "5xx"
    return "other"


_SENSITIVE_QUERY_KEY_HINTS = (
    "token",
    "auth",
    "password",
    "passwd",
    "secret",
    "session",
    "cookie",
    "jwt",
    "bearer",
    "signature",
    "sig",
    "key",
)


def _safe_query_keys(url_full: str) -> list[str]:
    """Return query parameter *names* only (never values).

    This is safe to include in tool output and often helps debugging (coupon/promo flags,
    feature gates, experiment buckets) without leaking sensitive values.
    """
    try:
        u = urlsplit(url_full)
    except Exception:
        return []
    if not u.query:
        return []

    keys: list[str] = []
    try:
        for k, _v in parse_qsl(u.query, keep_blank_values=True):
            kk = str(k or "").strip()
            if not kk:
                continue
            lk = kk.lower()
            if any(h in lk for h in _SENSITIVE_QUERY_KEY_HINTS):
                continue
            keys.append(kk)
    except Exception:
        return []

    # Keep deterministic order + bounded size.
    out: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
        if len(out) >= 20:
            break
    return out


def _summarize_trace(*, matched: list[dict[str, Any]], done: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute a compact, cognitive-cheap summary from matched trace items."""
    status_buckets: Counter[str] = Counter()
    types: Counter[str] = Counter()
    hosts: Counter[str] = Counter()
    query_keys: Counter[str] = Counter()
    ok_false = 0
    errors: Counter[str] = Counter()

    for rec in matched:
        if not isinstance(rec, dict):
            continue
        types[str(rec.get("type") or "")] += 1
        status_buckets[_status_bucket(rec.get("status"))] += 1
        url = rec.get("url") if isinstance(rec.get("url"), str) else ""
        host = _url_host(url)
        if host:
            hosts[host] += 1
        if rec.get("ok") is False:
            ok_false += 1
        err = rec.get("errorText") if isinstance(rec.get("errorText"), str) else None
        if err:
            errors[err] += 1

        rid = rec.get("requestId") if isinstance(rec.get("requestId"), str) else None
        meta = done.get(rid) if rid else None
        url_full = meta.get("urlFull") if isinstance(meta, dict) and isinstance(meta.get("urlFull"), str) else None
        if not url_full:
            url_full = url
        for k in _safe_query_keys(url_full):
            query_keys[k] += 1

    def _top(counter: Counter[str], n: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for k, v in counter.most_common(n):
            if not k or not v:
                continue
            out.append({"key": k, "count": int(v)})
        return out

    return {
        "status": {k: int(v) for k, v in status_buckets.items() if v},
        "types": {k: int(v) for k, v in types.items() if k and v},
        "okFalse": int(ok_false),
        "topHosts": _top(hosts, 6),
        "topQueryKeys": _top(query_keys, 10),
        "topErrors": _top(errors, 5),
    }


def _body_preview(
    *, full_items: list[dict[str, Any]], max_items: int = 3, max_chars: int = 1800
) -> list[dict[str, Any]]:
    """Return a tiny preview of captured request/response bodies (already redacted).

    We keep this extremely bounded to avoid leaking large payloads into tool output.
    Full fidelity remains artifact-backed.
    """
    picked: list[dict[str, Any]] = []

    # Prioritize error-ish requests.
    def _rank(it: dict[str, Any]) -> int:
        st = it.get("status")
        try:
            s = int(st)
        except Exception:
            s = 0
        ok = it.get("ok") is True
        # Higher is more important.
        if not ok:
            return 1000 + s
        if s >= 400:
            return 900 + s
        return s

    candidates = [it for it in full_items if isinstance(it, dict)]
    candidates.sort(key=_rank, reverse=True)

    for it in candidates[: max(0, int(max_items))]:
        rec: dict[str, Any] = {}
        for k in ("requestId", "ts", "url", "method", "type", "status", "ok"):
            if k in it:
                rec[k] = it.get(k)
        if isinstance(it.get("requestPostData"), str):
            rec["requestPostData"] = str(it.get("requestPostData"))[: max(0, int(max_chars))]
            if len(str(it.get("requestPostData"))) > max_chars:
                rec["requestPostDataTruncated"] = True
        if isinstance(it.get("responseBody"), str):
            rec["responseBody"] = str(it.get("responseBody"))[: max(0, int(max_chars))]
            if len(str(it.get("responseBody"))) > max_chars:
                rec["responseBodyTruncated"] = True
        if isinstance(it.get("responseBodyBase64Bytes"), int):
            rec["responseBodyBase64Bytes"] = int(it.get("responseBodyBase64Bytes") or 0)
        if isinstance(it.get("responseBodyError"), str):
            rec["responseBodyError"] = it.get("responseBodyError")
        if rec:
            picked.append(rec)
        if len(picked) >= max_items:
            break

    return picked


_MONEY_KEY_RE = re.compile(r"(amount|price|total|subtotal|tax|vat)", re.IGNORECASE)
_CURRENCY_KEY_RE = re.compile(r"currency|curr|iso", re.IGNORECASE)

# Common currency minor unit mapping (ISO 4217, partial; default=2).
_CURRENCY_DECIMALS: dict[str, int] = {
    # 0-decimal
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "MGA": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    # 2-decimal (explicitly listed for readability)
    "RUB": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
}


def _json_try_parse(text: Any, *, max_chars: int = 120_000) -> Any | None:
    """Best-effort JSON parse for bounded trace bodies (already redacted)."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if len(s) > max_chars:
        return None
    if not (s.startswith("{") or s.startswith("[")):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _money_kind_from_url(url: str) -> str:
    """Heuristic classification of a URL for money/checkout correlation."""
    u = (url or "").lower()
    if any(k in u for k in ("directpayment", "stripe", "paypal", "checkout", "payment", "invoice", "session")):
        return "payment"
    if any(k in u for k in ("cart", "basket", "order", "pricing", "quote", "subscription", "product")):
        return "cart"
    return "other"


def _walk_money_fields(
    obj: Any,
    *,
    url: str,
    source: str,
    currency_ctx: str | None = None,
    path: str = "",
    depth: int = 0,
    max_depth: int = 12,
    out: list[dict[str, Any]],
) -> None:
    if depth > max_depth:
        return

    if isinstance(obj, dict):
        cur = currency_ctx
        # Update currency context from this dict.
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            if _CURRENCY_KEY_RE.search(k) and isinstance(v, str) and v.strip():
                cur = v.strip().upper()
                break

        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            p2 = f"{path}.{k}" if path else k

            if isinstance(v, (int, float)) and _MONEY_KEY_RE.search(k):
                rec: dict[str, Any] = {
                    "url": url,
                    "source": source,
                    "path": p2,
                    "value": v,
                }
                if isinstance(cur, str) and cur:
                    rec["currency"] = cur
                out.append(rec)

            _walk_money_fields(
                v,
                url=url,
                source=source,
                currency_ctx=cur,
                path=p2,
                depth=depth + 1,
                max_depth=max_depth,
                out=out,
            )
        return

    if isinstance(obj, list):
        for i, v in enumerate(obj[:200]):
            p2 = f"{path}[{i}]" if path else f"[{i}]"
            _walk_money_fields(
                v,
                url=url,
                source=source,
                currency_ctx=currency_ctx,
                path=p2,
                depth=depth + 1,
                max_depth=max_depth,
                out=out,
            )
        return


def _money_score(rec: dict[str, Any]) -> int:
    p = str(rec.get("path") or "").lower()
    u = str(rec.get("url") or "").lower()
    score = 0
    if "amount" in p:
        score += 60
    if "grossprice" in p or "netprice" in p:
        score += 50
    if p.endswith(".total") or p.endswith(".subtotal") or ".total" in p:
        score += 35
    if "checkout/session" in u:
        score += 40
    if "/cart" in u or "carts/" in u:
        score += 30
    if "payment" in u or "directpayment" in u:
        score += 20
    return score


def _money_normalize(rec: dict[str, Any]) -> dict[str, Any]:
    """Normalize monetary record into minor/major units when possible."""
    out = dict(rec)
    cur = out.get("currency")
    cur_u = str(cur).upper() if isinstance(cur, str) and cur else None
    decimals = _CURRENCY_DECIMALS.get(cur_u or "", 2)

    value = out.get("value")
    path = str(out.get("path") or "").lower()

    # Heuristic: integers under 'amount' are usually minor units.
    if isinstance(value, int) and "amount" in path and value >= 0:
        out["unit"] = "minor"
        out["minor"] = value
        out["major"] = round(float(value) / (10**decimals), 6)
        out["decimals"] = decimals
        return out

    if isinstance(value, float):
        out["unit"] = "major"
        out["major"] = float(value)
        return out

    # Keep as-is (unknown semantics).
    return out


def _extract_money_insights(
    *, full_items: list[dict[str, Any]], max_values: int = 8, max_mismatches: int = 3
) -> dict[str, Any] | None:
    """Extract bounded money signals from captured request/response bodies.

    This is designed to surface *high-signal* checkout/price bugs without exporting artifacts
    and running ad-hoc parsing.
    """
    raw: list[dict[str, Any]] = []

    for it in full_items:
        if not isinstance(it, dict):
            continue
        url = it.get("url") if isinstance(it.get("url"), str) else ""
        if not url:
            continue

        req = _json_try_parse(it.get("requestPostData"))
        if req is not None:
            _walk_money_fields(req, url=url, source="requestPostData", out=raw)

        resp = _json_try_parse(it.get("responseBody"))
        if resp is not None:
            _walk_money_fields(resp, url=url, source="responseBody", out=raw)

    if not raw:
        return None

    # Rank + normalize + dedupe.
    raw.sort(key=_money_score, reverse=True)
    picked: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for rec in raw:
        cur = rec.get("currency")
        val = rec.get("value")
        key = (
            str(cur or ""),
            str(val),
            str(rec.get("path") or ""),
            str(rec.get("url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        picked.append(_money_normalize(rec))
        if len(picked) >= max_values:
            break

    # Mismatch detection: compare payment-like `amount` vs cart-like `price` in same currency.
    mismatches: list[dict[str, Any]] = []

    by_currency: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rec in picked:
        cur = rec.get("currency")
        if not isinstance(cur, str) or not cur:
            continue
        kind = _money_kind_from_url(rec.get("url") if isinstance(rec.get("url"), str) else "")
        by_currency.setdefault(cur, {}).setdefault(kind, []).append(rec)

    for cur, groups in by_currency.items():
        pays = groups.get("payment", [])
        carts = groups.get("cart", [])
        if not pays or not carts:
            continue

        pay_maj = [r.get("major") for r in pays if isinstance(r.get("major"), (int, float))]
        cart_maj = [r.get("major") for r in carts if isinstance(r.get("major"), (int, float))]
        if not pay_maj or not cart_maj:
            continue

        p = float(min(pay_maj))
        c = float(max(cart_maj))
        if p <= 0 or c <= 0:
            continue

        ratio = c / p
        # Conservative threshold to avoid noisy false positives.
        if ratio < 1.20:
            continue

        mismatches.append(
            {
                "currency": cur,
                "payment_major": round(p, 6),
                "cart_major": round(c, 6),
                "ratio": round(ratio, 4),
                "hint": "Possible price desync between payment session and cart/pricing API",
            }
        )

    if mismatches:
        mismatches.sort(key=lambda m: float(m.get("ratio") or 0.0), reverse=True)
        mismatches = mismatches[:max_mismatches]

    out: dict[str, Any] = {"values": picked}
    if mismatches:
        out["mismatches"] = mismatches
    return out


def build_net_trace(
    config: BrowserConfig,
    *,
    tab_id: str | None = None,
    cursor: int | None = None,
    since: int | None = None,
    offset: int = 0,
    limit: int = 20,
    include: Any = None,
    exclude: Any = None,
    types_raw: Any = None,
    capture: str = "meta",
    redact: bool = True,
    max_body_bytes: int = 80_000,
    max_total_bytes: int = 600_000,
    store: bool = False,
    export: bool = False,
    overwrite: bool = False,
    name: str | None = None,
    clear: bool = False,
) -> dict[str, Any]:
    """Build a bounded trace payload from Tier-0 "recent completed requests" buffer.

    Notes:
    - By default, only metadata is returned (capture="meta").
    - When capture includes request/response bodies, we need a live CDP session to call:
      - Network.getRequestPostData
      - Network.getResponseBody
      This will reuse an active shared session if one exists.
    """

    tab_id = str(tab_id or session_manager.tab_id or "").strip() or None
    if tab_id is None:
        raise SmartToolError(
            tool="net",
            action="trace",
            reason="No active session tab",
            suggestion="Navigate to a page first, then retry",
        )

    offset = max(0, int(offset))
    limit = max(0, min(int(limit), 200))

    # Ensure telemetry exists (best-effort) so `_req_done` is populated.
    telemetry = session_manager.get_telemetry(tab_id)
    if telemetry is None:
        with suppress(Exception), get_session(config, ensure_diagnostics=False) as (sess, _t):
            session_manager.ensure_telemetry(sess)
        telemetry = session_manager.get_telemetry(tab_id)

    done = getattr(telemetry, "_req_done", None) if telemetry is not None else None
    if not isinstance(done, dict):
        raise SmartToolError(
            tool="net",
            action="trace",
            reason="Tier-0 trace buffer not available for this tab",
            suggestion="Ensure MCP_TIER0=1 (default) and retry; if it still fails, navigate() to a normal http(s) page first",
        )

    include_pats = [p.lower() for p in _to_str_list(include)]
    exclude_pats = [p.lower() for p in _to_str_list(exclude)]

    types = set(_to_str_list(types_raw))
    # Defaults: keep signal cheap. If no explicit include/types, prefer XHR/Fetch.
    if not include_pats and not types:
        types = {"XHR", "Fetch"}

    capture = str(capture or "meta").strip().lower()
    capture_request = capture in {"request", "req", "post", "postdata", "all", "full"}
    capture_body = capture in {"body", "responsebody", "response_body", "all", "full"}

    max_body_bytes = _to_int_default(max_body_bytes, default=80_000, min_v=0, max_v=2_000_000)
    max_total_bytes = _to_int_default(max_total_bytes, default=600_000, min_v=0, max_v=10_000_000)

    # Iterate newest-first (dict preserves insertion order in Py3.7+).
    done_items = list(done.items())
    done_items.reverse()

    matched: list[dict[str, Any]] = []
    matched_ids: list[str] = []
    total = 0
    off = int(offset or 0)

    for req_id, meta in done_items:
        if not isinstance(req_id, str) or not req_id:
            continue
        if not isinstance(meta, dict):
            continue

        end_ts = meta.get("endTs")
        if not isinstance(end_ts, int):
            end_ts = meta.get("ts") if isinstance(meta.get("ts"), int) else None
        if since is not None and isinstance(end_ts, int) and end_ts <= since:
            continue

        rtype = meta.get("type")
        if types and (not isinstance(rtype, str) or rtype not in types):
            continue

        url_full = meta.get("urlFull")
        if not isinstance(url_full, str) or not url_full:
            url_full = meta.get("url") if isinstance(meta.get("url"), str) else ""
        u_l = url_full.lower() if isinstance(url_full, str) else ""

        if include_pats and not any(p in u_l for p in include_pats):
            continue
        if exclude_pats and any(p in u_l for p in exclude_pats):
            continue

        total += 1
        if off > 0:
            off -= 1
            continue

        rec: dict[str, Any] = {
            "requestId": req_id,
            "ts": meta.get("endTs") if isinstance(meta.get("endTs"), int) else meta.get("ts"),
            "url": meta.get("url") if isinstance(meta.get("url"), str) else "",
            # Keep the full URL for artifacts only; do not expose in tool output by default.
            "method": meta.get("method"),
            "type": rtype,
            "status": meta.get("status"),
            "ok": meta.get("ok"),
            "durationMs": meta.get("durationMs"),
            "encodedDataLength": meta.get("encodedDataLength"),
            "mimeType": meta.get("mimeType"),
            "contentType": meta.get("contentType"),
            **({"errorText": meta.get("errorText")} if isinstance(meta.get("errorText"), str) else {}),
            **({"blockedReason": meta.get("blockedReason")} if isinstance(meta.get("blockedReason"), str) else {}),
        }

        matched.append(rec)
        matched_ids.append(req_id)
        if limit and len(matched) >= limit:
            break

    out: dict[str, Any] = {
        "trace": {
            **({"cursor": cursor} if isinstance(cursor, int) else {}),
            "total": total,
            "offset": offset,
            "limit": limit,
            "include": include_pats,
            "exclude": exclude_pats,
            "types": sorted(types) if types else [],
            "capture": capture,
            "summary": _summarize_trace(matched=matched, done=done),
            "items": matched,
        }
    }

    # Artifact items: keep higher-fidelity metadata (incl. urlFull + headers/initiator)
    # without expanding the tool output. This is safe (redacted) and very useful for debug.
    artifact_items: list[dict[str, Any]] = []
    for rec in matched:
        rid = rec.get("requestId")
        meta = done.get(rid) if isinstance(rid, str) else None
        item = dict(rec)
        if isinstance(meta, dict):
            url_full = meta.get("urlFull")
            if isinstance(url_full, str) and url_full:
                item["urlFull"] = url_full
            req_headers = meta.get("reqHeaders")
            if isinstance(req_headers, dict) and req_headers:
                item["reqHeaders"] = req_headers
            resp_headers = meta.get("respHeaders")
            if isinstance(resp_headers, dict) and resp_headers:
                item["respHeaders"] = resp_headers
            initiator = meta.get("initiator")
            if isinstance(initiator, dict) and initiator:
                item["initiator"] = initiator
        artifact_items.append(item)

    # Optionally enrich with request/response bodies (best-effort).
    full_items: list[dict[str, Any]] | None = None
    if (capture_request or capture_body) and matched_ids:

        def _enrich(sess: Any) -> None:
            nonlocal full_items
            full_items = []
            # Copy base metadata and add urlFull to the artifact.
            for rec in matched:
                rid = rec.get("requestId")
                meta = done.get(rid) if isinstance(rid, str) else None
                url_full = (
                    meta.get("urlFull") if isinstance(meta, dict) and isinstance(meta.get("urlFull"), str) else None
                )
                item = dict(rec)
                if isinstance(url_full, str) and url_full:
                    item["urlFull"] = url_full
                if isinstance(meta, dict):
                    req_headers = meta.get("reqHeaders")
                    if isinstance(req_headers, dict) and req_headers:
                        item["reqHeaders"] = req_headers
                    resp_headers = meta.get("respHeaders")
                    if isinstance(resp_headers, dict) and resp_headers:
                        item["respHeaders"] = resp_headers
                    initiator = meta.get("initiator")
                    if isinstance(initiator, dict) and initiator:
                        item["initiator"] = initiator
                full_items.append(item)

            bytes_budget = int(max_total_bytes or 0)

            if capture_request:
                cmds = [{"method": "Network.getRequestPostData", "params": {"requestId": rid}} for rid in matched_ids]
                res = sess.send_many(cmds, stop_on_error=False)
                for i, r in enumerate(res):
                    if i >= len(full_items):
                        break
                    if not isinstance(r, dict):
                        continue
                    if r.get("ok") is False and isinstance(r.get("error"), str):
                        full_items[i]["requestPostDataError"] = r.get("error")
                        continue
                    post = r.get("postData")
                    if not isinstance(post, str) or not post:
                        continue
                    if bytes_budget > 0:
                        post = post[: min(len(post), bytes_budget)]
                    if redact:
                        post = redact_text_content(post)
                    full_items[i]["requestPostData"] = post
                    if bytes_budget > 0:
                        bytes_budget = max(0, bytes_budget - len(post))

            if capture_body and (bytes_budget > 0 or max_total_bytes == 0):
                cmds = [{"method": "Network.getResponseBody", "params": {"requestId": rid}} for rid in matched_ids]
                res = sess.send_many(cmds, stop_on_error=False)
                for i, r in enumerate(res):
                    if i >= len(full_items):
                        break
                    if not isinstance(r, dict):
                        continue
                    if r.get("ok") is False and isinstance(r.get("error"), str):
                        full_items[i]["responseBodyError"] = r.get("error")
                        continue
                    body = r.get("body")
                    base64_encoded = r.get("base64Encoded") is True
                    if not isinstance(body, str) or not body:
                        continue

                    raw_bytes: bytes
                    if base64_encoded:
                        try:
                            raw_bytes = base64.b64decode(body.encode("utf-8"), validate=False)
                        except Exception:
                            full_items[i]["responseBodyError"] = "base64 decode failed"
                            continue
                    else:
                        raw_bytes = body.encode("utf-8", errors="replace")

                    if max_body_bytes and len(raw_bytes) > max_body_bytes:
                        raw_bytes = raw_bytes[:max_body_bytes]
                        full_items[i]["responseBodyTruncated"] = True

                    if bytes_budget > 0 and len(raw_bytes) > bytes_budget:
                        raw_bytes = raw_bytes[:bytes_budget]
                        full_items[i]["responseBodyTruncated"] = True

                    if base64_encoded:
                        # Keep bytes as base64 to preserve binary safety.
                        out_b64 = base64.b64encode(raw_bytes).decode("ascii")
                        full_items[i]["responseBodyBase64"] = out_b64
                        full_items[i]["responseBodyBase64Bytes"] = len(raw_bytes)
                        if bytes_budget > 0:
                            bytes_budget = max(0, bytes_budget - len(raw_bytes))
                        continue

                    text = raw_bytes.decode("utf-8", errors="replace")
                    if redact:
                        text = redact_text_content(text)
                    full_items[i]["responseBody"] = text
                    if bytes_budget > 0:
                        bytes_budget = max(0, bytes_budget - len(text))

        active = session_manager.get_active_shared_session()
        if active:
            sess, _t = active
            with suppress(Exception):
                sess.enable_network()
            try:
                _enrich(sess)
            except Exception as e:
                out["trace"]["bodyCapture"] = {"available": False, "reason": str(e)}
        else:
            # Best-effort: open a short-lived session only when explicitly asked for bodies.
            try:
                with get_session(config, ensure_diagnostics=False) as (sess, _t):
                    with suppress(Exception):
                        sess.enable_network()
                    _enrich(sess)
            except Exception as e:
                out["trace"]["bodyCapture"] = {"available": False, "reason": str(e)}

    # When bodies were requested and successfully captured, include a tiny preview to keep bug-hunts
    # cognitively cheap (the full payload stays artifact-backed).
    if isinstance(full_items, list) and full_items:
        out["trace"]["preview"] = _body_preview(full_items=full_items, max_items=3, max_chars=1800)
        money = _extract_money_insights(full_items=full_items)
        if isinstance(money, dict) and money:
            out["trace"]["money"] = money

    # Store full fidelity trace as an artifact (recommended for agent drilldown).
    if store or export:
        trace_obj = {
            "action": "trace",
            "cursor": cursor,
            **({"since": since} if since is not None else {}),
            "generatedAtMs": int(time.time() * 1000),
            "filters": {
                "include": include_pats,
                "exclude": exclude_pats,
                "types": sorted(types) if types else [],
                "capture": capture,
                "redact": bool(redact),
                "maxBodyBytes": int(max_body_bytes),
                "maxTotalBytes": int(max_total_bytes),
            },
            "items": full_items if isinstance(full_items, list) else artifact_items,
        }
        try:
            ref = artifact_store.put_json(
                kind="net_trace",
                obj=trace_obj,
                metadata={
                    "total": int(out["trace"]["total"]),
                    "offset": int(offset),
                    "limit": int(limit),
                    **({"since": since} if since is not None else {}),
                    "capture": capture,
                    "redact": bool(redact),
                },
            )
            out["artifact"] = {
                "id": ref.id,
                "kind": ref.kind,
                "mimeType": ref.mime_type,
                "bytes": ref.bytes,
                "createdAt": ref.created_at,
            }
            out["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]

            if export:
                export_res = artifact_store.export(
                    artifact_id=ref.id,
                    name=str(name) if isinstance(name, str) and name.strip() else None,
                    overwrite=bool(overwrite),
                )
                if isinstance(export_res, dict) and isinstance(export_res.get("export"), dict):
                    out["export"] = export_res.get("export")
        except Exception:
            # Artifact storage is optional; never fail the core trace response.
            pass

    if clear:
        with suppress(Exception):
            session_manager.clear_net_trace(tab_id)
        out["cleared"] = True

    return out
