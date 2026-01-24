"""Deterministic template parameter interpolation for run macros.

This is intentionally separate from `server/registry.py` flow vars interpolation:
- Parameters are applied during macro expansion (before steps enter the flow engine).
- Syntax is distinct to avoid collisions with flow vars (`{{var}}`) and memory vars (`{{mem:key}}`).

Supported placeholders:
- Exact: `{{param:key}}` or `${param:key}` => preserves scalar type
- Inline: `... {{param:key}} ...` => stringifies

The `note` channel is used to avoid leaking sensitive values in macro plans.
"""

from __future__ import annotations

import re
from typing import Any

_PARAM_INLINE_RE = re.compile(
    r"(?:\{\{\s*param:([A-Za-z0-9_.-]+)\s*\}\}|\$\{\s*param:([A-Za-z0-9_.-]+)\s*\})"
)
_PARAM_EXACT_RE = re.compile(
    r"^\s*(?:\{\{\s*param:([A-Za-z0-9_.-]+)\s*\}\}|\$\{\s*param:([A-Za-z0-9_.-]+)\s*\})\s*$"
)


class ParamMissing(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = str(key or "").strip()


def params_hint(params: dict[str, Any], *, limit: int = 20) -> list[str]:
    keys = [k for k in params if isinstance(k, str) and k.strip()]
    keys.sort()
    return keys[: max(0, int(limit))]


def interpolate_params_pair(value: Any, params: dict[str, Any]) -> tuple[Any, Any]:
    """Return (actual, note) values.

    - actual: real substituted values
    - note: same structure but with {{param:key}} replaced by <param:key>
    """
    if isinstance(value, str):
        m = _PARAM_EXACT_RE.match(value)
        if m:
            key = m.group(1) or m.group(2) or ""
            key = key.strip()
            if key not in params:
                raise ParamMissing(key)
            return params.get(key), f"<param:{key}>"

        if "{{param:" not in value and "${param:" not in value:
            return value, value

        def _repl_actual(match: re.Match[str]) -> str:
            key = (match.group(1) or match.group(2) or "").strip()
            if key not in params:
                raise ParamMissing(key)
            v = params.get(key)
            return "" if v is None else str(v)

        def _repl_note(match: re.Match[str]) -> str:
            key = (match.group(1) or match.group(2) or "").strip()
            if key not in params:
                raise ParamMissing(key)
            return f"<param:{key}>"

        return _PARAM_INLINE_RE.sub(_repl_actual, value), _PARAM_INLINE_RE.sub(_repl_note, value)

    if isinstance(value, dict):
        out_actual: dict[str, Any] = {}
        out_note: dict[str, Any] = {}
        for k, v in value.items():
            a, n = interpolate_params_pair(v, params)
            out_actual[str(k)] = a
            out_note[str(k)] = n
        return out_actual, out_note

    if isinstance(value, list):
        actual_items: list[Any] = []
        note_items: list[Any] = []
        for v in value:
            a, n = interpolate_params_pair(v, params)
            actual_items.append(a)
            note_items.append(n)
        return actual_items, note_items

    return value, value

