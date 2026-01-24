"""Runbook helpers (agent memory step lists).

Runbooks are JSON step arrays stored in agent memory and later executed via run/flow.
This module provides safe-by-default sanitation for recording and previewing runbooks
without destroying placeholder-based workflows ({{mem:...}} / {{param:...}} / {{var}}).
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .sensitivity import is_sensitive_key

_SENSITIVE_KEYS = {
    "secret",
    "password",
    "pass",
    "pwd",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
    "api-key",
    "x-api-key",
    "x-auth-token",
}

_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{\s*(?:mem:|param:)?[A-Za-z0-9_.-]+\s*\}\}|\$\{\s*(?:mem:|param:)?[A-Za-z0-9_.-]+\s*\})"
)


def sanitize_runbook_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Return (sanitized_steps, redacted_count).

    - Keeps placeholder strings intact ({{mem:...}}, {{param:...}}, {{var}}).
    - Redacts obvious sensitive literals in tool-specific locations.
    """
    src = [s for s in steps if isinstance(s, dict)]
    out: list[dict[str, Any]] = []
    redacted = 0
    for st in src:
        sanitized_step, n = _sanitize_step(st)
        redacted += int(n)
        out.append(sanitized_step)
    return out, redacted


def has_sensitive_literals(steps: list[dict[str, Any]]) -> bool:
    """True if sanitization would redact anything."""
    _san, n = sanitize_runbook_steps(steps)
    return n > 0


def preview_runbook_steps(
    steps: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    sanitized, redacted = sanitize_runbook_steps(steps)
    limit_i = max(0, min(int(limit), 20))
    preview = sanitized[:limit_i]
    return {
        "steps_total": len(steps),
        "steps_preview": preview,
        **({"redacted": int(redacted)} if redacted else {}),
    }


def _is_placeholder(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return _PLACEHOLDER_RE.search(value) is not None


def _redact_value(value: Any) -> Any:
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


def _sanitize_headers(headers: dict[str, Any]) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    redacted = 0
    for k, v in headers.items():
        lk = str(k).lower()
        if lk in _SENSITIVE_KEYS or lk.startswith("authorization") or lk.startswith("cookie"):
            if isinstance(v, str) and _is_placeholder(v):
                out[k] = v
            else:
                out[k] = _redact_value(v)
                redacted += 1
        else:
            out[k] = v
    return out, redacted


def _sanitize_any(value: Any, *, tool: str, key: str | None) -> tuple[Any, int]:
    # Containers first.
    if isinstance(value, dict):
        # Special-case: browser memory set can embed secrets as literals:
        # {"browser": {"action":"memory","memory_action":"set","key":"token","value":"..."}}
        sensitive_memory_set = False
        if tool == "browser" and key is None:
            try:
                action = str(value.get("action") or "").strip().lower()
                mem_action = str(value.get("memory_action") or "").strip().lower()
            except Exception:
                action = ""
                mem_action = ""
            mem_key = value.get("key")
            sensitive_memory_set = (
                action == "memory"
                and mem_action == "set"
                and isinstance(mem_key, str)
                and is_sensitive_key(mem_key)
            )

        out: dict[str, Any] = {}
        redacted = 0
        for k, v in value.items():
            if sensitive_memory_set and str(k).lower() == "value":
                if isinstance(v, str) and _is_placeholder(v):
                    out[k] = v
                else:
                    out[k] = _redact_value(v)
                    redacted += 1
                continue
            vv, n = _sanitize_any(v, tool=tool, key=str(k))
            out[k] = vv
            redacted += int(n)
        return out, redacted

    if isinstance(value, list):
        out_list: list[Any] = []
        redacted = 0
        for it in value:
            vv, n = _sanitize_any(it, tool=tool, key=key)
            out_list.append(vv)
            redacted += int(n)
        return out_list, redacted

    # Primitive rules (placeholder-aware).
    lk = (key or "").lower()

    if isinstance(value, str) and lk == "url":
        from .server.redaction import redact_url as _redact_url

        red = _redact_url(value)
        if red != value:
            return red, 1
        return value, 0

    if isinstance(value, str) and _is_placeholder(value):
        return value, 0

    # Tool-specific redactions (keep placeholders).
    if tool == "type" and lk == "text":
        return _redact_value(value), 1

    if tool in {"fetch", "http"} and lk == "body":
        return _redact_value(value), 1

    if tool in {"fetch", "http"} and lk == "headers" and isinstance(value, dict):
        return _sanitize_headers(value)

    if tool == "form" and lk == "fill" and isinstance(value, dict):
        out: dict[str, Any] = {}
        redacted = 0
        for fk, fv in value.items():
            if isinstance(fv, str) and _is_placeholder(fv):
                out[fk] = fv
                continue
            out[fk] = _redact_value(fv)
            redacted += 1
        return out, redacted

    if tool == "cookies" and lk in {"value", "cookies"}:
        return _redact_value(value), 1

    if tool == "totp" and lk == "secret":
        return _redact_value(value), 1

    if tool == "storage" and lk == "value":
        return _redact_value(value), 1

    if tool == "storage" and lk == "items" and isinstance(value, dict):
        out: dict[str, Any] = {}
        redacted = 0
        for sk, sv in value.items():
            if isinstance(sv, str) and _is_placeholder(sv):
                out[sk] = sv
                continue
            out[sk] = _redact_value(sv)
            redacted += 1
        return out, redacted

    # Generic sensitive key redaction.
    if lk in _SENSITIVE_KEYS:
        return _redact_value(value), 1

    return value, 0


def _sanitize_step(step: dict[str, Any]) -> tuple[dict[str, Any], int]:
    st = copy.deepcopy(step)
    redacted = 0

    tool: str | None = None
    args: Any = None

    if isinstance(st.get("tool"), str):
        tool = str(st.get("tool"))
        args = st.get("args")
        if isinstance(args, dict):
            sanitized_args, n = _sanitize_any(args, tool=tool, key=None)
            st["args"] = sanitized_args
            redacted += int(n)
        return st, redacted

    # Shorthand: {click:{...}} / {macro:{...}} / {repeat:{...}} etc.
    for k, v in list(st.items()):
        if not isinstance(k, str):
            continue
        if k in {"optional", "label", "export", "irreversible"}:
            continue
        if isinstance(v, dict):
            tool = k
            args = v
            break

    if tool is None or not isinstance(args, dict):
        return st, 0

    sanitized_args, n = _sanitize_any(args, tool=tool, key=None)
    st[tool] = sanitized_args
    redacted += int(n)
    return st, redacted
