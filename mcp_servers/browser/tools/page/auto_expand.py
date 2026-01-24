"""Auto-expand helper for page analysis/extraction."""

from __future__ import annotations

import json
import time
from typing import Any

from ...config import BrowserConfig
from ..base import get_session

DEFAULT_EXPAND_PHRASES = [
    "show more",
    "read more",
    "see more",
    "expand",
    "show all",
    "load more",
]
DEFAULT_EXPAND_SELECTORS = "button, [role=button], summary, details"
DEFAULT_CLICK_LIMIT = 6
DEFAULT_MAX_ITERS = 6
MAX_MAX_ITERS = 50
DEFAULT_SETTLE_MS = 150


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for it in value:
            if isinstance(it, str) and it.strip():
                out.append(it.strip())
        return out
    return []


def _build_auto_expand_js(
    *,
    phrases: list[str],
    selectors: str,
    include_links: bool,
    max_clicks: int,
) -> str:
    phrases_json = json.dumps([p.lower() for p in phrases if p.strip()])
    selectors_json = json.dumps(selectors)
    include_links_js = "true" if include_links else "false"
    return (
        "(() => {"
        f"  const phrases = {phrases_json};"
        f"  const selector = {selectors_json};"
        f"  const includeLinks = {include_links_js};"
        f"  const maxClicks = {int(max_clicks)};"
        "  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();"
        "  const matches = (el) => {"
        "    const text = norm(el.textContent || '');"
        "    const aria = norm(el.getAttribute && el.getAttribute('aria-label'));"
        "    const title = norm(el.getAttribute && el.getAttribute('title'));"
        "    const hay = text || aria || title;"
        "    if (!hay) return false;"
        "    return phrases.some((p) => hay.includes(p));"
        "  };"
        "  const isVisible = (el) => {"
        "    if (!el) return false;"
        "    const style = window.getComputedStyle(el);"
        "    if (style && (style.visibility === 'hidden' || style.display === 'none')) return false;"
        "    const rects = el.getClientRects();"
        "    return !!(rects && rects.length);"
        "  };"
        "  const isDisabled = (el) => {"
        "    if (el.disabled) return true;"
        "    const aria = el.getAttribute && el.getAttribute('aria-disabled');"
        "    return aria === 'true';"
        "  };"
        "  const allowLink = (el) => {"
        "    if (el.tagName !== 'A') return true;"
        "    if (!includeLinks) return false;"
        "    const href = (el.getAttribute('href') || '').trim().toLowerCase();"
        "    if (!href || href === '#' || href.startsWith('#') || href.startsWith('javascript:')) return true;"
        "    const role = (el.getAttribute('role') || '').toLowerCase();"
        "    return role === 'button';"
        "  };"
        "  const nodes = Array.from(document.querySelectorAll(selector));"
        "  let count = 0;"
        "  let clicked = 0;"
        "  for (const el of nodes) {"
        "    if (!isVisible(el) || isDisabled(el)) continue;"
        "    if (el.dataset && el.dataset.mcpExpanded === '1') continue;"
        "    if (!allowLink(el)) continue;"
        "    if (!matches(el)) continue;"
        "    if (el.tagName === 'DETAILS') {"
        "      count += 1;"
        "      if (!el.open && clicked < maxClicks) {"
        "        el.open = true;"
        "        clicked += 1;"
        "        try { el.dataset.mcpExpanded = '1'; } catch (e) {}"
        "      }"
        "      continue;"
        "    }"
        "    const ariaExpanded = el.getAttribute && el.getAttribute('aria-expanded');"
        "    if (ariaExpanded === 'true') continue;"
        "    count += 1;"
        "    if (clicked < maxClicks) {"
        "      try { el.click(); } catch (e) {}"
        "      clicked += 1;"
        "      try { el.dataset.mcpExpanded = '1'; } catch (e) {}"
        "    }"
        "  }"
        "  return {clicked, total: count};"
        "})()"
    )


def auto_expand_page(config: BrowserConfig, spec: dict[str, Any]) -> dict[str, Any]:
    """Best-effort expand pass for collapsed content."""
    if not isinstance(spec, dict):
        return {
            "ok": False,
            "error": "auto_expand must be an object",
            "suggestion": "Use auto_expand=true or auto_expand={...}",
        }

    phrases = _as_str_list(spec.get("phrases")) or DEFAULT_EXPAND_PHRASES
    selectors_raw = spec.get("selectors")
    selectors = DEFAULT_EXPAND_SELECTORS
    if isinstance(selectors_raw, str) and selectors_raw.strip():
        selectors = selectors_raw.strip()
    elif isinstance(selectors_raw, list):
        selectors = ", ".join(_as_str_list(selectors_raw)) or DEFAULT_EXPAND_SELECTORS

    include_links = bool(spec.get("include_links", False))

    try:
        click_limit = int(spec.get("click_limit", DEFAULT_CLICK_LIMIT))
    except Exception:
        click_limit = DEFAULT_CLICK_LIMIT
    click_limit = max(1, min(click_limit, 40))

    try:
        max_iters = int(spec.get("max_iters", DEFAULT_MAX_ITERS))
    except Exception:
        max_iters = DEFAULT_MAX_ITERS
    max_iters = max(1, min(max_iters, MAX_MAX_ITERS))

    try:
        settle_ms = int(spec.get("settle_ms", DEFAULT_SETTLE_MS))
    except Exception:
        settle_ms = DEFAULT_SETTLE_MS
    settle_ms = max(0, min(settle_ms, 5000))

    js = _build_auto_expand_js(
        phrases=phrases,
        selectors=selectors,
        include_links=include_links,
        max_clicks=click_limit,
    )

    clicked_total = 0
    last_clicked = 0
    last_total = 0
    done = False

    with get_session(config) as (session, _target):
        for i in range(max_iters):
            try:
                res = session.eval_js(js)
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "error": "Auto-expand JS failed",
                    "details": {"error": str(exc)},
                    "suggestion": "Handle dialogs or reduce selector scope",
                }

            if not isinstance(res, dict):
                return {
                    "ok": False,
                    "error": "Auto-expand returned invalid result",
                    "details": {"result": str(res)},
                }

            try:
                last_clicked = int(res.get("clicked") or 0)
                last_total = int(res.get("total") or 0)
            except Exception:
                last_clicked = 0
                last_total = 0

            clicked_total += max(0, last_clicked)
            if last_total <= 0 or last_clicked <= 0:
                done = True
                break

            if settle_ms > 0:
                time.sleep(float(settle_ms) / 1000.0)

    return {
        "ok": True,
        "done": bool(done),
        "iters": int(max_iters if not done else min(max_iters, i + 1)),
        "clicked": int(clicked_total),
        "last": {"clicked": int(last_clicked), "total": int(last_total)},
        "phrases": phrases[:6],
        "selectors": selectors,
        "include_links": bool(include_links),
    }
