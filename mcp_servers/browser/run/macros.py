"""Macro expansion for `run(actions=[...])`.

Macros are run-internal conveniences that expand into regular steps. They exist to:
- reduce action list verbosity (agent token + cognitive budget),
- keep behavior deterministic and bounded.

Macros do NOT execute LLMs server-side.
"""

from __future__ import annotations

import json
from typing import Any

from ..session import session_manager
from .macro_cookbook import expand_assert_then, expand_goto_if_needed
from .macro_dismiss_overlays import DISMISS_OVERLAYS_JS
from .macro_repeat_helpers import (
    expand_auto_expand,
    expand_paginate_next,
    expand_retry_click,
    expand_scroll_to_end,
    expand_scroll_until_visible,
)
from .params import ParamMissing, interpolate_params_pair, params_hint

_DEFAULT_LOGIN_USER_KEYS = [
    "email",
    "e-mail",
    "username",
    "user",
    "login",
]

_DEFAULT_LOGIN_PASSWORD_KEYS = [
    "password",
    "pass",
    "passcode",
]


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


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _coerce_boolish(value: Any) -> tuple[bool | None, bool]:
    if isinstance(value, bool):
        return value, True
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value), True
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True, True
        if v in {"false", "0", "no", "n", "off"}:
            return False, True
    return None, False


_DEFAULT_ERROR_TEXTS = [
    "error while loading",
    "something went wrong",
    "please try again",
    "unable to load",
]


def _build_error_texts_js(texts: list[str]) -> str:
    safe = [t.strip().lower() for t in texts if isinstance(t, str) and t.strip()]
    if not safe:
        return "true"
    items = json.dumps(safe)
    return (
        "(() => {"
        f"  const errors = {items};"
        "  const hay = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();"
        "  if (!hay) return true;"
        "  return !errors.some((t) => hay.includes(t));"
        "})()"
    )


