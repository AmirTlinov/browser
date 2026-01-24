"""Macro cookbook helpers for `run(actions=[...])`.

These macros are higher-level patterns that expand into internal actions
(`assert`/`when`) and standard tools, keeping agent calls short and bounded.
"""

from __future__ import annotations

from typing import Any


def expand_goto_if_needed(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    url_contains = args.get("url_contains")
    url = args.get("url")
    if not (isinstance(url_contains, str) and url_contains.strip()):
        return {
            "ok": False,
            "error": "Missing url_contains",
            "suggestion": "Provide macro.args.url_contains='example.com/path'",
        }
    if not (isinstance(url, str) and url.strip()):
        return {
            "ok": False,
            "error": "Missing url",
            "suggestion": "Provide macro.args.url='https://...'",
        }

    wait_after = args.get("wait")
    if isinstance(wait_after, str):
        wait_after = wait_after.strip().lower()
    if wait_after not in {None, "", "auto", "navigation", "none"}:
        return {
            "ok": False,
            "error": "Invalid wait",
            "suggestion": "Use wait='auto'|'navigation'|'none'",
        }

    nav_args: dict[str, Any] = {"url": url.strip()}
    if isinstance(wait_after, str) and wait_after:
        nav_args["wait"] = wait_after

    steps = [
        {
            "when": {
                "if": {"url": url_contains.strip()},
                "then": [],
                "else": [{"navigate": nav_args}],
            }
        }
    ]
    plan_args = {
        "url_contains": str(args_note.get("url_contains") or url_contains).strip(),
        "url": str(args_note.get("url") or "<redacted>"),
        **({"wait": wait_after} if isinstance(wait_after, str) and wait_after else {}),
    }
    return {"ok": True, "steps": steps, "plan_args": plan_args}


def expand_assert_then(*, args: dict[str, Any], args_note: dict[str, Any]) -> dict[str, Any]:
    cond = args.get("assert")
    then_steps = args.get("then")
    if not isinstance(cond, dict) or not cond:
        return {
            "ok": False,
            "error": "Missing assert condition",
            "suggestion": "Provide macro.args.assert={url/title/selector/text,...}",
        }
    if not isinstance(then_steps, list) or not then_steps:
        return {
            "ok": False,
            "error": "Missing then steps",
            "suggestion": "Provide macro.args.then=[{click:{...}}, ...]",
        }

    body = [s for s in then_steps if isinstance(s, dict)]
    if len(body) != len(then_steps):
        return {
            "ok": False,
            "error": "Invalid then step list (non-object entries)",
            "suggestion": "Ensure every then step is an object like {click:{...}}",
        }
    if len(body) > 30:
        return {
            "ok": False,
            "error": "Then branch too large",
            "details": {"steps": len(body), "max": 30},
            "suggestion": "Reduce then size or split into multiple runs",
        }

    steps = [{"assert": cond}, *body]
    plan_args = {
        "assert": list(cond.keys())[:8],
        "then": len(body),
        **({"timeout_s": cond.get("timeout_s")} if "timeout_s" in cond else {}),
        **({"note": str(args_note.get("note"))} if isinstance(args_note.get("note"), str) and args_note.get("note") else {}),
    }
    return {"ok": True, "steps": steps, "plan_args": plan_args}

