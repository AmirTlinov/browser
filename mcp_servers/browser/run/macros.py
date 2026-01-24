"""Macro expansion for `run(actions=[...])`.

Macros are run-internal conveniences that expand into regular steps. They exist to:
- reduce action list verbosity (agent token + cognitive budget),
- keep behavior deterministic and bounded.

Macros do NOT execute LLMs server-side.
"""

from __future__ import annotations

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
            "suggestion": "Known macros: trace_then_screenshot, dismiss_overlays, login_basic, scroll_until_visible, scroll_to_end, retry_click, paginate_next, auto_expand, goto_if_needed, assert_then, include_memory_steps",
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