def expand_macro(
    *,
    name: str,
    args: dict[str, Any] | None,
    args_note: dict[str, Any] | None,
    dry_run: bool,
    max_steps: int = 80,
) -> dict[str, Any]:
    """Expand a macro into `flow/run` steps.

    Args:
        name: Macro name (stable id)
        args: Actual arguments (may include secrets already resolved from {{mem:...}})
        args_note: Same structure as args but with secrets redacted (used for plans/notes)
        dry_run: When true, return a plan without executing steps
        max_steps: Hard cap on generated steps
    """
    name = str(name or "").strip()
    if not name:
        return {
            "ok": False,
            "error": "Missing macro name",
            "suggestion": "Provide macro.name='...'",
        }

    a = args if isinstance(args, dict) else {}
    n = args_note if isinstance(args_note, dict) else {}

    steps: list[dict[str, Any]] = []
    plan: dict[str, Any] = {"name": name, "dry_run": bool(dry_run)}

    if name == "trace_then_screenshot":
        trace = a.get("trace")
        trace_note = n.get("trace")
        trace_name = str(trace or "harLite")
        if trace_name not in {"harLite", "trace"}:
            trace_name = "harLite"

        steps = [
            {"net": {"action": trace_name, "store": True}},
            {"screenshot": {}},
        ]
        plan["args"] = {"trace": str(trace_note or trace_name)}

    elif name == "dismiss_overlays":
        steps = [{"js": {"code": DISMISS_OVERLAYS_JS.strip()}, "optional": True, "label": "dismiss_overlays"}]
        plan["args"] = {}

    elif name == "login_basic":
        username = a.get("username")
        password = a.get("password")
        if not (isinstance(username, str) and username.strip()):
            return {
                "ok": False,
                "error": "Missing username",
                "suggestion": "Provide macro.args.username",
                "details": {"name": name},
            }
        if not (isinstance(password, str) and password.strip()):
            return {
                "ok": False,
                "error": "Missing password",
                "suggestion": "Provide macro.args.password (prefer {{mem:...}} placeholders)",
                "details": {"name": name},
            }

        user_keys = _dedupe_keep_order(_as_str_list(a.get("username_key_candidates")) + _DEFAULT_LOGIN_USER_KEYS)
        pass_keys = _dedupe_keep_order(_as_str_list(a.get("password_key_candidates")) + _DEFAULT_LOGIN_PASSWORD_KEYS)

        fill: dict[str, Any] = {}
        for k in user_keys:
            fill[k] = username
        for k in pass_keys:
            fill[k] = password

        # Submit via native form submit when possible (less brittle than clicking).
        steps = [{"form": {"fill": fill, "submit": True}}]
        plan["args"] = {
            "username": str(n.get("username") or "<redacted>"),
            "username_key_candidates": _as_str_list(n.get("username_key_candidates")) or _DEFAULT_LOGIN_USER_KEYS,
            "password": "<redacted>",
            "password_key_candidates": _as_str_list(n.get("password_key_candidates")) or _DEFAULT_LOGIN_PASSWORD_KEYS,
        }

    elif name == "scroll_until_visible":
        expanded = expand_scroll_until_visible(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "scroll_to_end":
        expanded = expand_scroll_to_end(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "retry_click":
        expanded = expand_retry_click(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "paginate_next":
        expanded = expand_paginate_next(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "auto_expand":
        expanded = expand_auto_expand(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "auto_expand_scroll_extract":
        expand_spec = a.get("expand", True)
        scroll_spec = a.get("scroll", True)
        extract_spec = a.get("extract", {})
        navigate_spec = a.get("navigate")
        url_spec = a.get("url")

        plan_args: dict[str, Any] = {}
        steps = []
        warnings: list[str] = []

        if isinstance(navigate_spec, dict):
            steps.append({"navigate": dict(navigate_spec)})
            plan_args["navigate"] = list(navigate_spec.keys())[:8]
        elif isinstance(url_spec, str) and url_spec.strip():
            steps.append({"navigate": {"url": url_spec.strip()}})
            plan_args["navigate"] = ["url"]

        if expand_spec not in (None, False):
            exp_args: dict[str, Any] | None = None
            if expand_spec is True:
                exp_args = {}
            elif isinstance(expand_spec, dict):
                exp_args = dict(expand_spec)
            else:
                coerced, ok = _coerce_boolish(expand_spec)
                if ok and coerced is True:
                    exp_args = {}
                elif ok and coerced is False:
                    exp_args = None
                else:
                    warnings.append("expand: expected bool or object; defaulted to true")
                    exp_args = {}
            if exp_args is not None:
                exp_note = n.get("expand") if isinstance(n.get("expand"), dict) else {}
                expanded = expand_auto_expand(args=exp_args, args_note=exp_note)
                if not bool(expanded.get("ok")):
                    return {
                        "ok": False,
                        "error": str(expanded.get("error") or "Macro expansion failed"),
                        "suggestion": expanded.get("suggestion"),
                        "details": {"name": name},
                    }
                steps.extend(expanded.get("steps") or [])
                plan_args["expand"] = expanded.get("plan_args") or {}

        if scroll_spec not in (None, False):
            scroll_args: dict[str, Any] | None = None
            if scroll_spec is True:
                scroll_args = {}
            elif isinstance(scroll_spec, dict):
                scroll_args = dict(scroll_spec)
            else:
                coerced, ok = _coerce_boolish(scroll_spec)
                if ok and coerced is True:
                    scroll_args = {}
                elif ok and coerced is False:
                    scroll_args = None
                else:
                    warnings.append("scroll: expected bool or object; defaulted to true")
                    scroll_args = {}
            if scroll_args is not None:
                scroll_args.setdefault("stop_on_url_change", True)
                scroll_note = n.get("scroll") if isinstance(n.get("scroll"), dict) else {}
                expanded = expand_scroll_to_end(args=scroll_args, args_note=scroll_note)
                if not bool(expanded.get("ok")):
                    return {
                        "ok": False,
                        "error": str(expanded.get("error") or "Macro expansion failed"),
                        "suggestion": expanded.get("suggestion"),
                        "details": {"name": name},
                    }
                steps.extend(expanded.get("steps") or [])
                plan_args["scroll"] = expanded.get("plan_args") or {}

        if extract_spec is None:
            extract_args: dict[str, Any] = {}
        elif isinstance(extract_spec, dict):
            extract_args = dict(extract_spec)
        else:
            return {
                "ok": False,
                "error": "extract must be an object",
                "suggestion": "Use extract={...}",
                "details": {"name": name},
            }

        retry_on_error = a.get("retry_on_error", True)
        retry_enabled = False
        coerced, ok = _coerce_boolish(retry_on_error)
        if ok and coerced is not None:
            retry_enabled = bool(coerced)
        elif isinstance(retry_on_error, bool):
            retry_enabled = retry_on_error

        error_texts = _as_str_list(a.get("error_texts")) or _DEFAULT_ERROR_TEXTS
        try:
            max_error_retries = int(a.get("max_error_retries", 2))
        except Exception:
            max_error_retries = 2
        max_error_retries = max(1, min(max_error_retries, 5))

        retry_steps_raw = a.get("retry_steps")
        retry_steps: list[dict[str, Any]] = []
        if isinstance(retry_steps_raw, list):
            retry_steps = [s for s in retry_steps_raw if isinstance(s, dict)]
        if not retry_steps:
            retry_steps = [
                {"wait": {"for": "networkidle", "timeout": 6}},
                {"scroll": {"direction": "down", "amount": 400}},
                {"wait": {"for": "networkidle", "timeout": 6}},
            ]

        if retry_enabled and error_texts:
            steps.append(
                {
                    "repeat": {
                        "max_iters": int(max_error_retries),
                        "until": {"js": _build_error_texts_js(error_texts)},
                        "timeout_s": 0.4,
                        "steps": retry_steps,
                    }
                }
            )
            plan_args["retry_on_error"] = True
            plan_args["max_error_retries"] = int(max_error_retries)

        steps.append({"extract_content": extract_args})
        plan_args["extract"] = list(extract_args.keys())[:12]
        if warnings:
            plan_args["warnings"] = warnings[:4]
        plan["args"] = plan_args

    elif name == "goto_if_needed":
        expanded = expand_goto_if_needed(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            return {
                "ok": False,
                "error": str(expanded.get("error") or "Macro expansion failed"),
                "suggestion": expanded.get("suggestion"),
                "details": {"name": name},
            }
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "assert_then":
        expanded = expand_assert_then(args=a, args_note=n)
        if not bool(expanded.get("ok")):
            err = expanded.get("error") or "Macro expansion failed"
            out = {"ok": False, "error": str(err)}
            if isinstance(expanded.get("suggestion"), str) and expanded.get("suggestion"):
                out["suggestion"] = expanded.get("suggestion")
            if isinstance(expanded.get("details"), dict) and expanded.get("details"):
                out["details"] = {"name": name, **expanded.get("details")}
            else:
                out["details"] = {"name": name}
            return out
        steps = expanded.get("steps") or []
        plan["args"] = expanded.get("plan_args") or {}

    elif name == "include_memory_steps":
        key = a.get("memory_key")
        if not (isinstance(key, str) and key.strip()):
            return {
                "ok": False,
                "error": "Missing memory_key",
                "suggestion": 'Provide macro.args.memory_key (set via browser(action="memory", memory_action="set", key="...", value=[...]))',
                "details": {"name": name},
            }

        allow_sensitive = bool(a.get("allow_sensitive", False))
        mem = session_manager.memory_get(key=key.strip())
        if not isinstance(mem, dict):
            return {
                "ok": False,
                "error": "Unknown memory key",
                "suggestion": 'Set it via browser(action="memory", memory_action="set", key="...", value=[...])',
                "details": {"key": key.strip(), "known": session_manager.memory_list()[:5]},
            }
        if bool(mem.get("sensitive")) and not allow_sensitive:
            return {
                "ok": False,
                "error": "Refusing to include a sensitive memory key",
                "suggestion": "Use allow_sensitive=true only if you explicitly accept the risk; prefer storing steps with {{mem:...}} placeholders",
                "details": {"key": key.strip()},
            }

        value = mem.get("value")
        if not isinstance(value, list):
            return {
                "ok": False,
                "error": "Memory value is not a step list",
                "suggestion": "Store value as a JSON array of step objects",
                "details": {"key": key.strip()},
            }

        raw_steps = [s for s in value if isinstance(s, dict)]
        if len(raw_steps) != len(value):
            return {
                "ok": False,
                "error": "Invalid step list (non-object entries)",
                "suggestion": "Ensure every step is an object like {click:{...}} or {tool:'click', args:{...}}",
                "details": {"key": key.strip()},
            }
        if not allow_sensitive:
            from ..runbook import has_sensitive_literals

            if has_sensitive_literals(raw_steps):
                return {
                    "ok": False,
                    "error": "Refusing to include a step list with sensitive literals",
                    "suggestion": "Prefer {{mem:...}} / {{param:...}} placeholders, or use allow_sensitive=true if you explicitly accept the risk",
                    "details": {"key": key.strip()},
                }

        params = a.get("params") if isinstance(a.get("params"), dict) else {}
        expanded_steps: list[dict[str, Any]] = []
        preview_steps: list[dict[str, Any]] = []
        try:
            for st in raw_steps:
                actual, note = interpolate_params_pair(st, params)
                if isinstance(actual, dict):
                    expanded_steps.append(actual)
                if isinstance(note, dict):
                    preview_steps.append(note)
        except ParamMissing as exc:
            return {
                "ok": False,
                "error": "Missing macro param",
                "suggestion": "Provide params={...} for {{param:key}} placeholders",
                "details": {"missing": exc.key, "known": params_hint(params)},
            }

        steps = expanded_steps
        plan["args"] = {"memory_key": key.strip(), "params": params_hint(params, limit=50)}
        if preview_steps:
            plan["stepsPreview"] = preview_steps[:5]

    else:
        return {
            "ok": False,
            "error": "Unknown macro",
            "suggestion": "Known macros: trace_then_screenshot, dismiss_overlays, login_basic, scroll_until_visible, scroll_to_end, retry_click, paginate_next, auto_expand, auto_expand_scroll_extract, goto_if_needed, assert_then, include_memory_steps",
            "details": {"name": name},
        }

    if len(steps) > max(0, int(max_steps)):
        return {
            "ok": False,
            "error": "Macro expansion too large",
            "suggestion": "Reduce macro scope or increase max_steps (server default is bounded)",
            "details": {"name": name, "steps": len(steps), "max_steps": int(max_steps)},
        }

    return {
        "ok": True,
        "name": name,
        "dry_run": bool(dry_run),
        "plan": plan,
        "steps": steps,
        "steps_total": len(steps),
    }
