from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderBudget:
    max_chars: int = 4000
    max_depth: int = 4
    max_list_items: int = 8
    max_str_chars: int = 600


_PRIORITY_KEYS: tuple[str, ...] = (
    # Common success/error markers
    "ok",
    "success",
    "isError",
    "error",
    "tool",
    # High-signal human-readable summary (flow/run step notes)
    "note",
    "action",
    "reason",
    "suggestion",
    # Common browser context
    "url",
    "title",
    "status",
    "statusText",
    "target",
    "sessionTabId",
    "cursor",
    "since",
    # Common wait/locators
    "found",
    "timeout",
    "waited",
    "waited_for",
)


def render_ctx_markdown(data: Any, *, budget: RenderBudget | None = None) -> str:
    """
    Render tool output as AI-first context-format Markdown (not JSON).

    Design:
    - Summary-first, stable, compact.
    - Truncates long strings and large collections.
    - Deterministic ordering for top-level keys.
    """
    budget = budget or RenderBudget()

    content_lines: list[str] = []
    state = _RenderState(max_chars=budget.max_chars)
    _render_any(data, content_lines, state=state, depth=0, budget=budget)

    legend = ""
    content = "\n".join(content_lines).rstrip()

    # Hard cap (last line defense).
    if legend.strip():
        out = f"[LEGEND]\n{legend.rstrip()}\n\n[CONTENT]\n{content}\n"
    else:
        # Avoid emitting an empty [LEGEND] block (noise).
        out = f"[CONTENT]\n{content}\n"
    if len(out) > budget.max_chars:
        out = out[: budget.max_chars].rstrip() + "\n… <TRUNCATED>\n"
    return out


def render_ctx_text(text: str, *, budget: RenderBudget | None = None) -> str:
    """Wrap a plain text payload into context-format Markdown."""
    budget = budget or RenderBudget()
    cleaned = (text or "").rstrip()
    # Avoid emitting an empty [LEGEND] block (noise).
    out = f"[CONTENT]\n{cleaned}\n"
    if len(out) > budget.max_chars:
        out = out[: budget.max_chars].rstrip() + "\n… <TRUNCATED>\n"
    return out


@dataclass
class _RenderState:
    max_chars: int
    used_chars: int = 0
    truncated: bool = False


def _push_line(lines: list[str], line: str, *, state: _RenderState) -> None:
    if state.truncated:
        return

    # Include newline char in budget accounting.
    needed = len(line) + 1
    if state.used_chars + needed > state.max_chars:
        state.truncated = True
        return
    lines.append(line)
    state.used_chars += needed


def _format_scalar(value: Any, *, budget: RenderBudget) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        s = value.replace("\r\n", "\n").replace("\r", "\n")
        # Keep single-line by default.
        if "\n" in s:
            first, _rest = s.split("\n", 1)
            s = first + " …"
        if len(s) > budget.max_str_chars:
            s = s[: budget.max_str_chars].rstrip() + "…"
        return s
    return str(value)


def _sorted_keys(d: dict[Any, Any]) -> list[Any]:
    """Deterministic key ordering that tolerates non-string keys.

    Some tool payloads naturally use numeric keys (e.g., grid maps). Rendering must never
    crash due to mixed key types.
    """
    keys = list(d.keys())

    def key_rank(k: Any) -> tuple[int, int, str]:
        idx = 10_000
        if isinstance(k, str):
            try:
                idx = _PRIORITY_KEYS.index(k)
            except ValueError:
                idx = 10_000
            return (idx, 0, k)
        # Non-string keys: keep stable ordering by type + stringified value.
        return (idx, 1, str(k))

    return sorted(keys, key=key_rank)


def _render_any(value: Any, lines: list[str], *, state: _RenderState, depth: int, budget: RenderBudget) -> None:
    if state.truncated:
        return

    if depth > budget.max_depth:
        _push_line(lines, "… <TRUNCATED depth>", state=state)
        return

    if isinstance(value, dict):
        _render_dict(value, lines, state=state, depth=depth, budget=budget)
        return

    if isinstance(value, list):
        _render_list(value, lines, state=state, depth=depth, budget=budget)
        return

    _push_line(lines, _format_scalar(value, budget=budget), state=state)


def _render_dict(d: dict[Any, Any], lines: list[str], *, state: _RenderState, depth: int, budget: RenderBudget) -> None:
    indent = "  " * depth
    for key in _sorted_keys(d):
        if state.truncated:
            return
        val = d[key]

        if isinstance(val, (dict, list)):
            # Header line
            if isinstance(val, list):
                _push_line(lines, f"{indent}{key}: [len={len(val)}]", state=state)
            else:
                _push_line(lines, f"{indent}{key}:", state=state)
            _render_any(val, lines, state=state, depth=depth + 1, budget=budget)
            continue

        _push_line(lines, f"{indent}{key}: {_format_scalar(val, budget=budget)}", state=state)


def _render_list(items: list[Any], lines: list[str], *, state: _RenderState, depth: int, budget: RenderBudget) -> None:
    indent = "  " * depth
    limit = min(len(items), budget.max_list_items)
    for i in range(limit):
        if state.truncated:
            return
        item = items[i]
        if isinstance(item, dict):
            # Attempt a one-line preview.
            preview_bits: list[str] = []
            for k in _sorted_keys(item)[:3]:
                v = item.get(k)
                if isinstance(v, (dict, list)):
                    continue
                preview_bits.append(f"{k}={_format_scalar(v, budget=budget)}")
            preview = " ".join(preview_bits) if preview_bits else f"dict(keys={len(item)})"
            _push_line(lines, f"{indent}- {preview}", state=state)
        elif isinstance(item, list):
            _push_line(lines, f"{indent}- [list len={len(item)}]", state=state)
        else:
            _push_line(lines, f"{indent}- {_format_scalar(item, budget=budget)}", state=state)

    if len(items) > limit and not state.truncated:
        _push_line(lines, f"{indent}- … <TRUNCATED list len={len(items)}>", state=state)
