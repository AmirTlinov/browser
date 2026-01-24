"""Repeat-based macros for `run(actions=[...])`.

These macros expand to the internal `repeat` action and are kept in a separate
module so `run/macros.py` stays within size limits.
"""

from __future__ import annotations

from typing import Any


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
