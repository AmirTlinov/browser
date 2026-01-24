"""Auto-scroll helper for page analysis/extraction."""

from __future__ import annotations

import time
from typing import Any

from ...config import BrowserConfig
from ..base import get_session

DEFAULT_MAX_ITERS = 8
MAX_MAX_ITERS = 50
DEFAULT_AMOUNT = 700
DEFAULT_SETTLE_MS = 150
DEFAULT_SCROLL_END_JS = (
    "(() => {"
    "  const el = document.scrollingElement || document.documentElement;"
    "  const bottom = (el.scrollTop + window.innerHeight);"
    "  return bottom >= (el.scrollHeight - 2);"
    "})()"
)


def auto_scroll_page(config: BrowserConfig, spec: dict[str, Any]) -> dict[str, Any]:
    """Best-effort auto-scroll before page analysis."""
    if not isinstance(spec, dict):
        return {
            "ok": False,
            "error": "auto_scroll must be an object",
            "suggestion": "Use auto_scroll=true or auto_scroll={...}",
        }

    try:
        max_iters = int(spec.get("max_iters", DEFAULT_MAX_ITERS))
    except Exception:
        max_iters = DEFAULT_MAX_ITERS
    max_iters = max(1, min(max_iters, MAX_MAX_ITERS))

    direction = str(spec.get("direction", "down") or "down").strip().lower()
    if direction not in {"down", "up", "left", "right"}:
        return {
            "ok": False,
            "error": "Invalid auto_scroll direction",
            "details": {"direction": direction},
            "suggestion": "Use direction in {down, up, left, right}",
        }

    try:
        amount = int(spec.get("amount", DEFAULT_AMOUNT))
    except Exception:
        amount = DEFAULT_AMOUNT
    amount = max(1, min(amount, 5000))

    try:
        settle_ms = int(spec.get("settle_ms", DEFAULT_SETTLE_MS))
    except Exception:
        settle_ms = DEFAULT_SETTLE_MS
    settle_ms = max(0, min(settle_ms, 5000))

    until_js = spec.get("until_js") if isinstance(spec.get("until_js"), str) else None
    until_js = until_js.strip() if isinstance(until_js, str) else ""
    if not until_js:
        until_js = DEFAULT_SCROLL_END_JS

    def _check_done(session) -> tuple[bool, str | None]:
        try:
            res = session.eval_js(until_js)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return bool(res), None

    dx, dy = 0, 0
    if direction == "down":
        dy = amount
    elif direction == "up":
        dy = -amount
    elif direction == "right":
        dx = amount
    elif direction == "left":
        dx = -amount

    with get_session(config) as (session, _target):
        done = False
        iters = 0
        for i in range(max_iters):
            iters = i
            done, err = _check_done(session)
            if err:
                return {
                    "ok": False,
                    "error": "Auto-scroll JS failed",
                    "details": {"error": err},
                    "suggestion": "Handle dialogs or provide a simpler until_js expression",
                }
            if done:
                break

            try:
                session.scroll(dx, dy, 100, 100)
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "error": "Auto-scroll failed",
                    "details": {"error": str(exc)},
                    "suggestion": "Ensure the page is scrollable or adjust amount",
                }

            if settle_ms > 0:
                time.sleep(float(settle_ms) / 1000.0)

        if not done:
            done, err = _check_done(session)
            if err:
                return {
                    "ok": False,
                    "error": "Auto-scroll JS failed",
                    "details": {"error": err},
                    "suggestion": "Handle dialogs or provide a simpler until_js expression",
                }

    return {
        "ok": True,
        "done": bool(done),
        "iters": int(iters),
        "max_iters": int(max_iters),
        "direction": direction,
        "amount": int(amount),
        "settle_ms": int(settle_ms),
    }
