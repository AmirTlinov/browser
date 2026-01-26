from __future__ import annotations

import copy
import time as _time
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from ... import tools as _tools
from ..dispatch import ToolRegistry
from .timeouts import RepeatDefaults

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher


@dataclass(frozen=True)
class InternalActionResult:
    consumed: bool
    should_break: bool
    first_error: dict[str, Any] | None


@dataclass(frozen=True)
class _RepeatBackoff:
    backoff_s: float
    backoff_factor: float
    backoff_max_s: float
    backoff_jitter: float
    jitter_seed: int


class FlowInternalActions:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        config: BrowserConfig,
        launcher: BrowserLauncher,
        stop_on_error: bool,
        condition_timeout_default: float,
        repeat_defaults: RepeatDefaults,
        max_total_steps: int,
        include_stack: list[str],
        step_timeout_seconds: Callable[[str, dict[str, Any]], float],
        first_error: dict[str, Any] | None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._launcher = launcher
        self._stop_on_error = bool(stop_on_error)
        self._condition_timeout_default = float(condition_timeout_default)
        self._repeat_defaults = repeat_defaults
        self._max_total_steps = int(max_total_steps)
        self._include_stack = include_stack
        self._step_timeout_seconds = step_timeout_seconds
        self._first_error = first_error

    @property
    def first_error(self) -> dict[str, Any] | None:
        return self._first_error

    def _note_first_error(self, *, i: int, tool: str, error: str) -> None:
        if self._first_error is None:
            self._first_error = {"i": i, "tool": tool, "error": error}
    @staticmethod
    def _is_optional(meta: dict[str, Any] | None) -> bool:
        return bool(meta and bool(meta.get("optional")))
    def _fail(
        self,
        *,
        i: int,
        tool: str,
        entry: dict[str, Any],
        meta: dict[str, Any] | None,
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        is_optional = self._is_optional(meta)
        if is_optional:
            entry["optional"] = True
            step_summaries.append(entry)
            return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)
        err = entry.get("error")
        self._note_first_error(i=i, tool=tool, error=str(err) if err is not None else "error")
        step_summaries.append(entry)
        return InternalActionResult(consumed=True, should_break=bool(self._stop_on_error), first_error=self._first_error)

    def _best_effort_page_info(self) -> dict[str, Any] | None:
        try:
            info = _tools.get_page_info(self._config)
        except Exception:
            return None
        return info.get("pageInfo") if isinstance(info, dict) else None

    def _condition_check(
        self,
        cond: dict[str, Any],
        *,
        timeout_s: float,
        allow_wait: bool,
    ) -> tuple[bool, dict[str, Any] | None, str | None, str | None]:
        """Return (matched, details, error, suggestion)."""
        if not isinstance(cond, dict):
            return False, None, "Invalid condition", "Provide if={...} as an object"
        url = cond.get("url")
        title = cond.get("title")
        selector = cond.get("selector")
        text = cond.get("text")
        js_expr = cond.get("js")

        if not any(k in cond for k in ("url", "title", "selector", "text", "js")):
            return False, None, "Empty condition", "Provide at least one of: url, title, selector, text, js"

        details: dict[str, Any] = {}

        # Cheap checks first: URL/title (no waits).
        pi = self._best_effort_page_info()
        cur_url = pi.get("url") if isinstance(pi, dict) and isinstance(pi.get("url"), str) else None
        cur_title = pi.get("title") if isinstance(pi, dict) and isinstance(pi.get("title"), str) else None

        if isinstance(url, str) and url:
            details["url"] = {"expected": url, "actual": cur_url}
            if not (isinstance(cur_url, str) and url in cur_url):
                return False, details, None, None

        if isinstance(title, str) and title:
            details["title"] = {"expected": title, "actual": cur_title}
            if not (isinstance(cur_title, str) and title in cur_title):
                return False, details, None, None

        if not allow_wait:
            return True, details, None, None

        if isinstance(selector, str) and selector.strip():
            tr = self._registry.dispatch(
                "wait",
                self._config,
                self._launcher,
                {"for": "element", "selector": selector.strip(), "timeout": float(timeout_s)},
            )
            if tr.is_error:
                return False, details, "Condition wait failed", "Retry or reduce selector scope"
            payload = tr.data if isinstance(tr.data, dict) else {}
            found = payload.get("found")
            if found is None:
                found = payload.get("success")
            details["selector"] = {"selector": selector.strip(), "found": bool(found)}
            if found is not True:
                return False, details, None, None

        if isinstance(text, str) and text.strip():
            tr = self._registry.dispatch(
                "wait",
                self._config,
                self._launcher,
                {
                    "for": "text",
                    "text": text.strip(),
                    "timeout": float(timeout_s),
                    **({"selector": selector.strip()} if isinstance(selector, str) and selector.strip() else {}),
                },
            )
            if tr.is_error:
                return False, details, "Condition wait failed", "Retry or reduce text scope"
            payload = tr.data if isinstance(tr.data, dict) else {}
            ok_text = payload.get("success")
            reason = payload.get("reason")
            if reason == "dialog_open":
                return False, details, "Blocking JS dialog is open", payload.get("suggestion")
            details["text"] = {"text": text.strip(), "success": bool(ok_text)}
            if ok_text is not True:
                return False, details, None, None

        if isinstance(js_expr, str) and js_expr.strip():
            expr = js_expr.strip()
            try:
                tr = self._registry.dispatch(
                    "js",
                    self._config,
                    self._launcher,
                    {"code": expr},
                )
            except Exception as exc:  # noqa: BLE001
                return False, details, "Condition JS failed", str(exc)

            if tr.is_error:
                return False, details, "Condition JS failed", "Check JS expression or page state"

            payload = tr.data if isinstance(tr.data, dict) else {}
            result = payload.get("result")
            expr_note = expr if len(expr) <= 120 else f"{expr[:120]}…"
            details["js"] = {"expr": expr_note, "result": bool(result)}
            if not result:
                return False, details, None, None

        return True, details, None, None

    def handle_step(
        self,
        *,
        i: int,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_args_note: dict[str, Any] | None,
        meta: dict[str, Any] | None,
        steps_raw: list[dict[str, Any]],
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        if tool_name == "assert":
            return self._handle_assert(i=i, spec=tool_args, meta=meta, step_summaries=step_summaries)
        if tool_name == "when":
            return self._handle_when(i=i, spec=tool_args, meta=meta, steps_raw=steps_raw, step_summaries=step_summaries)
        if tool_name == "repeat":
            return self._handle_repeat(i=i, spec=tool_args, meta=meta, steps_raw=steps_raw, step_summaries=step_summaries)
        if tool_name == "macro":
            return self._handle_macro(
                i=i,
                spec=tool_args,
                spec_note=tool_args_note,
                meta=meta,
                steps_raw=steps_raw,
                step_summaries=step_summaries,
            )
        return InternalActionResult(consumed=False, should_break=False, first_error=self._first_error)

    def _handle_assert(
        self,
        *,
        i: int,
        spec: dict[str, Any],
        meta: dict[str, Any] | None,
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        try:
            timeout_s = float(spec.get("timeout_s", 5.0))
        except Exception:
            timeout_s = 5.0
        timeout_s = max(0.0, min(timeout_s, 60.0))

        matched, details, err, suggestion = self._condition_check(spec, timeout_s=timeout_s, allow_wait=True)
        ok = bool(matched) if not err else False
        error_msg = err if err else (None if ok else "Assertion failed")

        entry: dict[str, Any] = {
            "i": i,
            "tool": "assert",
            "ok": ok,
            **({"details": details} if isinstance(details, dict) and details else {}),
            **({"note": f"timeout_s={timeout_s:g}"} if timeout_s else {}),
        }
        if ok:
            step_summaries.append(entry)
            return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

        entry["error"] = error_msg
        entry["suggestion"] = suggestion or "Check conditions (url/title/selector/text) or increase timeout_s"
        return self._fail(i=i, tool="assert", entry=entry, meta=meta, step_summaries=step_summaries)

    def _handle_when(
        self,
        *,
        i: int,
        spec: dict[str, Any],
        meta: dict[str, Any] | None,
        steps_raw: list[dict[str, Any]],
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        cond = spec.get("if")
        then_steps = spec.get("then")
        else_steps = spec.get("else")
        try:
            timeout_s = float(spec.get("timeout_s", self._condition_timeout_default))
        except Exception:
            timeout_s = float(self._condition_timeout_default)
        timeout_s = max(0.0, min(timeout_s, 10.0))

        matched, details, err, suggestion = self._condition_check(
            cond if isinstance(cond, dict) else {},
            timeout_s=timeout_s,
            allow_wait=True,
        )
        if err:
            entry = {
                "i": i,
                "tool": "when",
                "ok": False,
                "error": err,
                **({"details": details} if isinstance(details, dict) and details else {}),
                **({"suggestion": suggestion} if isinstance(suggestion, str) and suggestion else {}),
            }
            return self._fail(i=i, tool="when", entry=entry, meta=meta, step_summaries=step_summaries)

        branch = "then" if matched else "else"
        chosen = then_steps if matched else else_steps
        chosen_steps: list[dict[str, Any]] = [s for s in chosen if isinstance(s, dict)] if isinstance(chosen, list) else []

        if len(chosen_steps) > 50:
            entry = {
                "i": i,
                "tool": "when",
                "ok": False,
                "error": "Branch too large",
                "details": {"branch": branch, "steps": len(chosen_steps), "max": 50},
                "suggestion": "Reduce then/else size or split into multiple runs",
            }
            return self._fail(i=i, tool="when", entry=entry, meta=meta, step_summaries=step_summaries)

        entry = {
            "i": i,
            "tool": "when",
            "ok": True,
            "branch": branch,
            **({"details": details} if isinstance(details, dict) and details else {}),
        }
        step_summaries.append(entry)
        if chosen_steps:
            steps_raw[i + 1 : i + 1] = chosen_steps
        return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

    def _repeat_get_max_iters(
        self,
        *,
        spec: dict[str, Any],
        i: int,
        meta: dict[str, Any] | None,
        step_summaries: list[dict[str, Any]],
    ) -> int | None:
        try:
            max_iters = int(spec.get("max_iters", 5))
        except Exception:
            max_iters = 5

        if max_iters < 1:
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Invalid max_iters",
                "details": {"max_iters": max_iters},
                "suggestion": "Use max_iters >= 1",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        if max_iters > 50:
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "max_iters too large",
                "details": {"max_iters": max_iters, "max": 50},
                "suggestion": "Reduce max_iters (hard cap is 50) or split into multiple runs",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        return int(max_iters)

    @staticmethod
    def _repeat_get_iter_done(spec: dict[str, Any]) -> int:
        try:
            iter_done = int(spec.get("__iter", 0))
        except Exception:
            iter_done = 0
        return max(0, int(iter_done))

    def _repeat_get_body_steps(
        self,
        *,
        body: Any,
        max_iters: int,
        i: int,
        meta: dict[str, Any] | None,
        step_summaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if not isinstance(body, list):
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Missing steps",
                "suggestion": "Provide repeat.steps=[{click:{...}}, {scroll:{...}}, ...]",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        body_steps = [s for s in body if isinstance(s, dict)]
        if len(body_steps) != len(body):
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Invalid step list (non-object entries)",
                "suggestion": "Ensure every step is an object like {click:{...}} or {tool:'click', args:{...}}",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        if not body_steps:
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Empty step list",
                "suggestion": "Provide repeat.steps with at least one step",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        if len(body_steps) > 25:
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Body too large",
                "details": {"steps": len(body_steps), "max": 25},
                "suggestion": "Reduce repeat.steps size or use macros to keep it compact",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        if int(max_iters) * len(body_steps) > 400:
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Repeat too large",
                "details": {"max_iters": int(max_iters), "steps": len(body_steps), "max_total": 400},
                "suggestion": "Reduce max_iters or body size, or split into multiple runs",
            }
            _ = self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)
            return None

        return body_steps

    def _repeat_get_timeout_s(self, spec: dict[str, Any]) -> float:
        try:
            timeout_s = float(spec.get("timeout_s", self._condition_timeout_default))
        except Exception:
            timeout_s = float(self._condition_timeout_default)
        return max(0.0, min(timeout_s, 10.0))

    @staticmethod
    def _repeat_get_max_time_s(spec: dict[str, Any]) -> float:
        try:
            max_time_s = float(spec.get("max_time_s", 0.0))
        except Exception:
            max_time_s = 0.0
        return max(0.0, min(max_time_s, 300.0))

    @staticmethod
    def _repeat_get_time_origin(spec: dict[str, Any], *, max_time_s: float) -> tuple[float | None, float | None]:
        if max_time_s <= 0:
            return None, None
        raw_t0 = spec.get("__t0")
        try:
            t0_mono = float(raw_t0) if raw_t0 is not None else None
        except Exception:
            t0_mono = None
        if t0_mono is None:
            t0_mono = float(_time.monotonic())
        try:
            elapsed_s = max(0.0, float(_time.monotonic()) - float(t0_mono))
        except Exception:
            elapsed_s = 0.0
        return float(t0_mono), float(elapsed_s)

    def _repeat_get_backoff(self, spec: dict[str, Any]) -> _RepeatBackoff:
        def _spec_float(key: str, *, default: float) -> float:
            if key not in spec:
                return float(default)
            try:
                return float(spec.get(key, default))
            except Exception:
                return float(default)

        def _spec_int(key: str, *, default: int) -> int:
            if key not in spec:
                return int(default)
            try:
                return int(spec.get(key, default))
            except Exception:
                return int(default)

        backoff_s = max(0.0, min(_spec_float("backoff_s", default=self._repeat_defaults.backoff_s), 30.0))
        backoff_factor = float(_spec_float("backoff_factor", default=self._repeat_defaults.backoff_factor))
        if not (backoff_factor > 0):
            backoff_factor = 1.0
        backoff_max_s = float(_spec_float("backoff_max_s", default=self._repeat_defaults.backoff_max_s))
        if backoff_max_s <= 0:
            backoff_max_s = backoff_s
        backoff_max_s = max(0.0, min(backoff_max_s, 60.0))
        backoff_jitter = max(0.0, min(_spec_float("backoff_jitter", default=self._repeat_defaults.backoff_jitter), 1.0))
        jitter_seed = _spec_int("jitter_seed", default=self._repeat_defaults.jitter_seed)
        return _RepeatBackoff(
            backoff_s=float(backoff_s),
            backoff_factor=float(backoff_factor),
            backoff_max_s=float(backoff_max_s),
            backoff_jitter=float(backoff_jitter),
            jitter_seed=int(jitter_seed),
        )

    def _repeat_sleep(
        self,
        *,
        backoff: _RepeatBackoff,
        i: int,
        iter_done: int,
        max_time_s: float,
        elapsed_s: float | None,
        tool_args: dict[str, Any],
    ) -> float | None:
        if backoff.backoff_s <= 0 or iter_done <= 0:
            return None

        try:
            delay_s = float(backoff.backoff_s) * (float(backoff.backoff_factor) ** max(0, int(iter_done) - 1))
        except Exception:
            delay_s = float(backoff.backoff_s)

        if backoff.backoff_jitter > 0 and delay_s > 0:
            x = (int(backoff.jitter_seed) & 0xFFFFFFFF) ^ (int(i) * 0x9E3779B1) ^ (int(iter_done) * 0x85EBCA6B)
            x &= 0xFFFFFFFF
            x ^= (x << 13) & 0xFFFFFFFF
            x ^= (x >> 17) & 0xFFFFFFFF
            x ^= (x << 5) & 0xFFFFFFFF
            u = float(x) / float(0xFFFFFFFF)
            j = (u * 2.0 - 1.0) * float(backoff.backoff_jitter)
            delay_s = max(0.0, float(delay_s) * (1.0 + j))

        if backoff.backoff_max_s > 0:
            delay_s = min(delay_s, float(backoff.backoff_max_s))

        if max_time_s > 0 and isinstance(elapsed_s, (int, float)):
            remaining = max(0.0, float(max_time_s) - float(elapsed_s))
            delay_s = min(delay_s, remaining)

        try:
            step_timeout_s = float(self._step_timeout_seconds("repeat", tool_args))
        except Exception:
            step_timeout_s = 1.0
        delay_s = min(delay_s, max(0.0, step_timeout_s - 0.1))
        delay_s = max(0.0, float(delay_s))

        if delay_s <= 0:
            return None
        _time.sleep(delay_s)
        return float(delay_s)

    def _handle_repeat(
        self,
        *,
        i: int,
        spec: dict[str, Any],
        meta: dict[str, Any] | None,
        steps_raw: list[dict[str, Any]],
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        max_iters = self._repeat_get_max_iters(spec=spec, i=i, meta=meta, step_summaries=step_summaries)
        if max_iters is None:
            return InternalActionResult(consumed=True, should_break=bool(self._stop_on_error), first_error=self._first_error)

        iter_done = self._repeat_get_iter_done(spec)
        body_steps = self._repeat_get_body_steps(body=spec.get("steps"), max_iters=max_iters, i=i, meta=meta, step_summaries=step_summaries)
        if body_steps is None:
            return InternalActionResult(consumed=True, should_break=bool(self._stop_on_error), first_error=self._first_error)

        until = spec.get("until")
        has_until = until is not None
        timeout_s = self._repeat_get_timeout_s(spec)
        max_time_s = self._repeat_get_max_time_s(spec)
        t0_mono, elapsed_s = self._repeat_get_time_origin(spec, max_time_s=max_time_s)
        backoff = self._repeat_get_backoff(spec)

        matched = False
        details: dict[str, Any] | None = None

        if has_until:
            if not isinstance(until, dict):
                entry = {
                    "i": i,
                    "tool": "repeat",
                    "ok": False,
                    "error": "Invalid condition",
                    "suggestion": "Provide until={url/title/selector/text}",
                }
                return self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)

            matched, details, err, suggestion = self._condition_check(until, timeout_s=timeout_s, allow_wait=True)
            if err:
                entry = {
                    "i": i,
                    "tool": "repeat",
                    "ok": False,
                    "error": err,
                    **({"details": details} if isinstance(details, dict) and details else {}),
                    **({"suggestion": suggestion} if isinstance(suggestion, str) and suggestion else {}),
                }
                return self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)

            if matched:
                entry = {
                    "i": i,
                    "tool": "repeat",
                    "ok": True,
                    "done": True,
                    "iters": int(iter_done),
                    **({"details": details} if isinstance(details, dict) and details else {}),
                }
                step_summaries.append(entry)
                return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

            if iter_done >= max_iters:
                entry = {
                    "i": i,
                    "tool": "repeat",
                    "ok": False,
                    "error": "Repeat exhausted",
                    "details": {
                        "iters": int(iter_done),
                        "max_iters": int(max_iters),
                        **({"last": details} if isinstance(details, dict) and details else {}),
                    },
                    "suggestion": "Increase max_iters, adjust until condition, or split into multiple runs",
                }
                return self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)

        if not has_until and iter_done >= max_iters:
            step_summaries.append({"i": i, "tool": "repeat", "ok": True, "done": True, "iters": int(iter_done)})
            return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

        if max_time_s > 0 and isinstance(t0_mono, (int, float)):
            try:
                elapsed_s = max(0.0, float(_time.monotonic()) - float(t0_mono))
            except Exception:
                elapsed_s = float(elapsed_s) if isinstance(elapsed_s, (int, float)) else 0.0

        if max_time_s > 0 and isinstance(elapsed_s, (int, float)) and float(elapsed_s) > float(max_time_s):
            entry = {
                "i": i,
                "tool": "repeat",
                "ok": False,
                "error": "Repeat time budget exhausted",
                "details": {
                    "elapsed_s": float(elapsed_s),
                    "max_time_s": float(max_time_s),
                    "iters": int(iter_done),
                    "max_iters": int(max_iters),
                    **({"last": details} if isinstance(details, dict) and details else {}),
                },
                "suggestion": "Increase max_time_s, reduce work per iteration, or split into multiple runs",
            }
            return self._fail(i=i, tool="repeat", entry=entry, meta=meta, step_summaries=step_summaries)

        slept_s = self._repeat_sleep(
            backoff=backoff,
            i=i,
            iter_done=iter_done,
            max_time_s=max_time_s,
            elapsed_s=elapsed_s,
            tool_args=spec,
        )

        step_summaries.append(
            {
                "i": i,
                "tool": "repeat",
                "ok": True,
                "iter": int(iter_done),
                "max_iters": int(max_iters),
                "until": bool(has_until),
                **({"details": details} if isinstance(details, dict) and details else {}),
                **({"sleep_s": slept_s} if isinstance(slept_s, (int, float)) and slept_s > 0 else {}),
                **(
                    {"time": {"elapsed_s": float(elapsed_s), "max_time_s": float(max_time_s)}}
                    if max_time_s > 0 and isinstance(elapsed_s, (int, float))
                    else {}
                ),
            }
        )

        next_spec = dict(spec)
        next_spec["__iter"] = int(iter_done) + 1
        if max_time_s > 0 and isinstance(t0_mono, (int, float)):
            next_spec["__t0"] = float(t0_mono)

        inject: list[dict[str, Any]] = [copy.deepcopy(s) for s in body_steps]
        inject.append({"repeat": next_spec})
        steps_raw[i + 1 : i + 1] = inject
        return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

    def _handle_macro(
        self,
        *,
        i: int,
        spec: dict[str, Any],
        spec_note: dict[str, Any] | None,
        meta: dict[str, Any] | None,
        steps_raw: list[dict[str, Any]],
        step_summaries: list[dict[str, Any]],
    ) -> InternalActionResult:
        note = spec_note if isinstance(spec_note, dict) else {}
        macro_name = spec.get("name") if isinstance(spec.get("name"), str) else ""
        macro_args = spec.get("args") if isinstance(spec.get("args"), dict) else {}
        macro_args_note = note.get("args") if isinstance(note.get("args"), dict) else {}
        dry_run = bool(spec.get("dry_run", False))

        try:
            from ...run import expand_macro  # local import: keeps server wiring light

            expanded = expand_macro(
                name=str(macro_name or "").strip(),
                args=macro_args,
                args_note=macro_args_note,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            expanded = {"ok": False, "error": str(exc) or "Macro expansion failed"}

        if not isinstance(expanded, dict) or expanded.get("ok") is not True:
            err_text = expanded.get("error") if isinstance(expanded, dict) and isinstance(expanded.get("error"), str) else "Macro failed"
            sug = expanded.get("suggestion") if isinstance(expanded, dict) else None
            entry = {
                "i": i,
                "tool": "macro",
                "ok": False,
                "error": err_text,
                **({"suggestion": sug} if isinstance(sug, str) and sug else {}),
                **({"details": expanded.get("details")} if isinstance(expanded, dict) and isinstance(expanded.get("details"), dict) else {}),
            }
            return self._fail(i=i, tool="macro", entry=entry, meta=meta, step_summaries=step_summaries)

        plan = expanded.get("plan") if isinstance(expanded.get("plan"), dict) else None
        gen_steps = expanded.get("steps") if isinstance(expanded.get("steps"), list) else []
        gen_steps = [s for s in gen_steps if isinstance(s, dict)]

        entry = {
            "i": i,
            "tool": "macro",
            "ok": True,
            "name": expanded.get("name"),
            "dry_run": bool(dry_run),
            **({"plan": plan} if isinstance(plan, dict) else {}),
            **({"steps_total": expanded.get("steps_total")} if isinstance(expanded.get("steps_total"), int) else {}),
        }
        step_summaries.append(entry)
        if dry_run:
            return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)

        if gen_steps:
            include_key: str | None = None
            if str(macro_name or "").strip() == "include_memory_steps":
                mk = macro_args.get("memory_key") if isinstance(macro_args, dict) else None
                if isinstance(mk, str) and mk.strip():
                    include_key = mk.strip()

            if include_key is not None:
                if include_key in self._include_stack:
                    err_text = "Recursive include_memory_steps detected"
                    entry = {
                        "i": i,
                        "tool": "macro",
                        "ok": False,
                        "error": err_text,
                        "details": {"name": "include_memory_steps", "memory_key": include_key},
                        "suggestion": "Avoid including a runbook that (directly or indirectly) includes itself",
                    }
                    return self._fail(i=i, tool="macro", entry=entry, meta=meta, step_summaries=step_summaries)

                if len(self._include_stack) >= 10:
                    err_text = "Macro nesting too deep"
                    entry = {
                        "i": i,
                        "tool": "macro",
                        "ok": False,
                        "error": err_text,
                        "details": {"name": "include_memory_steps", "depth": len(self._include_stack), "max_depth": 10},
                        "suggestion": "Reduce nested include_memory_steps usage or split into multiple runs",
                    }
                    return self._fail(i=i, tool="macro", entry=entry, meta=meta, step_summaries=step_summaries)

                self._include_stack.append(include_key)
                gen_steps = [*gen_steps, {"__macro_end": {"memory_key": include_key}}]

            steps_raw[i + 1 : i + 1] = gen_steps
            if len(steps_raw) > self._max_total_steps:
                step_summaries.append(
                    {
                        "i": i,
                        "tool": "macro",
                        "ok": False,
                        "error": "Expanded step list too large",
                        "details": {"steps": len(steps_raw), "max_total_steps": int(self._max_total_steps)},
                        "suggestion": "Reduce macro nesting/runbook size, or split into multiple runs",
                    }
                )
                self._note_first_error(i=i, tool="macro", error="Expanded step list too large")
                return InternalActionResult(consumed=True, should_break=True, first_error=self._first_error)

        return InternalActionResult(consumed=True, should_break=False, first_error=self._first_error)
