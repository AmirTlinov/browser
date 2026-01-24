"""Redaction utilities for logging and frame-dumps.

This module intentionally prefers safety over perfect fidelity: by default it
removes obvious secrets and large payloads (e.g. screenshots) from logs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..sensitivity import is_sensitive_key

_SENSITIVE_KEYS = {
    "secret",
    "password",
    "pass",
    "pwd",
    "token",
    "auth",
    "authorization",
    "cookie",
    "set-cookie",
    "api-key",
    "x-api-key",
    "x-auth-token",
}


_URL_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{\s*(?:mem:|param:)?[A-Za-z0-9_.-]+\s*\}\}|\$\{\s*(?:mem:|param:)?[A-Za-z0-9_.-]+\s*\})"
)


def _is_placeholder_value(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return _URL_PLACEHOLDER_RE.search(value) is not None


def _should_redact_url_key(key: str) -> bool:
    lk = (key or "").strip().lower()
    if not lk:
        return False
    if lk in _SENSITIVE_KEYS:
        return True
    return is_sensitive_key(lk)


def _looks_like_query_string(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return "=" in value and ("&" in value or value.count("=") >= 1)


def redact_url(url: str) -> str:
    """Redact suspicious URL parameters without destroying normal queries.

    - Keeps non-sensitive query params intact (e.g., q=search, filters).
    - Redacts values for keys like token/auth/secret/api-key (key-based heuristic).
    - Preserves placeholders ({{mem:...}} / {{param:...}}) as-is.
    - Sanitizes fragment when it looks like a query string (OAuth-style).
    - Removes userinfo (`user:pass@host`) from netloc.

    Returns the original URL unchanged when no redaction is needed (avoids churn).
    """
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    changed = False
    scheme = parts.scheme
    netloc = parts.netloc
    path = parts.path
    query = parts.query
    fragment = parts.fragment

    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
        changed = True

    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        redacted_any = False
        out_pairs: list[tuple[str, str]] = []
        for k, v in pairs:
            if _should_redact_url_key(k) and isinstance(v, str) and v and not _is_placeholder_value(v):
                out_pairs.append((k, "<redacted>"))
                redacted_any = True
            else:
                out_pairs.append((k, v))
        if redacted_any:
            query = urlencode(out_pairs, doseq=True)
            changed = True

    if fragment and _looks_like_query_string(fragment):
        pairs = parse_qsl(fragment, keep_blank_values=True)
        redacted_any = False
        out_pairs: list[tuple[str, str]] = []
        for k, v in pairs:
            if _should_redact_url_key(k) and isinstance(v, str) and v and not _is_placeholder_value(v):
                out_pairs.append((k, "<redacted>"))
                redacted_any = True
            else:
                out_pairs.append((k, v))
        if redacted_any:
            fragment = urlencode(out_pairs, doseq=True)
            changed = True

    if not changed:
        return url

    try:
        return urlunsplit((scheme, netloc, path, query, fragment))
    except Exception:
        return url


def redact_url_brief(url: str) -> str:
    """Low-noise URL redaction (drops query+fragment; removes userinfo)."""
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
        netloc = parts.netloc.split("@", 1)[1] if "@" in parts.netloc else parts.netloc
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return url


def _redacted_summary(value: Any) -> str:
    if value is None:
        return "<redacted>"
    if isinstance(value, (bytes, bytearray)):
        return f"<redacted bytes len={len(value)}>"
    if isinstance(value, str):
        return f"<redacted str len={len(value)}>"
    if isinstance(value, (list, tuple, set)):
        return f"<redacted list len={len(value)}>"
    if isinstance(value, dict):
        return f"<redacted dict keys={len(value)}>"
    return "<redacted>"


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (headers or {}).items():
        lk = str(k).lower()
        if lk in _SENSITIVE_KEYS or lk.startswith("authorization") or lk.startswith("cookie"):
            out[k] = _redacted_summary(v)
        else:
            out[k] = v
    return out


def redact_tool_arguments(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Redact tool arguments for safe logging."""
    return _redact_any(args, tool=tool, key=None)


def redact_jsonrpc_for_dump(payload: dict[str, Any], *, max_text_chars: int | None = None) -> dict[str, Any]:
    """Redact a JSON-RPC message for file dumps.

    Notes:
    - Tool call args are redacted based on tool name.
    - Image content is replaced with a short placeholder.
    - Large text blobs can be truncated.
    """
    max_text_chars = max_text_chars if max_text_chars is not None else _dump_max_chars()
    msg = _copy_shallow(payload)

    method = msg.get("method")
    if method in {"tools/call", "call_tool"}:
        params = msg.get("params")
        if isinstance(params, dict):
            name = params.get("name")
            args = params.get("arguments") or params.get("args")
            if isinstance(name, str) and isinstance(args, dict):
                params = dict(params)
                params["arguments"] = redact_tool_arguments(name, args)
                params.pop("args", None)
                msg["params"] = params

    result = msg.get("result")
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        redacted_content = []
        for item in result["content"]:
            if not isinstance(item, dict):
                redacted_content.append(item)
                continue
            it = dict(item)
            if it.get("type") == "image" and isinstance(it.get("data"), str):
                it["data"] = f"<omitted image base64 len={len(it['data'])}>"
            if it.get("type") == "text" and isinstance(it.get("text"), str):
                it["text"] = redact_text_content(it["text"])
                if max_text_chars is not None and len(it["text"]) > max_text_chars:
                    it["text"] = it["text"][:max_text_chars] + f"… <truncated len={len(item['text'])}>"
            redacted_content.append(it)

        result = dict(result)
        result["content"] = redacted_content
        msg["result"] = result

    return msg


