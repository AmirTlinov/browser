"""Repeat-based macros for `run(actions=[...])`.

These macros expand to the internal `repeat` action and are kept in a separate
module so `run/macros.py` stays within size limits.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_SCROLL_END_JS = (
    "(() => {"
    "  const el = document.scrollingElement || document.documentElement;"
    "  const bottom = (el.scrollTop + window.innerHeight);"
    "  return bottom >= (el.scrollHeight - 2);"
    "})()"
)

DEFAULT_EXPAND_PHRASES = [
    "show more",
    "read more",
    "see more",
    "expand",
    "show all",
    "load more",
]
DEFAULT_EXPAND_SELECTORS = (
    "button, [role=button], summary, details, [aria-expanded], [aria-controls], "
    "[data-expand], [data-expanded], [data-showmore], [data-show-more], "
    "[data-toggle], [data-collapse], [data-collapsed], [data-more], [data-open]"
)


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


def expand_scroll_until_visible(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    selector = args.get("selector")
    text = args.get("text")
    if not (isinstance(selector, str) and selector.strip()) and not (isinstance(text, str) and text.strip()):
        return {
            "ok": False,
            "error": "Missing target",
            "suggestion": "Provide macro.args.selector or macro.args.text",
        }

    until: dict[str, Any] = {}
    if isinstance(selector, str) and selector.strip():
        until["selector"] = selector.strip()
    if isinstance(text, str) and text.strip():
        until["text"] = text.strip()

    try:
        max_iters = int(args.get("max_iters", 10))
    except Exception:
        max_iters = 10
    max_iters = max(1, min(max_iters, 50))

    scroll_args = args.get("scroll") if isinstance(args.get("scroll"), dict) else {}
    if not scroll_args:
        scroll_args = {"direction": "down", "amount": 600}

    try:
        timeout_s = float(args.get("timeout_s", 0.6))
    except Exception:
        timeout_s = 0.6
    timeout_s = max(0.0, min(timeout_s, 10.0))

    repeat: dict[str, Any] = {
        "max_iters": int(max_iters),
        "until": until,
        "timeout_s": float(timeout_s),
        "steps": [{"scroll": scroll_args}],
    }
    for k in ("max_time_s", "backoff_s", "backoff_factor", "backoff_max_s", "backoff_jitter", "jitter_seed"):
        v = args.get(k)
        if v is not None and not isinstance(v, bool):
            repeat[k] = v

    plan_args: dict[str, Any] = {
        **({"selector": str(until.get("selector"))} if "selector" in until else {}),
        **({"text": str(until.get("text"))} if "text" in until else {}),
        "max_iters": int(max_iters),
        "scroll": scroll_args,
    }
    return {"ok": True, "steps": [{"repeat": repeat}], "plan_args": plan_args}


def expand_retry_click(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    click_args = args.get("click")
    until = args.get("until")
    if not isinstance(click_args, dict) or not click_args:
        return {
            "ok": False,
            "error": "Missing click args",
            "suggestion": "Provide macro.args.click={text/selector/x,y/...}",
        }
    if not isinstance(until, dict) or not until:
        return {
            "ok": False,
            "error": "Missing until condition",
            "suggestion": "Provide macro.args.until={url/title/selector/text}",
        }

    try:
        max_iters = int(args.get("max_iters", 5))
    except Exception:
        max_iters = 5
    max_iters = max(1, min(max_iters, 50))

    try:
        timeout_s = float(args.get("timeout_s", 0.8))
    except Exception:
        timeout_s = 0.8
    timeout_s = max(0.0, min(timeout_s, 10.0))

    dismiss = bool(args.get("dismiss_overlays", True))
    body_steps: list[dict[str, Any]] = []
    if dismiss:
        body_steps.append({"macro": {"name": "dismiss_overlays"}})
    # Click is optional so repeat can retry on failures (until condition is the success signal).
    body_steps.append({"click": click_args, "optional": True, "label": "retry_click"})

    repeat: dict[str, Any] = {
        "max_iters": int(max_iters),
        "until": until,
        "timeout_s": float(timeout_s),
        "steps": body_steps,
    }
    for k in ("max_time_s", "backoff_s", "backoff_factor", "backoff_max_s", "backoff_jitter", "jitter_seed"):
        v = args.get(k)
        if v is not None and not isinstance(v, bool):
            repeat[k] = v

    plan_args: dict[str, Any] = {
        "max_iters": int(max_iters),
        "timeout_s": float(timeout_s),
        "dismiss_overlays": bool(dismiss),
        # Avoid leaking raw args; keys-only is enough for debugging.
        "click": list((args_note.get("click") if isinstance(args_note.get("click"), dict) else click_args).keys())[:8],
        "until": list((args_note.get("until") if isinstance(args_note.get("until"), dict) else until).keys())[:8],
    }
    return {"ok": True, "steps": [{"repeat": repeat}], "plan_args": plan_args}


def expand_scroll_to_end(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    scroll_args = args.get("scroll") if isinstance(args.get("scroll"), dict) else {}
    if not scroll_args:
        scroll_args = {"direction": "down", "amount": 700}

    try:
        max_iters = int(args.get("max_iters", 8))
    except Exception:
        max_iters = 8
    max_iters = max(1, min(max_iters, 50))

    try:
        timeout_s = float(args.get("timeout_s", 0.4))
    except Exception:
        timeout_s = 0.4
    timeout_s = max(0.0, min(timeout_s, 10.0))

    until_js = args.get("until_js") if isinstance(args.get("until_js"), str) and args.get("until_js").strip() else None
    until_js = until_js or DEFAULT_SCROLL_END_JS

    repeat: dict[str, Any] = {
        "max_iters": int(max_iters),
        "until": {"js": until_js},
        "timeout_s": float(timeout_s),
        "steps": [{"scroll": scroll_args}],
    }

    settle_ms = args.get("settle_ms")
    if settle_ms is not None and "backoff_s" not in args:
        try:
            repeat["backoff_s"] = max(0.0, min(float(settle_ms) / 1000.0, 10.0))
        except Exception:
            repeat["backoff_s"] = 0.2
    elif "backoff_s" not in args:
        repeat["backoff_s"] = 0.2

    for k in ("max_time_s", "backoff_s", "backoff_factor", "backoff_max_s", "backoff_jitter", "jitter_seed"):
        v = args.get(k)
        if v is not None and not isinstance(v, bool):
            repeat[k] = v

    plan_args: dict[str, Any] = {
        "max_iters": int(max_iters),
        "scroll": scroll_args,
        "until_js": "<default>" if until_js == DEFAULT_SCROLL_END_JS else (until_js[:120] + "…" if len(until_js) > 120 else until_js),
    }
    return {"ok": True, "steps": [{"repeat": repeat}], "plan_args": plan_args}


def _paginate_done_js(selector: str) -> str:
    sel = json.dumps(selector)
    return (
        "(() => {"
        f"  const el = document.querySelector({sel});"
        "  if (!el) return true;"
        "  const aria = (el.getAttribute && el.getAttribute('aria-disabled')) || '';"
        "  const disabled = !!(el.disabled || el.hasAttribute('disabled') || aria === 'true' || el.classList.contains('disabled'));"
        "  return disabled;"
        "})()"
    )


def expand_paginate_next(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    next_selector = args.get("next_selector")
    if not (isinstance(next_selector, str) and next_selector.strip()):
        return {
            "ok": False,
            "error": "Missing next_selector",
            "suggestion": "Provide macro.args.next_selector (CSS selector for the Next button)",
        }

    click_args = args.get("click") if isinstance(args.get("click"), dict) else {}
    if not click_args:
        click_args = {"selector": next_selector.strip()}

    until = args.get("until") if isinstance(args.get("until"), dict) else None
    if not until:
        until = {"js": _paginate_done_js(next_selector.strip())}

    try:
        max_iters = int(args.get("max_iters", 10))
    except Exception:
        max_iters = 10
    max_iters = max(1, min(max_iters, 50))

    try:
        timeout_s = float(args.get("timeout_s", 0.8))
    except Exception:
        timeout_s = 0.8
    timeout_s = max(0.0, min(timeout_s, 10.0))

    dismiss = bool(args.get("dismiss_overlays", True))
    body_steps: list[dict[str, Any]] = []
    if dismiss:
        body_steps.append({"macro": {"name": "dismiss_overlays"}})

    body_steps.append({"click": click_args, "optional": True, "label": "paginate_next"})

    wait_args = args.get("wait") if isinstance(args.get("wait"), dict) else None
    if wait_args:
        body_steps.append({"wait": wait_args})

    repeat: dict[str, Any] = {
        "max_iters": int(max_iters),
        "until": until,
        "timeout_s": float(timeout_s),
        "steps": body_steps,
    }

    settle_ms = args.get("settle_ms")
    if settle_ms is not None and "backoff_s" not in args:
        try:
            repeat["backoff_s"] = max(0.0, min(float(settle_ms) / 1000.0, 10.0))
        except Exception:
            repeat["backoff_s"] = 0.2
    elif "backoff_s" not in args:
        repeat["backoff_s"] = 0.2

    for k in ("max_time_s", "backoff_s", "backoff_factor", "backoff_max_s", "backoff_jitter", "jitter_seed"):
        v = args.get(k)
        if v is not None and not isinstance(v, bool):
            repeat[k] = v

    plan_args: dict[str, Any] = {
        "next_selector": next_selector.strip(),
        "max_iters": int(max_iters),
        "timeout_s": float(timeout_s),
        "dismiss_overlays": bool(dismiss),
        "click": list(
            (args_note.get("click") if isinstance(args_note.get("click"), dict) else click_args).keys()
        )[:8],
        "until": list((args_note.get("until") if isinstance(args_note.get("until"), dict) else until).keys())[:8],
    }
    if wait_args:
        plan_args["wait"] = list(wait_args.keys())[:6]
    return {"ok": True, "steps": [{"repeat": repeat}], "plan_args": plan_args}


def _build_auto_expand_js(
    *,
    phrases: list[str],
    selectors: str,
    include_links: bool,
    max_clicks: int,
    do_click: bool,
) -> str:
    phrases_json = json.dumps([p.lower() for p in phrases if p.strip()])
    selectors_json = json.dumps(selectors)
    do_click_js = "true" if do_click else "false"
    include_links_js = "true" if include_links else "false"
    return (
        "(() => {"
        f"  const phrases = {phrases_json};"
        f"  const selector = {selectors_json};"
        f"  const includeLinks = {include_links_js};"
        f"  const maxClicks = {int(max_clicks)};"
        f"  const doClick = {do_click_js};"
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
        "  const hasExpandHints = (el) => {"
        "    const ariaExpanded = el.getAttribute && el.getAttribute('aria-expanded');"
        "    if (ariaExpanded === 'false') return true;"
        "    if (ariaExpanded === 'true') return false;"
        "    const role = norm(el.getAttribute && el.getAttribute('role'));"
        "    if (role === 'button') {"
        "      if (el.hasAttribute && (el.hasAttribute('aria-expanded') || el.hasAttribute('aria-controls'))) return true;"
        "    }"
        "    const dataAttrs = ['data-expand', 'data-expanded', 'data-showmore', 'data-show-more', 'data-toggle',"
        "      'data-collapse', 'data-collapsed', 'data-more', 'data-open'];"
        "    for (const attr of dataAttrs) {"
        "      if (el.hasAttribute && el.hasAttribute(attr)) return true;"
        "    }"
        "    const dataTokens = ['expand', 'collapse', 'collapsed', 'show', 'more', 'toggle', 'open'];"
        "    const names = el.getAttributeNames ? el.getAttributeNames() : (el.attributes ? Array.from(el.attributes).map((a) => a.name) : []);"
        "    for (const name of names) {"
        "      if (!name || !name.startsWith('data-')) continue;"
        "      const lower = name.toLowerCase();"
        "      if (dataTokens.some((t) => lower.includes(t))) return true;"
        "      const val = norm(el.getAttribute(name));"
        "      if (val && dataTokens.some((t) => val.includes(t))) return true;"
        "    }"
        "    const controls = el.getAttribute && el.getAttribute('aria-controls');"
        "    if (controls) return true;"
        "    return false;"
        "  };"
        "  const nodes = Array.from(document.querySelectorAll(selector));"
        "  let count = 0;"
        "  let clicked = 0;"
        "  for (const el of nodes) {"
        "    if (!isVisible(el) || isDisabled(el)) continue;"
        "    if (el.dataset && el.dataset.mcpExpanded === '1') continue;"
        "    if (!allowLink(el)) continue;"
        "    if (!matches(el) && !hasExpandHints(el)) continue;"
        "    if (el.tagName === 'DETAILS') {"
        "      count += 1;"
        "      if (doClick && !el.open && clicked < maxClicks) {"
        "        el.open = true;"
        "        clicked += 1;"
        "        try { el.dataset.mcpExpanded = '1'; } catch (e) {}"
        "      }"
        "      continue;"
        "    }"
        "    const ariaExpanded = el.getAttribute && el.getAttribute('aria-expanded');"
        "    if (ariaExpanded === 'true') continue;"
        "    count += 1;"
        "    if (doClick && clicked < maxClicks) {"
        "      try { el.click(); } catch (e) {}"
        "      clicked += 1;"
        "      try { el.dataset.mcpExpanded = '1'; } catch (e) {}"
        "    }"
        "  }"
        "  if (!doClick) return count === 0;"
        "  return {clicked, total: count};"
        "})()"
    )


def expand_auto_expand(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    phrases = _as_str_list(args.get("phrases")) or DEFAULT_EXPAND_PHRASES
    selectors_raw = args.get("selectors")
    selectors = DEFAULT_EXPAND_SELECTORS
    if isinstance(selectors_raw, str) and selectors_raw.strip():
        selectors = selectors_raw.strip()
    elif isinstance(selectors_raw, list):
        selectors = ", ".join(_as_str_list(selectors_raw)) or DEFAULT_EXPAND_SELECTORS

    include_links = bool(args.get("include_links", False))

    try:
        max_clicks = int(args.get("click_limit", 6))
    except Exception:
        max_clicks = 6
    max_clicks = max(1, min(max_clicks, 40))

    try:
        max_iters = int(args.get("max_iters", 6))
    except Exception:
        max_iters = 6
    max_iters = max(1, min(max_iters, 50))

    try:
        timeout_s = float(args.get("timeout_s", 0.4))
    except Exception:
        timeout_s = 0.4
    timeout_s = max(0.0, min(timeout_s, 10.0))

    count_js = _build_auto_expand_js(
        phrases=phrases,
        selectors=selectors,
        include_links=include_links,
        max_clicks=max_clicks,
        do_click=False,
    )
    click_js = _build_auto_expand_js(
        phrases=phrases,
        selectors=selectors,
        include_links=include_links,
        max_clicks=max_clicks,
        do_click=True,
    )

    body_steps: list[dict[str, Any]] = [{"js": {"code": click_js}}]
    wait_args = args.get("wait") if isinstance(args.get("wait"), dict) else None
    if wait_args:
        body_steps.append({"wait": wait_args})

    repeat: dict[str, Any] = {
        "max_iters": int(max_iters),
        "until": {"js": count_js},
        "timeout_s": float(timeout_s),
        "steps": body_steps,
    }

    settle_ms = args.get("settle_ms")
    if settle_ms is not None and "backoff_s" not in args:
        try:
            repeat["backoff_s"] = max(0.0, min(float(settle_ms) / 1000.0, 10.0))
        except Exception:
            repeat["backoff_s"] = 0.2
    elif "backoff_s" not in args:
        repeat["backoff_s"] = 0.2

    for k in ("max_time_s", "backoff_s", "backoff_factor", "backoff_max_s", "backoff_jitter", "jitter_seed"):
        v = args.get(k)
        if v is not None and not isinstance(v, bool):
            repeat[k] = v

    plan_args: dict[str, Any] = {
        "phrases": phrases[:8],
        "selectors": selectors,
        "include_links": bool(include_links),
        "click_limit": int(max_clicks),
        "max_iters": int(max_iters),
    }
    if wait_args:
        plan_args["wait"] = list(wait_args.keys())[:6]

    return {"ok": True, "steps": [{"repeat": repeat}], "plan_args": plan_args}
