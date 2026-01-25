"""Helpers for extract_content retry-on-error logic."""

from __future__ import annotations

import json
from typing import Any

from ... import tools
from ...tools.base import SmartToolError

DEFAULT_ERROR_TEXTS = [
    "error while loading",
    "something went wrong",
    "please try again",
    "unable to load",
]


def as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


def build_error_texts_present_js(texts: list[str]) -> str:
    safe = [t.strip().lower() for t in texts if isinstance(t, str) and t.strip()]
    if not safe:
        return "false"
    items = json.dumps(safe)
    return (
        "(() => {"
        f"  const errors = {items};"
        "  const hay = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();"
        "  if (!hay) return false;"
        "  return errors.some((t) => hay.includes(t));"
        "})()"
    )


def error_texts_present(config, texts: list[str]) -> bool:  # noqa: ANN001
    if not texts:
        return False
    js = build_error_texts_present_js(texts)
    try:
        res = tools.eval_js(config, js)
    except SmartToolError:
        return False
    if not isinstance(res, dict):
        return False
    return bool(res.get("result"))


def normalize_retry_scroll(spec: Any) -> tuple[float, float, str | None]:
    direction = "down"
    amount = 400
    container_selector: str | None = None

    if isinstance(spec, dict):
        raw_direction = spec.get("direction")
        if isinstance(raw_direction, str) and raw_direction.strip():
            direction = raw_direction.strip().lower()
        try:
            amount = int(spec.get("amount", amount))
        except Exception:
            amount = 400
        raw_container = spec.get("container_selector")
        if isinstance(raw_container, str) and raw_container.strip():
            container_selector = raw_container.strip()

    if direction not in {"down", "up", "left", "right"}:
        direction = "down"
    amount = max(50, min(amount, 2000))

    delta_x = 0.0
    delta_y = 0.0
    if direction == "down":
        delta_y = float(amount)
    elif direction == "up":
        delta_y = float(-amount)
    elif direction == "right":
        delta_x = float(amount)
    else:
        delta_x = float(-amount)

    return delta_x, delta_y, container_selector