def redact_jsonrpc_for_log(payload: dict[str, Any]) -> dict[str, Any]:
    """Stricter redaction for logs (shorter + safer)."""
    return redact_jsonrpc_for_dump(payload, max_text_chars=512)


def redact_text_content(text: str) -> str:
    """Redact sensitive fields inside JSON text payloads (best-effort)."""
    try:
        obj = json.loads(text)
    except Exception:
        return _redact_plain_text(text)

    redacted = _redact_output_json(obj)
    try:
        return json.dumps(redacted, ensure_ascii=False)
    except Exception:
        return text


def _dump_max_chars() -> int:
    raw = os.environ.get("MCP_DUMP_FRAMES_MAX_CHARS", "5000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 5000


def _copy_shallow(obj: dict[str, Any]) -> dict[str, Any]:
    return dict(obj) if isinstance(obj, dict) else {}


def _redact_any(value: Any, *, tool: str, key: str | None) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[k] = _redact_any(v, tool=tool, key=str(k))
        return out

    if isinstance(value, list):
        return [_redact_any(v, tool=tool, key=key) for v in value]

    if isinstance(value, str) and key and key.lower() == "url":
        return redact_url(value)

    lk = (key or "").lower()

    # Tool-specific redactions
    if tool in {"type"} and lk == "text":
        return _redacted_summary(value)
    if tool in {"fetch", "http"} and lk in {"body"}:
        return _redacted_summary(value)
    if tool in {"fetch", "http"} and lk in {"headers"} and isinstance(value, dict):
        return redact_headers(value)
    if tool in {"form"} and lk == "fill" and isinstance(value, dict):
        return {k: _redacted_summary(v) for k, v in value.items()}
    if tool in {"cookies"} and lk in {"value", "cookies"}:
        return _redacted_summary(value)
    if tool in {"totp"} and lk == "secret":
        return _redacted_summary(value)
    if tool in {"storage"} and lk in {"value"}:
        return _redacted_summary(value)
    if tool in {"storage"} and lk in {"items"} and isinstance(value, dict):
        return {k: _redacted_summary(v) for k, v in value.items()}

    # Generic redactions
    if lk in _SENSITIVE_KEYS:
        return _redacted_summary(value)

    return value


def _redact_output_json(value: Any) -> Any:
    """Redact common sensitive fields in tool outputs.

    This is used for frame dumps and trace logs (not for tool responses).
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            lk = str(k).lower()

            if lk == "headers" and isinstance(v, dict):
                out[k] = redact_headers(v)
                continue

            if lk == "body":
                out[k] = _redacted_summary(v)
                continue

            if lk == "cookies" and isinstance(v, list):
                cookies_out = []
                for c in v:
                    if isinstance(c, dict) and "value" in c:
                        c2 = dict(c)
                        c2["value"] = _redacted_summary(c2.get("value"))
                        cookies_out.append(c2)
                    else:
                        cookies_out.append(c)
                out[k] = cookies_out
                continue

            if lk in {"secret", "token", "authorization", "cookie"}:
                out[k] = _redacted_summary(v)
                continue

            if lk == "code" and isinstance(v, str) and v.isdigit() and 4 <= len(v) <= 12:
                out[k] = _redacted_summary(v)
                continue

            out[k] = _redact_output_json(v)
        return out

    if isinstance(value, list):
        return [_redact_output_json(v) for v in value]

    return value


def _redact_plain_text(text: str) -> str:
    """Best-effort redaction for non-JSON text payloads (e.g. context-format markdown).

    This is used for frame dumps and trace logs (not for tool responses).
    """
    try:
        lines = (text or "").splitlines()
    except Exception:
        return text

    out_lines: list[str] = []
    for raw in lines:
        line = raw
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if stripped in {"[LEGEND]", "[CONTENT]"}:
            out_lines.append(line)
            continue

        # Key-value redaction (works for "key: value" and "key = value").
        sep = None
        if ":" in line:
            sep = ":"
        elif "=" in line:
            sep = "="

        if not sep:
            out_lines.append(line)
            continue

        left, right = line.split(sep, 1)
        key = left.strip().lower()
        if (
            key in _SENSITIVE_KEYS
            or key.startswith("authorization")
            or key.startswith("cookie")
            or key.startswith("set-cookie")
        ):
            out_lines.append(f"{left}{sep} {_redacted_summary(right.strip())}")
            continue

        # Special-case numeric 2FA codes.
        if key == "code":
            v = right.strip()
            if v.isdigit() and 4 <= len(v) <= 12:
                out_lines.append(f"{left}{sep} {_redacted_summary(v)}")
                continue

        out_lines.append(line)

    return "\n".join(out_lines)
