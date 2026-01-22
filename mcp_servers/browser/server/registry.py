"""
Tool registry with dispatch table for MCP server.

Replaces the massive if-elif chain with clean O(1) lookup.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from .types import ToolResult

if TYPE_CHECKING:
    from ..config import BrowserConfig
    from ..launcher import BrowserLauncher

logger = logging.getLogger("mcp.browser.registry")

# Type alias for handler function
HandlerFunc = Callable[["BrowserConfig", "BrowserLauncher", dict[str, Any]], ToolResult]


class ToolRegistry:
    """Registry for tool handlers with automatic browser lifecycle management."""

    def __init__(self) -> None:
        # name -> (handler, requires_browser)
        self._handlers: dict[str, tuple[HandlerFunc, bool]] = {}

    def register(
        self,
        name: str,
        handler: HandlerFunc,
        requires_browser: bool = True,
    ) -> None:
        """Register a tool handler."""
        self._handlers[name] = (handler, requires_browser)

    def register_many(self, handlers: dict[str, tuple[HandlerFunc, bool]]) -> None:
        """Register multiple handlers at once."""
        self._handlers.update(handlers)

    def get(self, name: str) -> tuple[HandlerFunc, bool] | None:
        """Get handler and its browser requirement."""
        return self._handlers.get(name)

    def has(self, name: str) -> bool:
        """Check if handler exists."""
        return name in self._handlers

    def dispatch(
        self,
        name: str,
        config: BrowserConfig,
        launcher: BrowserLauncher,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """
        Dispatch tool call to appropriate handler.

        Args:
            name: Tool name
            config: Browser configuration
            launcher: Browser launcher instance
            arguments: Tool arguments

        Returns:
            ToolResult from handler

        Raises:
            KeyError: If tool not found
        """
        handler_info = self._handlers.get(name)
        if handler_info is None:
            raise KeyError(f"Unknown tool: {name}")

        handler, requires_browser = handler_info

        # Ensure browser is running if needed
        if requires_browser:
            launch_res = launcher.ensure_running()

            mode = getattr(config, "mode", "launch")
            if mode == "extension":
                # Extension mode does NOT require a remote-debugging-port HTTP endpoint.
                # Health-check is "is the extension connected?" (fail-closed, low-noise).
                try:
                    from ..session import session_manager as _session_manager

                    gw = _session_manager.get_extension_gateway()
                    if gw is None:
                        return ToolResult.error(
                            "Extension gateway is not configured (mode=extension)",
                            tool=name,
                            suggestion="Start the server with MCP_BROWSER_MODE=extension and ensure the gateway starts successfully",
                        )
                    if not gw.is_connected():
                        # Fail-soft: allow a short wait for the extension to connect.
                        # This avoids "first call fails" races right after server startup.
                        try:
                            connect_timeout = float(os.environ.get("MCP_EXTENSION_CONNECT_TIMEOUT") or 2.0)
                        except Exception:
                            connect_timeout = 2.0
                        connect_timeout = max(0.0, min(connect_timeout, 15.0))
                        if connect_timeout > 0:
                            with suppress(Exception):
                                gw.wait_for_connection(timeout=connect_timeout)
                    if not gw.is_connected():
                        return ToolResult.error(
                            "Extension is not connected (mode=extension)",
                            tool=name,
                            suggestion='Enable the Browser MCP extension and turn ON agent control in the extension popup, then retry (check via browser(action="status"))',
                            details={"gateway": gw.status()},
                        )
                except Exception:
                    # If we can't validate readiness, let the tool attempt and surface its own error.
                    pass
            else:
                # Fail fast (no hangs): a common brick state is "port listens but /json/version hangs".
                # In that case we want a deterministic suggestion instead of letting downstream tools time out.
                try:
                    if not launcher.cdp_ready(timeout=0.6):
                        return ToolResult.error(
                            "CDP endpoint not reachable (port may be in use or Chrome is hung)",
                            tool=name,
                            suggestion='Try browser(action="recover") (hard restart if owned) or change MCP_BROWSER_PORT',
                            details={"cdpPort": config.cdp_port, "message": getattr(launch_res, "message", None)},
                        )
                except Exception:
                    # If we can't validate readiness, let the tool attempt and surface its own error.
                    pass

        return handler(config, launcher, arguments)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._handlers.keys())

    def __len__(self) -> int:
        return len(self._handlers)


def create_default_registry() -> ToolRegistry:
    """Create registry with unified handlers."""
    from .handlers.unified import UNIFIED_HANDLERS

    registry = ToolRegistry()
    registry.register_many(UNIFIED_HANDLERS)

    # High-leverage super-tool: batch multiple tool calls into one.
    # Registered here (not in UNIFIED_HANDLERS) so it can dispatch to this registry.
    from time import time as _now

    from .. import tools as _tools
    from ..http_client import HttpClientError as _HttpClientError
    from ..session import session_manager as _session_manager
    from ..tools.base import SmartToolError as _SmartToolError
    from .artifacts import artifact_store as _artifact_store
    from .hints import artifact_get_hint

    def _extract_ctx_field(text: str, field: str) -> str | None:
        """Best-effort parse of render_ctx_markdown output for a single `key: value` field."""
        if not text:
            return None
        in_content = False
        for line in text.splitlines():
            if line.strip() == "[CONTENT]":
                in_content = True
                continue
            if not in_content:
                continue
            if line.startswith(f"{field}:"):
                return line.split(":", 1)[1].strip()
        return None

    def _step_note(tool_name: str, step_args: dict[str, Any]) -> str:
        """Compact per-step note (no secrets)."""
        if tool_name == "navigate" and isinstance(step_args.get("url"), str):
            return step_args["url"]
        if tool_name == "click":
            if isinstance(step_args.get("text"), str):
                role = step_args.get("role")
                return f"text={step_args['text']}" + (f" role={role}" if role else "")
            if isinstance(step_args.get("selector"), str):
                return f"selector={step_args['selector']}"
            if "x" in step_args and "y" in step_args:
                return f"xy=({step_args.get('x')},{step_args.get('y')})"
        if tool_name == "type":
            if isinstance(step_args.get("key"), str):
                mods = "".join(
                    c for c, flag in (("C", "ctrl"), ("A", "alt"), ("M", "meta"), ("S", "shift")) if step_args.get(flag)
                )
                return f"key={step_args['key']}" + (f" mods={mods}" if mods else "")
            if isinstance(step_args.get("selector"), str):
                t = step_args.get("text")
                t_len = len(t) if isinstance(t, str) else 0
                return f"selector={step_args['selector']} text_len={t_len}"
            t = step_args.get("text")
            t_len = len(t) if isinstance(t, str) else 0
            return f"text_len={t_len}"
        if tool_name in {"http", "fetch"} and isinstance(step_args.get("url"), str):
            method = step_args.get("method")
            return f"{method} {step_args['url']}" if method else step_args["url"]
        if tool_name == "net":
            action = step_args.get("action") if isinstance(step_args.get("action"), str) else "harLite"
            since = step_args.get("since")
            return f"action={action}" + (f" since={since}" if since is not None else "")
        if tool_name == "wait" and isinstance(step_args.get("for"), str):
            return f"for={step_args['for']}"
        if tool_name == "page":
            detail = step_args.get("detail")
            return f"detail={detail}" if detail else "overview"
        return ""

    def _normalize_step(step: Any) -> tuple[str | None, dict[str, Any], dict[str, Any] | None]:
        """Support two formats: {tool,args,label,optional} or {toolName: args} shorthand."""
        if not isinstance(step, dict):
            return None, {}, None

        if isinstance(step.get("tool"), str):
            tool_name = step["tool"]
            raw_args = step.get("args")
            tool_args = raw_args if isinstance(raw_args, dict) else {}
            meta: dict[str, Any] = {}
            if "label" in step:
                meta["label"] = step.get("label")
            if "optional" in step:
                meta["optional"] = bool(step.get("optional"))
            if "export" in step and isinstance(step.get("export"), dict):
                meta["export"] = step.get("export")
            if "download" in step:
                meta["download"] = step.get("download")
            if "irreversible" in step:
                meta["irreversible"] = bool(step.get("irreversible"))
            return tool_name, tool_args, meta

        # Shorthand with optional meta keys at the same level:
        # {click:{...}, label:"...", download:true, optional:true, export:{...}}
        meta_keys = {"label", "optional", "export", "download", "irreversible"}
        tool_keys = [k for k in step if k not in meta_keys]
        if len(tool_keys) == 1:
            tool_name = str(tool_keys[0])
            raw_args = step.get(tool_keys[0])
            tool_args = raw_args if isinstance(raw_args, dict) else {}
            meta: dict[str, Any] = {}
            if "label" in step:
                meta["label"] = step.get("label")
            if "optional" in step:
                meta["optional"] = bool(step.get("optional"))
            if "export" in step and isinstance(step.get("export"), dict):
                meta["export"] = step.get("export")
            if "download" in step:
                meta["download"] = step.get("download")
            if "irreversible" in step:
                meta["irreversible"] = bool(step.get("irreversible"))
            return tool_name, tool_args, (meta if meta else None)

        return None, {}, None

    _MISSING = object()

    def _extract_path(obj: Any, path: str) -> Any:
        """Extract a scalar value from a nested dict/list using a dotted path (e.g. 'artifact.id')."""
        if not path or not isinstance(path, str):
            return _MISSING
        cur: Any = obj
        for raw_part in path.split("."):
            part = raw_part.strip()
            if not part:
                continue
            if isinstance(cur, dict):
                if part not in cur:
                    return _MISSING
                cur = cur.get(part)
                continue
            if isinstance(cur, list) and part.isdigit():
                idx = int(part)
                if idx < 0 or idx >= len(cur):
                    return _MISSING
                cur = cur[idx]
                continue
            return _MISSING
        return cur

    def handle_flow(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
        """Execute a compact multi-step flow and return a single summary."""
        steps_raw = args.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return ToolResult.error(
                "Missing or empty 'steps' array",
                tool="flow",
                suggestion="Provide steps=[{tool:'navigate', args:{url:'...'}}, ...] or steps=[{navigate:{url:'...'}}, ...]",
            )

        stop_on_error = bool(args.get("stop_on_error", True))
        final = str(args.get("final", "observe") or "observe")
        if final not in {"none", "observe", "audit", "triage", "diagnostics"}:
            return ToolResult.error(
                f"Unknown final: {final}",
                tool="flow",
                suggestion="Use final='observe' (default), 'audit', 'triage', 'diagnostics', or 'none'",
            )
        delta_final = bool(args.get("delta_final", True))
        with_screenshot = bool(args.get("with_screenshot", False))

        steps_output = str(args.get("steps_output", "compact") or "compact").lower()
        if steps_output not in {"compact", "errors", "none"}:
            return ToolResult.error(
                f"Unknown steps_output: {steps_output}",
                tool="flow",
                suggestion="Use steps_output='compact' (default), 'errors', or 'none'",
            )

        screenshot_on_error = bool(args.get("screenshot_on_error", False))
        triage_on_error = bool(args.get("triage_on_error", True))
        diagnostics_on_error = bool(args.get("diagnostics_on_error", False))

        # Internal/advanced: attach a compact proof object to each executed step.
        step_proof = bool(args.get("step_proof", False))
        proof_screenshot = str(args.get("proof_screenshot", "none") or "none").lower()
        if proof_screenshot not in {"none", "artifact"}:
            proof_screenshot = "none"
        screenshot_on_ambiguity = bool(args.get("screenshot_on_ambiguity", False))

        # Resume lever: start executing steps from this index (run(start_at=...) support).
        try:
            start_at = int(args.get("start_at", 0))
        except Exception:
            start_at = 0
        start_at = max(0, min(start_at, len(steps_raw)))

        # Robustness knobs (used by run(); safe defaults for flow()).
        auto_dialog = str(args.get("auto_dialog", "off") or "off").strip().lower()
        if auto_dialog not in {"auto", "off", "dismiss", "accept"}:
            auto_dialog = "off"
        if auto_dialog == "auto":
            # Safety-as-mode: strict disables implicit dialog actions.
            try:
                pol = _session_manager.get_policy()
                if isinstance(pol, dict) and pol.get("mode") == "strict":
                    auto_dialog = "off"
                else:
                    auto_dialog = "dismiss"
            except Exception:
                auto_dialog = "dismiss"

        auto_recover = bool(args.get("auto_recover", False))
        recover_hard = bool(args.get("recover_hard", False))
        try:
            recover_timeout = float(args.get("recover_timeout", 5.0))
        except Exception:
            recover_timeout = 5.0
        recover_timeout = max(1.0, min(recover_timeout, 30.0))

        # Recovery budget: how many times flow/run may attempt to recover and keep going.
        try:
            max_recoveries = int(args.get("max_recoveries", 0))
        except Exception:
            max_recoveries = 0
        max_recoveries = max(0, min(max_recoveries, 5))

        # When true, flow will continue executing remaining steps after a recovery (run() uses this).
        bool(args.get("continue_after_recover", False))

        # Per-step watchdog: guarantees flow/run won't hang indefinitely on a stuck action.
        try:
            action_timeout_s = float(args.get("action_timeout", 30.0))
        except Exception:
            action_timeout_s = 30.0
        action_timeout_s = max(0.2, min(action_timeout_s, 120.0))

        # Auto-download capture: optionally detect and store downloads after click-like steps.
        auto_download = bool(args.get("auto_download", False))
        try:
            auto_download_timeout_s = float(args.get("auto_download_timeout", 3.0))
        except Exception:
            auto_download_timeout_s = 3.0
        auto_download_timeout_s = max(0.0, min(auto_download_timeout_s, 60.0))

        def _is_cdp_brick(error: str | None) -> bool:
            if not isinstance(error, str) or not error:
                return False
            m = error.lower()
            return (
                "cdp response timed out" in m
                or "action timed out" in m
                or "cdp endpoint not reachable" in m
                or "cdp not reachable" in m
                or ("websocket" in m and ("closed" in m or "handshake" in m or "connection" in m))
                or "connection refused" in m
                or "broken pipe" in m
            )

        def _is_dialog_block(error: str | None) -> bool:
            if not isinstance(error, str) or not error:
                return False
            m = error.lower()
            if "blocking js dialog" in m:
                return True
            return bool(
                "js dialog" in m and ("blocked" in m or "handle it via dialog" in m or "dialog() then retry" in m)
            )

        dialogs_auto_handled = 0

        import contextlib
        import signal
        import threading
        import time as _time

        with (
            _session_manager.shared_session(config) as (shared_sess, _shared_target),
            contextlib.ExitStack() as _flow_exit,
        ):
            started = _now()
            baseline_cursor: int | None = None
            tab_id_for_auto = _session_manager.tab_id

            # Ensure Tier-0 telemetry is enabled for the session tab early:
            # - powers delta-debug without page injection
            # - lets us fail-fast on blocking dialogs (prevents CDP hangs)
            with suppress(Exception):
                _session_manager.ensure_telemetry(shared_sess)

            # Async dialog handling (prevents long hangs when alerts open mid-step).
            if isinstance(tab_id_for_auto, str) and tab_id_for_auto:
                _flow_exit.callback(lambda tid=tab_id_for_auto: _session_manager.clear_auto_dialog(tid))
                if auto_dialog in {"dismiss", "accept"}:
                    _session_manager.set_auto_dialog(
                        tab_id_for_auto, auto_dialog, ttl_s=max(10.0, action_timeout_s * 2)
                    )
                else:
                    # Ensure any previous TTL-based setting is cleared for this tab.
                    _session_manager.clear_auto_dialog(tab_id_for_auto)

            if delta_final and (
                final in {"observe", "triage", "diagnostics"} or triage_on_error or diagnostics_on_error or step_proof
            ):
                # Cursor is epoch-ms, used for delta-debug snapshots.
                # Prefer page-local time to match __mcpDiag timestamps.
                try:
                    tab_id = _session_manager.tab_id
                    t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                    dialog_open = bool(getattr(t0, "dialog_open", False)) if t0 is not None else False
                except Exception:
                    dialog_open = False

                if not dialog_open:
                    try:
                        js_now = shared_sess.eval_js("Date.now()")
                        baseline_cursor = int(js_now) if isinstance(js_now, (int, float, str)) else None
                    except Exception:
                        baseline_cursor = None
                if baseline_cursor is None:
                    baseline_cursor = int(started * 1000)

            step_summaries: list[dict[str, Any]] = []
            first_error: dict[str, Any] | None = None
            steps_artifact: dict[str, Any] | None = None
            collected_next: list[str] = []
            flow_vars: dict[str, Any] = {}

            _FLOW_VAR_INLINE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}|\$\{\s*([A-Za-z0-9_.-]+)\s*\}")
            _FLOW_VAR_EXACT_RE = re.compile(
                r"^\s*(?:\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}|\$\{\s*([A-Za-z0-9_.-]+)\s*\})\s*$"
            )

            class _FlowVarMissing(Exception):
                def __init__(self, name: str) -> None:
                    super().__init__(name)
                    self.name = str(name or "")

            def _flow_vars_hint(*, limit: int = 20) -> list[str]:
                keys = [k for k in flow_vars if isinstance(k, str) and k.strip()]
                keys.sort()
                return keys[: max(0, int(limit))]

            def _flow_var_lookup(name: str) -> Any:
                k = str(name or "").strip()
                if not k:
                    raise _FlowVarMissing(k)
                if k not in flow_vars:
                    raise _FlowVarMissing(k)
                return flow_vars.get(k)

            def _interpolate_flow_vars(value: Any) -> Any:
                if isinstance(value, str):
                    # Exact-placeholder preserves scalar types (int/bool/etc).
                    m = _FLOW_VAR_EXACT_RE.match(value)
                    if m:
                        var = m.group(1) or m.group(2) or ""
                        return _flow_var_lookup(var)

                    # Inline interpolation always stringifies.
                    def _repl(match: re.Match[str]) -> str:
                        var = match.group(1) or match.group(2) or ""
                        v = _flow_var_lookup(var)
                        return "" if v is None else str(v)

                    # Fast path: avoid regex work for most strings.
                    if "{{" not in value and "${" not in value:
                        return value
                    return _FLOW_VAR_INLINE_RE.sub(_repl, value)

                if isinstance(value, dict):
                    out: dict[str, Any] = {}
                    for k, v in value.items():
                        # Avoid interpolating keys: it creates surprising structures.
                        out[str(k)] = _interpolate_flow_vars(v)
                    return out

                if isinstance(value, list):
                    return [_interpolate_flow_vars(v) for v in value]

                return value

            def _collect_next(payload: Any) -> None:
                """Bubble step-level drilldown hints to the top-level flow/run response.

                In v2, most capabilities are internal actions inside run(). If we don't
                surface `next` hints from those actions, agents lose the drilldown path
                (e.g., artifact pointers from fetch/storage/download).
                """
                nonlocal collected_next
                if not isinstance(payload, dict):
                    return
                nxt = payload.get("next")
                if not isinstance(nxt, list):
                    return
                for item in nxt:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    if item in collected_next:
                        continue
                    collected_next.append(item)
                    # Hard cap: keep outputs cognitively-cheap.
                    if len(collected_next) >= 8:
                        break

            def _safe_js_now_ms() -> int:
                # Avoid Runtime.evaluate when dialogs are open (it will hang).
                try:
                    tab_id = _session_manager.tab_id
                    t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                    if t0 is not None and getattr(t0, "dialog_open", False):
                        return int(_now() * 1000)
                except Exception:
                    pass

                try:
                    js_now = shared_sess.eval_js("Date.now()")
                    if isinstance(js_now, (int, float)):
                        return int(js_now)
                    if isinstance(js_now, str) and js_now.strip().isdigit():
                        return int(js_now.strip())
                except Exception:
                    pass
                return int(_now() * 1000)

            def _extract_matches_found(payload: Any) -> int | None:
                if not isinstance(payload, dict):
                    return None
                res = payload.get("result")
                if isinstance(res, dict):
                    mf = res.get("matchesFound")
                    if isinstance(mf, int):
                        return mf
                mf2 = payload.get("matchesFound")
                if isinstance(mf2, int):
                    return mf2
                return None

            def _drain_and_ingest_dialog_events() -> None:
                """Best-effort: ingest dialog events from the shared session socket queue.

                Dialogs are uniquely dangerous: they can open between steps (setTimeout(alert))
                and cause subsequent CDP calls to hang. Draining the event queue keeps Tier-0
                in sync so we can fail-fast or auto-handle deterministically.
                """
                try:
                    tab_id = _session_manager.tab_id
                    if not tab_id:
                        return
                    if not (hasattr(shared_sess, "conn") and hasattr(shared_sess.conn, "pop_event")):
                        return

                    # Pull already-buffered messages off the socket (non-blocking) so
                    # Page.javascriptDialogOpening doesn't get stuck until the next CDP command.
                    with suppress(Exception):
                        if hasattr(shared_sess.conn, "drain_events"):
                            shared_sess.conn.drain_events(max_messages=50)

                    opened = shared_sess.conn.pop_event("Page.javascriptDialogOpening")
                    if opened is not None:
                        with suppress(Exception):
                            _session_manager._ingest_tier0_event(
                                tab_id, {"method": "Page.javascriptDialogOpening", "params": opened}
                            )

                    closed = shared_sess.conn.pop_event("Page.javascriptDialogClosed")
                    if closed is not None:
                        with suppress(Exception):
                            _session_manager._ingest_tier0_event(
                                tab_id, {"method": "Page.javascriptDialogClosed", "params": closed}
                            )
                except Exception:
                    return

            def _dismiss_overlay_best_effort(*, timeout_s: float = 0.9) -> bool:
                """Best-effort close of a blocking DOM overlay/modal (cookie banners, onboarding).

                This is intentionally conservative and bounded:
                - Detects a likely overlay by hit-testing the viewport center.
                - Prefers close/dismiss/cancel/skip over accept/continue.
                - Returns False when unsure (no action).

                Why this exists:
                - Complex SPAs often throw a consent/onboarding overlay that steals focus and
                  intercepts clicks, causing agents to loop.
                - Dismissing once and retrying the original action is usually faster than
                  trying 10 alternative click paths.
                """
                js = r"""
                (() => {
                  const vw = window.innerWidth || 0;
                  const vh = window.innerHeight || 0;
                  if (!vw || !vh) return null;

                  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
                  const within = (r) => r && r.width > 2 && r.height > 2 && r.right > 0 && r.bottom > 0 && r.left < vw && r.top < vh;
                  const isVisible = (el) => {
                    try {
                      const st = window.getComputedStyle(el);
                      if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0' || st.pointerEvents === 'none') return false;
                    } catch (e) {}
                    const r = el.getBoundingClientRect?.();
                    return !!(r && within(r));
                  };

                  const looksLikeOverlay = (el) => {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    if (!within(r)) return false;
                    const area = Math.max(0, r.width) * Math.max(0, r.height);
                    const vp = vw * vh;
                    const coversCenter = (vw * 0.5 >= r.left && vw * 0.5 <= r.right && vh * 0.5 >= r.top && vh * 0.5 <= r.bottom);

                    let pos = '';
                    let z = 0;
                    try {
                      const st = window.getComputedStyle(el);
                      pos = String(st?.position || '');
                      z = Number.parseInt(String(st?.zIndex || '0'), 10);
                      if (!Number.isFinite(z)) z = 0;
                    } catch (e) {}

                    const role = String(el.getAttribute?.('role') || '').toLowerCase();
                    const ariaModal = String(el.getAttribute?.('aria-modal') || '').toLowerCase();
                    const hint = (String(el.id || '') + ' ' + String(el.className || '')).toLowerCase();

                    if (role === 'dialog' || role === 'alertdialog' || ariaModal === 'true') return coversCenter;
                    if ((pos === 'fixed' || pos === 'sticky') && coversCenter && area >= vp * 0.25) return true;
                    if (coversCenter && area >= vp * 0.35) return true;
                    if (coversCenter && area >= vp * 0.20 && (hint.includes('modal') || hint.includes('dialog') || hint.includes('overlay') || hint.includes('backdrop') || hint.includes('consent') || hint.includes('cookie'))) return true;
                    if (coversCenter && z >= 1000 && area >= vp * 0.15) return true;
                    return false;
                  };

                  const cx0 = clamp(Math.floor(vw * 0.5), 1, vw - 2);
                  const cy0 = clamp(Math.floor(vh * 0.5), 1, vh - 2);
                  let el = document.elementFromPoint(cx0, cy0);
                  if (!el) return null;

                  let overlay = null;
                  for (let i = 0; i < 10 && el; i++) {
                    if (looksLikeOverlay(el) && isVisible(el)) { overlay = el; break; }
                    el = el.parentElement;
                  }
                  if (!overlay) return null;

                  const labelOf = (b) => {
                    const pick = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
                    const aria = pick(b.getAttribute?.('aria-label'));
                    const title = pick(b.getAttribute?.('title'));
                    const txt = pick(b.innerText || b.textContent || '');
                    return (aria || title || txt).slice(0, 120);
                  };
                  const score = (label, hint) => {
                    const s = (String(label || '') + ' ' + String(hint || '')).toLowerCase();
                    const close = /(close|dismiss|cancel|skip|later|not now|×|x\\b|закры|отмен|пропус|позже|не сейчас)/i;
                    const reject = /(reject|decline|deny|no|отклон|нет|запрет)/i;
                    const accept = /(accept|agree|ok|got it|continue|allow|yes|соглас|принять|ок|продолж|разреш|да)/i;
                    if (close.test(s)) return 100;
                    if (reject.test(s)) return 60;
                    if (accept.test(s)) return 25;
                    return 0;
                  };

                  const nodes = overlay.querySelectorAll('button,[role="button"],a,input[type="button"],input[type="submit"],div[role="button"],span[role="button"]');
                  let best = null;
                  let bestScore = 0;
                  for (const b of nodes) {
                    if (!b || !isVisible(b)) continue;
                    const r = b.getBoundingClientRect?.();
                    if (!within(r)) continue;
                    const label = labelOf(b);
                    const hint = (String(b.getAttribute?.('data-testid') || '') + ' ' + String(b.id || '') + ' ' + String(b.className || '')).slice(0, 200);
                    const sc = score(label, hint);
                    if (sc > bestScore) { bestScore = sc; best = b; }
                  }
                  if (!best || bestScore < 25) return null;

                  const r = best.getBoundingClientRect();
                  const x = clamp(r.left + r.width * 0.5, 5, vw - 5);
                  const y = clamp(r.top + r.height * 0.5, 5, vh - 5);
                  return { x, y, score: bestScore, label: labelOf(best) || null };
                })()
                """
                try:
                    res = shared_sess.eval_js(js, timeout=float(timeout_s))
                except Exception:
                    return False

                if not isinstance(res, dict):
                    return False
                x = res.get("x")
                y = res.get("y")
                if x is None or y is None:
                    return False
                try:
                    shared_sess.click(float(x), float(y), button="left", click_count=1)
                    _time.sleep(0.08)
                    return True
                except Exception:
                    return False

            def _handle_net_internal(step_args: dict[str, Any]) -> ToolResult:
                """Internal Tier-0 network/telemetry helper (no new top-level tools).

                v2 rationale:
                - run() is public, internal actions are not.
                - This provides a HAR-lite slice (delta via since/cursor) without dumping full diagnostics.
                """
                action = str(step_args.get("action", "harLite") or "harLite")
                action_norm = action.strip().lower()
                if action_norm in {"harlite", "har-lite", "har_lite", "har"}:
                    action = "harLite"
                elif action_norm in {"trace", "nettrace", "networktrace", "deep"}:
                    action = "trace"
                else:
                    return ToolResult.error(
                        f"Unknown net action: {action}",
                        tool="net",
                        suggestion='Use net(action="harLite") or net(action="trace")',
                    )

                # Ensure Tier-0 telemetry is enabled (best-effort).
                try:
                    active = _session_manager.get_active_shared_session()
                    if active:
                        sess, _t = active
                        _session_manager.ensure_telemetry(sess)
                except Exception:
                    pass

                tab_id = _session_manager.tab_id
                if not isinstance(tab_id, str) or not tab_id:
                    return ToolResult.error(
                        "No active session tab",
                        tool="net",
                        suggestion="Call navigate(url=...) first, then retry",
                    )

                def _to_int(x: Any) -> int | None:
                    try:
                        if x is None:
                            return None
                        if isinstance(x, bool):
                            return None
                        if isinstance(x, (int, float)):
                            return int(x)
                        s = str(x).strip()
                        if not s:
                            return None
                        return int(float(s))
                    except Exception:
                        return None

                since = _to_int(step_args.get("since"))
                try:
                    offset = int(step_args.get("offset", 0))
                except Exception:
                    offset = 0
                offset = max(0, offset)

                try:
                    limit = int(step_args.get("limit", 20))
                except Exception:
                    limit = 20
                limit = max(0, min(limit, 200))

                store = bool(step_args.get("store", False))
                export = bool(step_args.get("export", False))
                if export:
                    store = True
                overwrite = bool(step_args.get("overwrite", False))
                clear = bool(step_args.get("clear", False))

                # Thread-safe snapshot (bounded) + total via limit=0 (meaning: "no truncation").
                snap = _session_manager.tier0_snapshot(tab_id, since=since, offset=0, limit=0)
                if not isinstance(snap, dict):
                    return ToolResult.error(
                        "Tier-0 telemetry not available for this tab",
                        tool="net",
                        suggestion="Ensure MCP_TIER0=1 (default) and retry; if it still fails, navigate() to a normal http(s) page",
                    )

                payload: dict[str, Any] = {
                    "ok": True,
                    "tool": "net",
                    "action": action,
                    "cursor": snap.get("cursor"),
                    **({"since": since} if since is not None else {}),
                    "sessionTabId": tab_id,
                }

                if action == "harLite":
                    har_all = snap.get("harLite") if isinstance(snap.get("harLite"), list) else []
                    total = len(har_all)
                    items = har_all[offset:]
                    if limit:
                        items = items[:limit]

                    payload["harLite"] = {
                        "total": total,
                        "offset": offset,
                        "limit": limit,
                        "items": items,
                    }

                    if store:
                        try:
                            ref = _artifact_store.put_json(
                                kind="net_harlite",
                                obj={
                                    "action": action,
                                    "cursor": snap.get("cursor"),
                                    **({"since": since} if since is not None else {}),
                                    "harLite": har_all,
                                },
                                metadata={
                                    "total": total,
                                    "offset": offset,
                                    "limit": limit,
                                    **({"since": since} if since is not None else {}),
                                },
                            )
                            payload["artifact"] = {
                                "id": ref.id,
                                "kind": ref.kind,
                                "mimeType": ref.mime_type,
                                "bytes": ref.bytes,
                                "createdAt": ref.created_at,
                            }
                            payload["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]

                            if export:
                                name = step_args.get("name")
                                export_res = _artifact_store.export(
                                    artifact_id=ref.id,
                                    name=str(name) if isinstance(name, str) and name.strip() else None,
                                    overwrite=overwrite,
                                )
                                if isinstance(export_res, dict) and isinstance(export_res.get("export"), dict):
                                    payload["export"] = export_res.get("export")
                                    try:
                                        path = payload["export"].get("path")  # type: ignore[union-attr]
                                        if isinstance(path, str) and path:
                                            payload.setdefault("next", [])
                                            if isinstance(payload.get("next"), list):
                                                payload["next"].insert(0, f"Exported: {path}")
                                    except Exception:
                                        pass
                        except Exception:
                            # Storing/exporting is optional; never fail the core net snapshot.
                            pass

                    if clear:
                        try:
                            _session_manager.clear_har_lite(tab_id)
                            payload["cleared"] = True
                        except Exception:
                            pass

                    return ToolResult.json(payload)

                # ──────────────────────────────────────────────────────────────
                # net(action="trace") — deep, on-demand trace for a bounded set of
                # *recently completed* requests (best-effort).
                # ──────────────────────────────────────────────────────────────
                from ..net_trace import build_net_trace

                include = step_args.get("include")
                if include is None:
                    include = step_args.get("includeUrlPatterns")
                exclude = step_args.get("exclude")
                if exclude is None:
                    exclude = step_args.get("excludeUrlPatterns")

                types_raw = step_args.get("types")
                if types_raw is None:
                    types_raw = step_args.get("resourceTypes")

                capture = str(step_args.get("capture", "meta") or "meta")
                redact = step_args.get("redact")
                if redact is None:
                    redact = True

                def _to_int_default(v: Any, *, default: int, min_v: int, max_v: int) -> int:
                    try:
                        if v is None or isinstance(v, bool):
                            raise ValueError
                        if isinstance(v, (int, float)):
                            n = int(v)
                        else:
                            n = int(float(str(v).strip()))
                    except Exception:
                        n = int(default)
                    return max(min_v, min(n, max_v))

                max_body_bytes = _to_int_default(
                    step_args.get("maxBodyBytes"), default=80_000, min_v=0, max_v=2_000_000
                )
                max_total_bytes = _to_int_default(
                    step_args.get("maxTotalBytes"), default=600_000, min_v=0, max_v=10_000_000
                )

                name = step_args.get("name")
                name_str = str(name) if isinstance(name, str) and name.strip() else None

                cursor_i = snap.get("cursor") if isinstance(snap.get("cursor"), int) else None
                trace_out = build_net_trace(
                    config,
                    tab_id=tab_id,
                    cursor=cursor_i,
                    since=since,
                    offset=offset,
                    limit=limit,
                    include=include,
                    exclude=exclude,
                    types_raw=types_raw,
                    capture=capture,
                    redact=bool(redact),
                    max_body_bytes=max_body_bytes,
                    max_total_bytes=max_total_bytes,
                    store=store,
                    export=export,
                    overwrite=overwrite,
                    name=name_str,
                    clear=clear,
                )
                payload.update(trace_out)
                return ToolResult.json(payload)

            def _maybe_store_screenshot(*, kind: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
                if proof_screenshot != "artifact":
                    return None
                try:
                    shot = _tools.screenshot(config)
                    data_b64 = shot.get("content_b64") or shot.get("data", "")
                    if not isinstance(data_b64, str) or not data_b64:
                        return None
                    ref = _artifact_store.put_image_b64(
                        kind=kind, data_b64=data_b64, mime_type="image/png", metadata=metadata
                    )
                    return {
                        "artifact": {
                            "id": ref.id,
                            "kind": ref.kind,
                            "mimeType": ref.mime_type,
                            "bytes": ref.bytes,
                            "createdAt": ref.created_at,
                        },
                        "next": [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)],
                    }
                except Exception:
                    return None

            def _build_step_proof(
                *, since_ms: int, tool_name: str | None, tool_args: dict[str, Any], payload: Any
            ) -> dict[str, Any] | None:
                proof: dict[str, Any] = {"since": since_ms}

                # After-state (cheap, best-effort)
                try:
                    info = _tools.get_page_info(config)
                    pi = info.get("pageInfo") if isinstance(info, dict) else None
                    if isinstance(pi, dict):
                        proof["after"] = {
                            "url": pi.get("url"),
                            "title": pi.get("title"),
                            "readyState": pi.get("readyState"),
                        }
                except Exception:
                    pass

                # Tier-0 delta snapshot (fast, deterministic; avoids heavy injection per step).
                try:
                    tab_id = _session_manager.tab_id
                    if tab_id:
                        t0 = _session_manager.tier0_snapshot(tab_id, since=since_ms, offset=0, limit=50)
                        if isinstance(t0, dict):
                            cur = t0.get("cursor")
                            if cur is not None:
                                proof["cursor"] = cur

                            summary = t0.get("summary") if isinstance(t0.get("summary"), dict) else {}
                            delta: dict[str, Any] = {}
                            for k in (
                                "consoleErrors",
                                "consoleWarnings",
                                "jsErrors",
                                "resourceErrors",
                                "unhandledRejections",
                                "failedRequests",
                            ):
                                v = summary.get(k)
                                if isinstance(v, (int, float)) and int(v) > 0:
                                    delta[k] = int(v)
                            last_err = summary.get("lastError")
                            if isinstance(last_err, str) and last_err.strip():
                                delta["lastError"] = (
                                    (last_err.strip()[:200] + "…") if len(last_err.strip()) > 200 else last_err.strip()
                                )
                            if delta:
                                proof["delta"] = delta

                            # Dialog signal is the most common CDP brick trigger.
                            if t0.get("dialogOpen") is True:
                                d0 = t0.get("dialog") if isinstance(t0.get("dialog"), dict) else {}
                                proof["dialog"] = {
                                    "open": True,
                                    "type": d0.get("type"),
                                    "message": d0.get("message"),
                                    "url": d0.get("url"),
                                }
                                proof["top"] = {
                                    "severity": "error",
                                    "kind": "dialog_open",
                                    "message": d0.get("message") or "Dialog is open",
                                }
                            elif isinstance(last_err, str) and last_err.strip():
                                proof["top"] = {
                                    "severity": "error",
                                    "kind": "js_error",
                                    "message": delta.get("lastError"),
                                }
                            else:
                                failed = t0.get("network") if isinstance(t0.get("network"), list) else []
                                if isinstance(failed, list) and failed:
                                    n0 = failed[0] if isinstance(failed[0], dict) else None
                                    if isinstance(n0, dict):
                                        msg = n0.get("url")
                                        if isinstance(n0.get("status"), int):
                                            msg = f"{n0.get('status')} {msg}"
                                        proof["top"] = {"severity": "error", "kind": "failed_request", "message": msg}
                except Exception:
                    pass

                # Ambiguity detection (high value for screenshot/debug)
                ambiguous: dict[str, Any] | None = None
                if tool_name == "click":
                    mf = _extract_matches_found(payload)
                    if isinstance(mf, int) and mf > 1:
                        ambiguous = {"reason": "multiple_matches", "matchesFound": mf}
                if ambiguous is not None:
                    proof["ambiguous"] = ambiguous

                # Optional screenshot stored off-context
                want_shot = False
                if ambiguous is not None and screenshot_on_ambiguity:
                    want_shot = True
                if isinstance(payload, dict) and payload.get("error") and proof_screenshot == "artifact":
                    want_shot = True
                if not isinstance(payload, dict) and proof_screenshot == "artifact":
                    # Unknown shape; don't assume error.
                    pass

                if want_shot:
                    meta = {
                        "tool": tool_name,
                        "i": tool_args.get("i"),
                        "reason": "ambiguity" if ambiguous is not None else "error",
                    }
                    stored = _maybe_store_screenshot(kind="run_proof_screenshot", metadata=meta)
                    if isinstance(stored, dict):
                        proof.update(stored)

                # Signal marker (cheap decision bit)
                try:
                    delta = proof.get("delta")
                    if (
                        isinstance(delta, dict)
                        and any(isinstance(delta.get(k), (int, float)) and float(delta.get(k)) > 0 for k in delta)
                        or "dialog" in proof
                        or "ambiguous" in proof
                    ):
                        proof["signal"] = True
                    else:
                        proof["signal"] = False
                except Exception:
                    pass

                return proof if len(proof) > 1 else None

            class _ActionTimeoutError(Exception):
                pass

            def _step_timeout_seconds(tool: str, tool_args: dict[str, Any]) -> float:
                # Default watchdog per action (keeps run() predictable).
                t = float(action_timeout_s)
                # If the step itself has a timeout, allow it + small slack.
                raw = tool_args.get("timeout") if isinstance(tool_args, dict) else None
                try:
                    if raw is not None and not isinstance(raw, bool):
                        t = max(t, float(raw) + 2.0)
                except Exception:
                    pass
                return max(1.0, min(t, 300.0))

            class _Watchdog:  # noqa: D401
                """Per-action watchdog that works in threads (no SIGALRM dependency)."""

                def __init__(self, *, timeout_s: float) -> None:
                    self.timeout_s = float(timeout_s)
                    self.fired = threading.Event()
                    self._timer: threading.Timer | None = None
                    self._old_sig = None
                    self._sig_enabled = False

                def start(self) -> None:
                    if self.timeout_s <= 0:
                        return

                    def _fire() -> None:
                        self.fired.set()
                        # IMPORTANT: a plain close() can hang inside websocket-client when CDP is
                        # bricked (common after JS dialogs). Prefer a raw-socket abort breaker.
                        try:
                            conn = getattr(shared_sess, "conn", None)
                            if conn is not None and hasattr(conn, "abort"):
                                conn.abort()
                            else:
                                shared_sess.close()
                        except Exception:
                            pass

                    # Always start a thread-based watchdog: MCP servers commonly execute handlers
                    # outside the main thread, where SIGALRM cannot be used.
                    t = threading.Timer(self.timeout_s, _fire)
                    t.daemon = True
                    t.start()
                    self._timer = t

                    # Best-effort: in the main thread we can also raise a deterministic exception
                    # via SIGALRM (faster + clearer than a generic connection-closed error).
                    if (
                        threading.current_thread() is threading.main_thread()
                        and hasattr(signal, "SIGALRM")
                        and hasattr(signal, "setitimer")
                    ):
                        self._old_sig = signal.getsignal(signal.SIGALRM)

                        def _handler(_signum, _frame):  # noqa: ANN001
                            self.fired.set()
                            try:
                                conn = getattr(shared_sess, "conn", None)
                                if conn is not None and hasattr(conn, "abort"):
                                    conn.abort()
                                else:
                                    shared_sess.close()
                            except Exception:
                                pass
                            raise _ActionTimeoutError(f"Action timed out after {self.timeout_s:.1f}s")

                        signal.signal(signal.SIGALRM, _handler)
                        signal.setitimer(signal.ITIMER_REAL, float(self.timeout_s))
                        self._sig_enabled = True

                def stop(self) -> None:
                    if self._timer is not None:
                        with suppress(Exception):
                            self._timer.cancel()
                        self._timer = None
                    if self._sig_enabled:
                        with suppress(Exception):
                            signal.setitimer(signal.ITIMER_REAL, 0)
                        with suppress(Exception):
                            signal.signal(signal.SIGALRM, self._old_sig)
                        self._sig_enabled = False

            def _watchdog_start(timeout_s: float) -> _Watchdog | None:  # noqa: ANN001
                if timeout_s <= 0:
                    return None
                wd = _Watchdog(timeout_s=float(timeout_s))
                wd.start()
                return wd

            def _watchdog_stop(wd: _Watchdog | None) -> None:  # noqa: ANN001
                if wd is None:
                    return
                wd.stop()

            def _close_dialog_best_effort(*, accept: bool, max_wait_s: float = 1.5) -> bool:
                """Close a blocking JS dialog in a way that minimizes CDP wedges.

                Strategy (best-effort):
                1) Immediately schedule the Tier-0 out-of-band handler (fresh connection).
                2) Try a fast direct Page.handleJavaScriptDialog on the shared connection.
                3) Poll Tier-0 state briefly until the dialog is observed closed.

                IMPORTANT:
                - This MUST be bounded by `max_wait_s` (not by action_timeout_s), otherwise a single
                  dialog guard can consume tens of seconds and blow up agent UX.
                - Avoid calling the heavy dialog() tool here: it can run health checks + soft recover
                  and is intentionally slower. run()/flow auto-dialog must be cheap and predictable.
                """

                def _is_no_dialog_error(exc: Exception) -> bool:
                    msg = str(exc).lower()
                    return (
                        "no dialog" in msg
                        or "dialog is not showing" in msg
                        or "no javascript dialog" in msg
                        or "no javascript dialog is showing" in msg
                    )

                tab_id = _session_manager.tab_id
                if not isinstance(tab_id, str) or not tab_id:
                    return False

                try:
                    max_wait_s = float(max_wait_s)
                except Exception:
                    max_wait_s = 1.5
                max_wait_s = max(0.0, min(float(max_wait_s), 10.0))

                # Always schedule an out-of-band close first: it's cheap and doesn't risk
                # wedging the shared (in-flight) CDP connection used by the current tool call.
                with suppress(Exception):
                    _session_manager._schedule_auto_dialog_handle(tab_id, accept=bool(accept))

                deadline = _now() + max_wait_s
                # Poll + attempt a fast direct close (bounded).
                while _now() <= deadline:
                    _drain_and_ingest_dialog_events()

                    # Attempt: direct Page.handleJavaScriptDialog on the shared connection.
                    handled = False
                    try:
                        remaining = max(0.0, deadline - _now())
                        # Keep the per-attempt watchdog short so we never burn the full budget
                        # on a single blocked send(). If it wedges, the watchdog breaks the socket.
                        wd_dialog = _watchdog_start(min(1.0, remaining + 0.2))
                        try:
                            shared_sess.send("Page.handleJavaScriptDialog", {"accept": bool(accept)})
                        finally:
                            _watchdog_stop(wd_dialog)
                        handled = True
                    except Exception as exc:
                        # If Chrome says "no dialog", treat it as closed: the dialog may have already
                        # been handled out-of-band, or telemetry might be stale.
                        if _is_no_dialog_error(exc):
                            handled = True
                        else:
                            handled = False

                    if handled:
                        # Force Tier-0 dialog state closed (the closed event can be missed).
                        with suppress(Exception):
                            _session_manager.note_dialog_closed(tab_id, accepted=bool(accept))
                        with suppress(Exception):
                            _drain_and_ingest_dialog_events()
                        return True

                    # If the out-of-band handler closed the dialog while we were attempting, accept it.
                    try:
                        t0 = _session_manager.get_telemetry(tab_id)
                        if t0 is not None and not bool(getattr(t0, "dialog_open", False)):
                            return True
                    except Exception:
                        pass

                    if max_wait_s <= 0:
                        break
                    _time.sleep(0.05)

                return False

            for i, step in enumerate(steps_raw):
                if i < start_at:
                    continue
                tool_name, tool_args, meta = _normalize_step(step)
                if not tool_name:
                    step_summaries.append({"i": i, "ok": False, "error": "Invalid step format"})
                    first_error = first_error or {"i": i, "tool": None, "error": "Invalid step format"}
                    if stop_on_error:
                        break
                    continue

                # Stateful flows: allow later steps to reference exported scalars from prior steps.
                # Example:
                # - step0.export = {"traceId":"artifact.id"}
                # - step1.args.id = "{{traceId}}"
                try:
                    tool_args = _interpolate_flow_vars(tool_args)
                except _FlowVarMissing as exc:
                    hint = _flow_vars_hint()
                    step_summaries.append(
                        {
                            "i": i,
                            "tool": tool_name,
                            "ok": False,
                            "error": "Missing flow variable",
                            "details": {"var": exc.name, "known": hint},
                            "suggestion": "Export a value from an earlier step via export={myVar:'path.to.scalar'} then reference it via {{myVar}} or ${myVar}",
                        }
                    )
                    first_error = first_error or {"i": i, "tool": tool_name, "error": "Missing flow variable"}
                    if stop_on_error:
                        break
                    continue

                # Fail-fast: if a blocking JS dialog is currently open, avoid running any other
                # actions that may hang CDP/Runtime. This makes cross-call dialog scenarios safe.
                if tool_name not in {"dialog", "browser"}:
                    try:
                        tab_id = _session_manager.tab_id
                        _drain_and_ingest_dialog_events()

                        t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                        if t0 is not None and getattr(t0, "dialog_open", False):
                            meta_d = getattr(t0, "dialog_last", None)
                            dialog = meta_d if isinstance(meta_d, dict) else {}
                            # Optional: auto-handle dialogs to keep flows cognitively-cheap.
                            handled_dialog = False
                            if auto_dialog in {"dismiss", "accept"}:
                                accept = auto_dialog == "accept"
                                handled_dialog = _close_dialog_best_effort(
                                    accept=bool(accept),
                                    max_wait_s=min(2.0, action_timeout_s),
                                )
                                if handled_dialog:
                                    dialogs_auto_handled += 1

                            if not handled_dialog:
                                toolset = str(os.environ.get("MCP_TOOLSET") or "").strip().lower()
                                is_v2 = toolset in {"v2", "northstar", "north-star"}
                                next_hint = (
                                    "dialog(accept=true)" if auto_dialog != "dismiss" else "dialog(accept=false)"
                                )
                                backup_hint = 'tabs(action="rescue")'
                                suggestion = (
                                    f"Re-run with a dialog action: run(actions=[{{dialog:{{accept:{'false' if auto_dialog == 'dismiss' else 'true'}}}}}])"
                                    if is_v2
                                    else f"Handle the dialog first: {next_hint} (backup: {backup_hint})"
                                )
                                step_summaries.append(
                                    {
                                        "i": i,
                                        "tool": tool_name,
                                        "ok": False,
                                        "error": "Blocking JS dialog is open",
                                        "details": {
                                            "type": dialog.get("type"),
                                            "message": dialog.get("message"),
                                            "url": dialog.get("url"),
                                        },
                                        "suggestion": suggestion,
                                        "next": [next_hint, backup_hint],
                                    }
                                )
                                if next_hint not in collected_next and len(collected_next) < 8:
                                    collected_next.append(next_hint)
                                if backup_hint not in collected_next and len(collected_next) < 8:
                                    collected_next.append(backup_hint)
                                first_error = first_error or {
                                    "i": i,
                                    "tool": tool_name,
                                    "error": "Blocking JS dialog is open",
                                }
                                if stop_on_error:
                                    break
                                continue
                    except Exception:
                        # If we can't read telemetry, proceed (best-effort).
                        pass

                # Internal "act": resolve a stable affordance ref (aff:<hash>) into a concrete tool call.
                # This keeps run/flow cognitive-cheap: agents can do page() -> act(ref) without
                # re-specifying long locators/text each time.
                display_tool = tool_name
                act_ref: str | None = None
                act_state: dict[str, Any] | None = None
                act_healed = False
                if tool_name == "act":
                    act_ref_val = tool_args.get("ref") if isinstance(tool_args, dict) else None
                    act_ref = act_ref_val if isinstance(act_ref_val, str) else None
                    tab_id = _session_manager.tab_id
                    resolved, state = _session_manager.resolve_affordance(tab_id or "", act_ref or "")
                    act_state = state if isinstance(state, dict) else None
                    if not isinstance(resolved, dict):
                        # Self-heal: refresh affordances once, then retry resolve.
                        # This is safe only because refs are stable hashes (aff:<hash>),
                        # so a "successful" re-resolve still points to the same semantic action.
                        can_refresh = True
                        try:
                            tid = tab_id or ""
                            if tid:
                                now_ms = int(_now() * 1000)
                                t0 = _session_manager.tier0_snapshot(
                                    tid, since=max(0, now_ms - 5000), offset=0, limit=3
                                )
                                if isinstance(t0, dict) and t0.get("dialogOpen") is True:
                                    # Likely blocking JS evaluation; don't try to re-run locators (it will hang).
                                    can_refresh = False
                        except Exception:
                            can_refresh = True

                        if can_refresh:
                            with contextlib.suppress(Exception):
                                _tools.get_page_locators(config, kind="all", offset=0, limit=80)

                            resolved2, state2 = _session_manager.resolve_affordance(tab_id or "", act_ref or "")
                            if isinstance(resolved2, dict):
                                resolved = resolved2
                                act_state = state2 if isinstance(state2, dict) else act_state
                                act_healed = True

                    if not isinstance(resolved, dict):
                        step_summaries.append(
                            {
                                "i": i,
                                "tool": "act",
                                "ok": False,
                                "error": "Unknown or stale affordance ref",
                                "details": {
                                    "ref": act_ref,
                                    **({"knownCount": act_state.get("count")} if isinstance(act_state, dict) else {}),
                                    **({"url": act_state.get("url")} if isinstance(act_state, dict) else {}),
                                },
                                "suggestion": "Call page(detail='triage') or page(detail='locators') to refresh affordances, then retry act(ref=...)",
                            }
                        )
                        first_error = first_error or {"i": i, "tool": "act", "error": "Unknown or stale affordance ref"}
                        if stop_on_error:
                            break
                        continue

                    resolved_tool = resolved.get("tool")
                    resolved_args = resolved.get("args")
                    if not (isinstance(resolved_tool, str) and resolved_tool):
                        step_summaries.append({"i": i, "tool": "act", "ok": False, "error": "Invalid affordance spec"})
                        first_error = first_error or {"i": i, "tool": "act", "error": "Invalid affordance spec"}
                        if stop_on_error:
                            break
                        continue
                    if not isinstance(resolved_args, dict):
                        resolved_args = {}

                    # Optional overrides: act(ref="aff:1", args={...})
                    overrides = tool_args.get("args") if isinstance(tool_args, dict) else None
                    if isinstance(overrides, dict) and overrides:
                        merged_args = {**resolved_args, **overrides}
                    else:
                        merged_args = dict(resolved_args)

                    tool_name = resolved_tool
                    tool_args = merged_args
                    display_tool = "act"

                if tool_name in {"flow", "run"}:
                    step_summaries.append(
                        {"i": i, "tool": tool_name, "ok": False, "error": "Nested flow/run is not allowed"}
                    )
                    first_error = first_error or {"i": i, "tool": tool_name, "error": "Nested flow/run is not allowed"}
                    if stop_on_error:
                        break
                    continue

                # Auto-download plan (before executing the step) so we can snapshot a baseline
                # *before* click-like actions and avoid missing instant downloads.
                download_cfg = meta.get("download") if isinstance(meta, dict) else None
                download_explicit: bool | None = None
                download_required = False
                download_timeout_s = float(auto_download_timeout_s)
                download_store = True
                download_sha256 = True
                download_sha256_max_bytes = 209_715_200
                download_poll_interval = 0.2
                download_stable_ms = 500

                if download_cfg is True:
                    download_explicit = True
                elif download_cfg is False:
                    download_explicit = False
                elif isinstance(download_cfg, dict):
                    enabled = download_cfg.get("enabled", True)
                    download_explicit = bool(enabled)
                    download_required = bool(download_cfg.get("required", False))
                    try:
                        if "timeout" in download_cfg and not isinstance(download_cfg.get("timeout"), bool):
                            download_timeout_s = float(download_cfg.get("timeout"))
                    except Exception:
                        pass
                    download_timeout_s = max(0.0, min(download_timeout_s, 180.0))

                    if "store" in download_cfg:
                        download_store = bool(download_cfg.get("store", True))
                    if "sha256" in download_cfg:
                        download_sha256 = bool(download_cfg.get("sha256", True))
                    try:
                        if "sha256_max_bytes" in download_cfg and not isinstance(
                            download_cfg.get("sha256_max_bytes"), bool
                        ):
                            download_sha256_max_bytes = int(download_cfg.get("sha256_max_bytes"))
                    except Exception:
                        pass
                    download_sha256_max_bytes = max(0, min(download_sha256_max_bytes, 2_000_000_000))

                    try:
                        if "poll_interval" in download_cfg and not isinstance(download_cfg.get("poll_interval"), bool):
                            download_poll_interval = float(download_cfg.get("poll_interval"))
                    except Exception:
                        pass
                    download_poll_interval = max(0.05, min(download_poll_interval, 1.0))

                    try:
                        if "stable_ms" in download_cfg and not isinstance(download_cfg.get("stable_ms"), bool):
                            download_stable_ms = int(download_cfg.get("stable_ms"))
                    except Exception:
                        pass
                    download_stable_ms = max(0, min(download_stable_ms, 30_000))

                want_download = False
                if download_explicit is True:
                    want_download = True
                elif download_explicit is False:
                    want_download = False
                else:
                    want_download = bool(auto_download and tool_name in {"click"})

                # Never attempt auto-download after an explicit download step.
                if tool_name == "download":
                    want_download = False

                download_baseline: list[str] | None = None
                if want_download:
                    try:
                        tab_id = _session_manager.tab_id or getattr(shared_sess, "tab_id", None)
                        if isinstance(tab_id, str) and tab_id:
                            # Configure per-tab downloads early (best-effort).
                            with suppress(Exception):
                                _session_manager.ensure_downloads(shared_sess)
                            dl_dir = _session_manager.get_download_dir(tab_id)
                            download_baseline = [p.name for p in dl_dir.iterdir() if p.is_file()]
                    except Exception:
                        download_baseline = None

                step_cursor = _safe_js_now_ms() if step_proof else None

                max_attempts = 1
                if auto_dialog in {"dismiss", "accept"} and tool_name in {"js", "page", "wait"}:
                    # Safe retry for dialog-blocked *read-ish* steps.
                    # We only retry when we have strong dialog evidence (see _is_dialog_block / dialogOpen).
                    max_attempts = 2
                elif tool_name in {"click", "type"} and not (
                    isinstance(meta, dict) and meta.get("irreversible") is True
                ):
                    # UI self-heal: allow one extra attempt for missing-element/overlay cases.
                    # The retry gate below is conservative (only for pre-click failures).
                    max_attempts = 2

                tool_result: ToolResult | None = None
                attempt = 0
                overlay_dismissed = False
                while True:
                    attempt += 1
                    watchdog = _watchdog_start(_step_timeout_seconds(tool_name, tool_args))
                    try:
                        try:
                            if tool_name == "net":
                                tool_result = _handle_net_internal(tool_args)
                            else:
                                tool_result = registry.dispatch(tool_name, config, launcher, tool_args)
                        except _ActionTimeoutError as exc:
                            tool_result = ToolResult.error(str(exc), tool=display_tool)
                        except _SmartToolError as exc:
                            # Preserve structured suggestions inside flow/run (critical for AI-native debugging).
                            tool_result = ToolResult.error(
                                exc.reason,
                                tool=exc.tool,
                                suggestion=exc.suggestion,
                                details=exc.details,
                            )
                        except _HttpClientError as exc:
                            if watchdog is not None and watchdog.fired.is_set():
                                tool_result = ToolResult.error(
                                    f"Action timed out after {watchdog.timeout_s:.1f}s",
                                    tool=display_tool,
                                )
                            else:
                                tool_result = ToolResult.error(str(exc), tool=display_tool)
                        except Exception as exc:  # noqa: BLE001
                            if watchdog is not None and watchdog.fired.is_set():
                                tool_result = ToolResult.error(
                                    f"Action timed out after {watchdog.timeout_s:.1f}s",
                                    tool=display_tool,
                                )
                            else:
                                tool_result = ToolResult.error(str(exc), tool=display_tool)
                    finally:
                        _watchdog_stop(watchdog)

                    if tool_result is None or not tool_result.is_error:
                        break
                    if attempt >= max_attempts:
                        break

                    # If the failure is dialog-related (or dialog is now open), auto-handle and retry once.
                    err = None
                    if isinstance(tool_result.data, dict) and isinstance(tool_result.data.get("error"), str):
                        err = tool_result.data.get("error")

                    # UI self-heal: if the failure looks like a missing element (pre-click),
                    # try dismissing a blocking overlay/modal and retry once.
                    def _is_ui_transient(error: str | None) -> bool:
                        if not isinstance(error, str) or not error:
                            return False
                        m = error.lower()
                        return (
                            "element not found" in m
                            or "selector not found" in m
                            or "missing element bounds" in m
                            or "no matching accessibility node found" in m
                            or "click evaluation returned null" in m
                            or "index out of range" in m
                            or "no candidates after filtering" in m
                        )

                    if (
                        not overlay_dismissed
                        and not (isinstance(meta, dict) and meta.get("irreversible") is True)
                        and tool_name in {"click", "type"}
                        and _is_ui_transient(err)
                    ):
                        try:
                            overlay_dismissed = bool(_dismiss_overlay_best_effort(timeout_s=min(0.9, action_timeout_s)))
                        except Exception:
                            overlay_dismissed = False
                        # Even if we didn't dismiss anything, allow one retry to handle "UI lag"
                        # where the element appears shortly after the first probe.
                        _time.sleep(0.12)
                        continue

                    dialog_open_now = False
                    try:
                        tab_id = _session_manager.tab_id
                        if tab_id and hasattr(shared_sess, "conn") and hasattr(shared_sess.conn, "pop_event"):
                            with suppress(Exception):
                                if hasattr(shared_sess.conn, "drain_events"):
                                    shared_sess.conn.drain_events(max_messages=50)
                            opened = shared_sess.conn.pop_event("Page.javascriptDialogOpening")
                            if opened is not None:
                                with suppress(Exception):
                                    _session_manager._ingest_tier0_event(
                                        tab_id, {"method": "Page.javascriptDialogOpening", "params": opened}
                                    )
                        t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                        dialog_open_now = bool(getattr(t0, "dialog_open", False)) if t0 is not None else False
                    except Exception:
                        dialog_open_now = False

                    if not (_is_dialog_block(err) or dialog_open_now):
                        break

                    handled_dialog = False
                    accept = auto_dialog == "accept"
                    handled_dialog = _close_dialog_best_effort(
                        accept=bool(accept), max_wait_s=min(2.0, action_timeout_s)
                    )
                    if handled_dialog:
                        dialogs_auto_handled += 1

                    if handled_dialog:
                        # Retry the original tool step once.
                        continue
                    break

                if tool_result is None:
                    tool_result = ToolResult.error("Unknown tool failure", tool=display_tool)

                # Bubble drilldown hints (artifacts) to the top-level response.
                _collect_next(tool_result.data)

                # Auto-download capture (best-effort, bounded). This runs *after* the main step
                # so we never risk double-click/type retries.
                download_result_payload: dict[str, Any] | None = None
                download_error: str | None = None
                download_suggestion: str | None = None
                if want_download and not tool_result.is_error:
                    try:
                        dl_args: dict[str, Any] = {
                            "timeout": float(download_timeout_s),
                            "store": bool(download_store),
                            "sha256": bool(download_sha256),
                            "sha256_max_bytes": int(download_sha256_max_bytes),
                            "poll_interval": float(download_poll_interval),
                            "stable_ms": int(download_stable_ms),
                            "_baseline": download_baseline or [],
                        }
                        wd_dl = _watchdog_start(_step_timeout_seconds("download", {"timeout": download_timeout_s}))
                        try:
                            dl_tr = registry.dispatch("download", config, launcher, dl_args)
                        finally:
                            _watchdog_stop(wd_dl)

                        if not dl_tr.is_error and isinstance(dl_tr.data, dict):
                            download_result_payload = dl_tr.data
                            _collect_next(dl_tr.data)
                        elif dl_tr.is_error:
                            err_text = None
                            if dl_tr.content and dl_tr.content[0].type == "text":
                                err_text = dl_tr.content[0].text or ""
                            download_error = _extract_ctx_field(err_text or "", "error") or "Download capture failed"
                            download_suggestion = _extract_ctx_field(err_text or "", "suggestion")

                            # Best-effort mode: treat "no download" as a no-op (do not fail the step).
                            if (
                                not download_required
                                and isinstance(download_error, str)
                                and "timed out waiting for a new download" in download_error.lower()
                            ):
                                download_error = None
                                download_suggestion = None
                    except Exception as exc:  # noqa: BLE001
                        download_error = str(exc) or "Download capture failed"

                # Emergency: if CDP is bricked (timeouts / endpoint unreachable), attempt recovery
                # and stop. Retrying the same action automatically can be unsafe (double-click/type),
                # so we recover deterministically and ask the agent to re-run the scenario.
                if tool_result.is_error and auto_recover:
                    err = None
                    if isinstance(tool_result.data, dict) and isinstance(tool_result.data.get("error"), str):
                        err = tool_result.data.get("error")
                    if _is_cdp_brick(err):
                        rec = registry.dispatch(
                            "browser",
                            config,
                            launcher,
                            {"action": "recover", "hard": recover_hard, "timeout": recover_timeout},
                        )
                        return ToolResult.error(
                            "CDP brick detected during flow; attempted recovery",
                            tool="flow",
                            suggestion=f"Re-run the same run/actions after recovery (resume hint: start_at={i})",
                            details={
                                "failedStep": {"i": i, "tool": display_tool, "resolvedTool": tool_name},
                                "error": err,
                                "recovery": rec.data if isinstance(rec.data, dict) else None,
                            },
                        )

                ok = not tool_result.is_error
                download_detected = False
                if isinstance(download_result_payload, dict) and isinstance(
                    download_result_payload.get("download"), dict
                ):
                    download_detected = True
                if ok and want_download and download_required and not download_detected:
                    ok = False
                resolved_note = _step_note(tool_name, tool_args)
                note = resolved_note
                entry: dict[str, Any] = {"i": i, "tool": display_tool, "ok": ok, **({"note": note} if note else {})}
                if meta and meta.get("label"):
                    entry["label"] = meta["label"]
                if display_tool == "act":
                    if act_ref:
                        entry["ref"] = act_ref
                    entry["resolvedTool"] = tool_name
                    if act_healed:
                        entry["healed"] = True

                if attempt > 1:
                    entry["attempts"] = attempt
                    if overlay_dismissed:
                        entry["overlayDismissed"] = True

                # Optional: export selected scalar fields from raw tool payload.
                # This keeps flow cognitively-cheap while still allowing stateful workflows
                # (e.g., export cursor / artifact.id / tabId).
                export_spec = meta.get("export") if isinstance(meta, dict) else None
                if ok and isinstance(export_spec, dict) and tool_result.data is not None:
                    exported: dict[str, Any] = {}
                    for out_key, path in export_spec.items():
                        if not isinstance(out_key, str) or not out_key.strip():
                            continue
                        if not isinstance(path, str) or not path.strip():
                            continue
                        val = _extract_path(tool_result.data, path)
                        if val is _MISSING:
                            continue
                        if val is None or isinstance(val, (str, int, float, bool)):
                            exported[out_key] = val
                    if exported:
                        entry["export"] = exported
                        # Persist exports for later step interpolation (single-call pipelines).
                        for k, v in exported.items():
                            flow_vars[k] = v

                if tool_result.is_error:
                    err_text = None
                    if tool_result.content and tool_result.content[0].type == "text":
                        err_text = tool_result.content[0].text or ""
                    message = _extract_ctx_field(err_text or "", "error") or "Tool failed"
                    suggestion = _extract_ctx_field(err_text or "", "suggestion")
                    entry["error"] = message
                    if suggestion:
                        entry["suggestion"] = suggestion

                    is_optional = bool(meta and bool(meta.get("optional")))
                    if is_optional:
                        entry["optional"] = True
                    else:
                        first_error = first_error or {"i": i, "tool": tool_name, "error": message}
                        if stop_on_error:
                            step_summaries.append(entry)
                            break
                else:
                    # Attach auto-download results (cognitive-cheap): only surface when a download was detected.
                    if download_detected and isinstance(download_result_payload, dict):
                        dl = (
                            download_result_payload.get("download")
                            if isinstance(download_result_payload.get("download"), dict)
                            else None
                        )
                        art = (
                            download_result_payload.get("artifact")
                            if isinstance(download_result_payload.get("artifact"), dict)
                            else None
                        )
                        payload: dict[str, Any] = {}
                        if isinstance(dl, dict):
                            if isinstance(dl.get("fileName"), str):
                                payload["fileName"] = dl.get("fileName")
                            if isinstance(dl.get("bytes"), int):
                                payload["bytes"] = dl.get("bytes")
                            if isinstance(dl.get("mimeType"), str):
                                payload["mimeType"] = dl.get("mimeType")
                            if isinstance(dl.get("sha256"), str):
                                payload["sha256"] = dl.get("sha256")
                        if isinstance(art, dict) and isinstance(art.get("id"), str):
                            payload["artifact"] = {
                                "id": art.get("id"),
                                **({"mimeType": art.get("mimeType")} if isinstance(art.get("mimeType"), str) else {}),
                                **({"bytes": art.get("bytes")} if isinstance(art.get("bytes"), int) else {}),
                                **({"sha256": art.get("sha256")} if isinstance(art.get("sha256"), str) else {}),
                            }
                        if payload:
                            entry["download"] = payload

                    # Required download missing: promote to a step failure (deterministic).
                    if want_download and download_required and not download_detected:
                        entry["error"] = "Download expected but not detected"
                        if download_error:
                            entry["details"] = {"downloadError": download_error}
                        if download_suggestion:
                            entry["suggestion"] = download_suggestion
                        first_error = first_error or {"i": i, "tool": tool_name, "error": entry["error"]}
                        if stop_on_error:
                            step_summaries.append(entry)
                            break

                # Optional per-step proof (must be cheap and bounded).
                if step_proof and step_cursor is not None:
                    try:
                        # Avoid any extra CDP/Runtime probes while a dialog is open.
                        # (Dialogs can open right after a step returns: setTimeout(alert) race.)
                        with suppress(Exception):
                            _drain_and_ingest_dialog_events()
                        try:
                            tab_id = _session_manager.tab_id
                            t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                            if t0 is not None and getattr(t0, "dialog_open", False):
                                accept = auto_dialog == "accept"
                                if auto_dialog in {"dismiss", "accept"} and _close_dialog_best_effort(
                                    accept=bool(accept),
                                    max_wait_s=min(1.5, action_timeout_s),
                                ):
                                    dialogs_auto_handled += 1
                        except Exception:
                            pass
                        proof = _build_step_proof(
                            since_ms=int(step_cursor),
                            tool_name=tool_name,
                            tool_args={"i": i, **tool_args},
                            payload=tool_result.data,
                        )
                        if isinstance(proof, dict):
                            entry["proof"] = proof
                    except Exception:
                        pass

                # Step images (e.g., captcha screenshot) must not blow up the context window.
                # Store them as artifacts and bubble a drilldown hint.
                try:
                    img = None
                    if isinstance(tool_result.content, list):
                        for c in tool_result.content:
                            if (
                                getattr(c, "type", None) == "image"
                                and isinstance(getattr(c, "data", None), str)
                                and c.data
                            ):
                                img = c
                                break
                    if img is not None:
                        mime = getattr(img, "mime_type", None) or "image/png"
                        ref = _artifact_store.put_image_b64(
                            kind="step_image",
                            data_b64=str(img.data),
                            mime_type=str(mime),
                            metadata={
                                "tool": display_tool,
                                "resolvedTool": tool_name if display_tool == "act" else None,
                                "i": i,
                                **(
                                    {"label": meta.get("label")} if isinstance(meta, dict) and meta.get("label") else {}
                                ),
                            },
                        )
                        hint = artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)
                        entry["imageArtifact"] = {
                            "id": ref.id,
                            "kind": ref.kind,
                            "mimeType": ref.mime_type,
                            "bytes": ref.bytes,
                            "createdAt": ref.created_at,
                        }
                        entry["next"] = [hint]
                        if hint not in collected_next and len(collected_next) < 8:
                            collected_next.append(hint)
                except Exception:
                    pass

                step_summaries.append(entry)

                # Post-step dialog guard: dialogs may open *after* a step returns (e.g., setTimeout(alert)).
                # If we proceed without handling, subsequent CDP calls (and final report) may hang.
                if tool_name not in {"dialog", "browser"}:
                    try:
                        tab_id = _session_manager.tab_id
                        _drain_and_ingest_dialog_events()

                        t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                        if t0 is not None and getattr(t0, "dialog_open", False):
                            meta_d = getattr(t0, "dialog_last", None)
                            dialog = meta_d if isinstance(meta_d, dict) else {}

                            handled_dialog = False
                            if auto_dialog in {"dismiss", "accept"}:
                                accept = auto_dialog == "accept"
                                handled_dialog = _close_dialog_best_effort(
                                    accept=bool(accept),
                                    max_wait_s=min(2.0, action_timeout_s),
                                )
                                if handled_dialog:
                                    dialogs_auto_handled += 1

                            if not handled_dialog:
                                # Stop deterministically: final report and next steps are unsafe under a blocking dialog.
                                toolset = str(os.environ.get("MCP_TOOLSET") or "").strip().lower()
                                is_v2 = toolset in {"v2", "northstar", "north-star"}
                                next_hint = (
                                    "dialog(accept=true)" if auto_dialog != "dismiss" else "dialog(accept=false)"
                                )
                                backup_hint = 'tabs(action="rescue")'
                                suggestion = (
                                    f"Re-run with a dialog action: run(actions=[{{dialog:{{accept:{'false' if auto_dialog == 'dismiss' else 'true'}}}}}])"
                                    if is_v2
                                    else f"Handle the dialog first: {next_hint} (backup: {backup_hint})"
                                )
                                err_entry = {
                                    "i": i,
                                    "tool": "dialog_guard",
                                    "ok": False,
                                    "error": "Blocking JS dialog is open",
                                    "details": {
                                        "type": dialog.get("type"),
                                        "message": dialog.get("message"),
                                        "url": dialog.get("url"),
                                    },
                                    "suggestion": suggestion,
                                    "next": [next_hint, backup_hint],
                                }
                                step_summaries.append(err_entry)
                                if next_hint not in collected_next and len(collected_next) < 8:
                                    collected_next.append(next_hint)
                                if backup_hint not in collected_next and len(collected_next) < 8:
                                    collected_next.append(backup_hint)
                                first_error = first_error or {
                                    "i": i,
                                    "tool": "dialog_guard",
                                    "error": "Blocking JS dialog is open",
                                }
                                if stop_on_error:
                                    break
                    except Exception:
                        pass

            duration_ms = int((_now() - started) * 1000)
            executed = len(step_summaries)
            succeeded = len([s for s in step_summaries if isinstance(s, dict) and s.get("ok") is True])
            planned_total = max(0, len(steps_raw) - start_at)
            completed = executed == planned_total and first_error is None

            def _trim_step_summaries(steps: list[dict[str, Any]], *, max_items: int = 8) -> list[dict[str, Any]]:
                """Keep flow outputs cognitively-cheap without losing critical info.

                Strategy:
                - If short: return as-is.
                - If long: keep {errors} + {first 2} + {last 2}, then clamp.
                """

                if len(steps) <= max_items:
                    return steps

                errors = [s for s in steps if isinstance(s, dict) and s.get("ok") is False]
                head = steps[:2]
                tail = steps[-2:]

                chosen_by_i: dict[int, dict[str, Any]] = {}
                for entry in [*errors, *head, *tail]:
                    if not isinstance(entry, dict):
                        continue
                    i = entry.get("i")
                    if isinstance(i, int):
                        chosen_by_i[i] = entry

                trimmed = [chosen_by_i[i] for i in sorted(chosen_by_i)]
                if len(trimmed) <= max_items:
                    return trimmed

                # Too many errors or overlaps: keep errors first, then head/tail.
                chosen_by_i = {}
                for entry in [*errors, *head, *tail]:
                    if not isinstance(entry, dict):
                        continue
                    i = entry.get("i")
                    if not isinstance(i, int):
                        continue
                    chosen_by_i[i] = entry
                    if len(chosen_by_i) >= max_items:
                        break
                trimmed = [chosen_by_i[i] for i in sorted(chosen_by_i)]
                return trimmed[:max_items]

            out: dict[str, Any] = {
                "ok": completed,
                "flow": {
                    "steps_total": planned_total,
                    "steps_executed": executed,
                    "succeeded": succeeded,
                    "failed": executed - succeeded,
                    "duration_ms": duration_ms,
                    "stopped_on_error": bool(first_error and stop_on_error),
                },
            }

            if start_at:
                out["flow"]["start_at"] = start_at

            if dialogs_auto_handled:
                # Keep it tiny; only present when non-zero.
                out["flow"]["dialogsAutoHandled"] = dialogs_auto_handled

            if first_error:
                out["error"] = first_error.get("error")
                out["failed_step"] = {"i": first_error.get("i"), "tool": first_error.get("tool")}

            if steps_output == "compact":
                # If there are many steps, store the full list off-context and keep
                # the visible output tiny and decision-centric.
                if len(step_summaries) > 8:
                    try:
                        ref = _artifact_store.put_json(
                            kind="flow_steps",
                            obj={"steps": step_summaries},
                            metadata={
                                "stepsTotal": len(step_summaries),
                                "stepsShown": min(8, len(step_summaries)),
                            },
                        )
                        steps_artifact = {
                            "id": ref.id,
                            "kind": ref.kind,
                            "mimeType": ref.mime_type,
                            "bytes": ref.bytes,
                            "createdAt": ref.created_at,
                        }
                        out["next"] = [artifact_get_hint(artifact_id=ref.id, offset=0, max_chars=4000)]
                    except Exception:
                        steps_artifact = None

                out["steps"] = _trim_step_summaries(step_summaries, max_items=8)
                if steps_artifact is not None:
                    out["stepsArtifact"] = steps_artifact
            elif steps_output == "errors":
                filtered = [s for s in step_summaries if isinstance(s, dict) and s.get("ok") is False]
                if filtered:
                    out["steps"] = filtered
            # steps_output == "none": omit steps entirely

            if baseline_cursor is not None:
                out["since"] = baseline_cursor

            # Merge step-level drilldown hints (e.g., artifacts) into the top-level response.
            if collected_next:
                merged: list[str] = []
                existing = out.get("next")
                if isinstance(existing, list):
                    for item in existing:
                        if isinstance(item, str) and item.strip() and item not in merged:
                            merged.append(item)
                for item in collected_next:
                    if item not in merged:
                        merged.append(item)
                    if len(merged) >= 10:
                        break
                if merged:
                    out["next"] = merged

            def _safe_final_call(timeout_s: float, fn):  # noqa: ANN001
                """Run a final/report helper under a bounded watchdog."""
                wd = _watchdog_start(float(timeout_s))
                try:
                    return fn()
                except _ActionTimeoutError:
                    return None
                except Exception:  # noqa: BLE001
                    if wd is not None and wd.fired.is_set():
                        return None
                    return None
                finally:
                    _watchdog_stop(wd)

            # Final dialog guard: dialogs can open after the last action (async timers).
            # Never let final snapshots hang on a blocking dialog.
            try:
                tab_id = _session_manager.tab_id
                _drain_and_ingest_dialog_events()
                t0 = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                if t0 is not None and getattr(t0, "dialog_open", False):
                    if auto_dialog in {"dismiss", "accept"}:
                        accept = auto_dialog == "accept"
                        if _close_dialog_best_effort(accept=bool(accept), max_wait_s=min(2.0, action_timeout_s)):
                            dialogs_auto_handled += 1
                    # If still open, skip final CDP-based snapshots; they are unsafe under a dialog.
                    t0b = _session_manager.get_telemetry(tab_id or "") if tab_id else None
                    if t0b is not None and getattr(t0b, "dialog_open", False):
                        out.setdefault("final", {})["dialogOpen"] = True  # type: ignore[index]
            except Exception:
                pass

            # Best-effort final context (kept compact by renderer).
            try:
                info = _safe_final_call(min(5.0, action_timeout_s), lambda: _tools.get_page_info(config))
                if isinstance(info, dict) and isinstance(info.get("pageInfo"), dict):
                    pi = info["pageInfo"]
                    out["final"] = {
                        "url": pi.get("url"),
                        "title": pi.get("title"),
                        "readyState": pi.get("readyState"),
                    }
            except Exception:
                pass

            def _triage_has_signal(payload: dict[str, Any]) -> bool:
                triage = payload.get("triage") if isinstance(payload, dict) else None
                if not isinstance(triage, dict):
                    return False
                summary = triage.get("summary")
                if isinstance(summary, dict):
                    for k in (
                        "consoleErrors",
                        "consoleWarnings",
                        "jsErrors",
                        "resourceErrors",
                        "unhandledRejections",
                        "failedRequests",
                    ):
                        v = summary.get(k)
                        if isinstance(v, (int, float)) and v > 0:
                            return True
                top = triage.get("top")
                return isinstance(top, list) and len(top) > 0

            def _diag_has_signal(payload: dict[str, Any]) -> bool:
                snap = payload.get("diagnostics") if isinstance(payload, dict) else None
                if not isinstance(snap, dict):
                    return False
                delta = snap.get("delta")
                if isinstance(delta, dict):
                    for k in ("console", "errors", "unhandledRejections", "network"):
                        v = delta.get(k)
                        if isinstance(v, (int, float)) and v > 0:
                            return True
                # Fallback: any non-empty arrays
                for k in ("console", "errors", "unhandledRejections", "network"):
                    v = snap.get(k)
                    if isinstance(v, list) and len(v) > 0:
                        return True
                return False

            error_happened = first_error is not None
            try:
                final_limit_triage = int(args.get("final_limit", 30))
            except Exception:
                final_limit_triage = 30
            try:
                final_limit_diag = int(args.get("final_limit", 50))
            except Exception:
                final_limit_diag = 50

            # Attach final context only if requested, plus extra attachments on error.
            want_triage = final == "triage" or (error_happened and triage_on_error)
            want_diag = final == "diagnostics" or (error_happened and diagnostics_on_error)
            want_audit = final == "audit"

            if want_triage:
                try:
                    triage_payload = _safe_final_call(
                        min(10.0, action_timeout_s),
                        lambda: _tools.get_page_triage(
                            config,
                            since=baseline_cursor if delta_final else None,
                            limit=final_limit_triage,
                        ),
                    )
                    if (
                        final == "triage"
                        and not error_happened
                        and delta_final
                        and isinstance(triage_payload, dict)
                        and not _triage_has_signal(triage_payload)
                    ):
                        # Success path, delta-only, no new signals: keep cursor only.
                        cur = triage_payload.get("cursor")
                        if cur is not None:
                            out["cursor"] = cur
                    else:
                        out["triage"] = triage_payload
                except Exception:
                    pass

            if want_diag:
                try:
                    diag_payload = _safe_final_call(
                        min(10.0, action_timeout_s),
                        lambda: _tools.get_page_diagnostics(
                            config,
                            since=baseline_cursor if delta_final else None,
                            limit=final_limit_diag,
                        ),
                    )
                    if final == "diagnostics" or error_happened or _diag_has_signal(diag_payload):
                        out["diagnostics"] = diag_payload
                except Exception:
                    pass

            if want_audit:
                try:
                    audit_payload = _safe_final_call(
                        min(15.0, action_timeout_s),
                        lambda: _tools.get_page_audit(
                            config,
                            since=baseline_cursor if delta_final else None,
                            limit=final_limit_triage,
                            clear=False,
                        ),
                    )
                    if isinstance(audit_payload, dict):
                        out["audit"] = audit_payload
                except Exception:
                    pass

            # High-signal Observe bundle (Tier-0 + best-effort perf), kept tiny and deterministic.
            try:
                final_obj = out.get("final") if isinstance(out.get("final"), dict) else None
                if isinstance(final_obj, dict):
                    tab_id = _session_manager.tab_id
                    snap = None
                    if isinstance(tab_id, str) and tab_id:
                        snap = _session_manager.tier0_snapshot(
                            tab_id,
                            since=baseline_cursor if delta_final else None,
                            offset=0,
                            limit=50,
                            url=final_obj.get("url") if isinstance(final_obj.get("url"), str) else None,
                            title=final_obj.get("title") if isinstance(final_obj.get("title"), str) else None,
                            ready_state=final_obj.get("readyState")
                            if isinstance(final_obj.get("readyState"), str)
                            else None,
                        )

                    if isinstance(snap, dict):
                        # Always surface a cursor for delta workflows (even in observe mode).
                        cur = snap.get("cursor")
                        if cur is not None and "cursor" not in out:
                            out["cursor"] = cur

                        summary = snap.get("summary") if isinstance(snap.get("summary"), dict) else {}
                        counts: dict[str, Any] = {}
                        for k in (
                            "consoleErrors",
                            "consoleWarnings",
                            "jsErrors",
                            "resourceErrors",
                            "unhandledRejections",
                            "failedRequests",
                        ):
                            v = summary.get(k)
                            if isinstance(v, (int, float)) and int(v) > 0:
                                counts[k] = int(v)

                        def _trunc(s: Any, n: int = 200) -> str | None:
                            if not isinstance(s, str):
                                return None
                            s2 = s.strip()
                            if not s2:
                                return None
                            return (s2[:n] + "…") if len(s2) > n else s2

                        last_err = _trunc(summary.get("lastError"))
                        if last_err:
                            counts["lastError"] = last_err

                        # Resources (HAR-lite): approximate, bounded, high-signal.
                        har = snap.get("harLite") if isinstance(snap.get("harLite"), list) else []
                        har_items = [h for h in har if isinstance(h, dict)]
                        bytes_total = 0
                        failed_har = 0
                        slowest: dict[str, Any] | None = None
                        largest: dict[str, Any] | None = None
                        for it in har_items:
                            if it.get("ok") is False:
                                failed_har += 1
                            b = it.get("encodedDataLength")
                            if isinstance(b, (int, float)) and b >= 0:
                                bytes_total += int(b)
                            d = it.get("durationMs")
                            if (
                                isinstance(d, (int, float))
                                and d >= 0
                                and (slowest is None or float(d) > float(slowest.get("durationMs") or -1))
                            ):
                                slowest = it
                            if (
                                isinstance(b, (int, float))
                                and b >= 0
                                and (largest is None or float(b) > float(largest.get("encodedDataLength") or -1))
                            ):
                                largest = it

                        resources: dict[str, Any] = {}
                        if har_items:
                            resources["harLiteCount"] = len(har_items)
                        if failed_har > 0:
                            resources["failed"] = failed_har
                        if bytes_total > 0:
                            resources["bytesApprox"] = bytes_total

                        def _pick_req(it: dict[str, Any], *, kind: str) -> dict[str, Any] | None:
                            url = _trunc(it.get("url"), 240)
                            if not url:
                                return None
                            out_it: dict[str, Any] = {"kind": kind, "url": url}
                            if isinstance(it.get("type"), str) and it.get("type"):
                                out_it["type"] = it.get("type")
                            if isinstance(it.get("status"), int):
                                out_it["status"] = it.get("status")
                            if isinstance(it.get("durationMs"), (int, float)) and it.get("durationMs") >= 0:
                                out_it["durationMs"] = int(it.get("durationMs"))
                            if (
                                isinstance(it.get("encodedDataLength"), (int, float))
                                and it.get("encodedDataLength") >= 0
                            ):
                                out_it["encodedDataLength"] = int(it.get("encodedDataLength"))
                            if isinstance(it.get("ok"), bool):
                                out_it["ok"] = bool(it.get("ok"))
                            return out_it

                        # Keep only truly notable samples to avoid noise.
                        if (
                            isinstance(slowest, dict)
                            and isinstance(slowest.get("durationMs"), (int, float))
                            and slowest.get("durationMs") >= 500
                        ):
                            picked = _pick_req(slowest, kind="slowest")
                            if isinstance(picked, dict):
                                resources["slowest"] = picked
                        if (
                            isinstance(largest, dict)
                            and isinstance(largest.get("encodedDataLength"), (int, float))
                            and largest.get("encodedDataLength") >= 100_000
                        ):
                            picked = _pick_req(largest, kind="largest")
                            if isinstance(picked, dict):
                                resources["largest"] = picked

                        # Insights: 1–3 prioritized items.
                        insights: list[dict[str, Any]] = []
                        if snap.get("dialogOpen") is True:
                            d0 = snap.get("dialog") if isinstance(snap.get("dialog"), dict) else {}
                            msg = _trunc(d0.get("message"))
                            dtype = _trunc(d0.get("type"), 40)
                            insights.append(
                                {
                                    "severity": "error",
                                    "kind": "dialog_open",
                                    "message": _trunc(
                                        f"{dtype}: {msg}" if dtype and msg else (msg or dtype or "Dialog is open")
                                    ),
                                    **(
                                        {"url": d0.get("url")}
                                        if isinstance(d0.get("url"), str) and d0.get("url")
                                        else {}
                                    ),
                                }
                            )
                            if isinstance(d0, dict) and d0:
                                final_obj["dialog"] = d0

                        if last_err:
                            insights.append({"severity": "error", "kind": "js_error", "message": last_err})

                        network = snap.get("network") if isinstance(snap.get("network"), list) else []
                        for ev in network:
                            if not isinstance(ev, dict):
                                continue
                            url = _trunc(ev.get("url"), 240)
                            if not url:
                                continue
                            status = ev.get("status") if isinstance(ev.get("status"), int) else None
                            err_text = _trunc(ev.get("errorText"), 120)
                            msg = f"{status} {url}" if isinstance(status, int) else url
                            if err_text:
                                msg = f"{msg} ({err_text})"
                            insights.append(
                                {
                                    "severity": "error",
                                    "kind": "failed_request",
                                    "message": _trunc(msg, 240) or url,
                                    **({"status": status} if isinstance(status, int) else {}),
                                }
                            )
                            break

                        if not any(i.get("kind") == "failed_request" for i in insights) and isinstance(
                            resources.get("slowest"), dict
                        ):
                            s = resources.get("slowest")
                            insights.append(
                                {
                                    "severity": "warn",
                                    "kind": "slow_request",
                                    "message": _trunc(f"{s.get('durationMs')}ms {s.get('url')}", 240),
                                }
                            )

                        # Performance (best-effort; never block on dialogs).
                        perf: dict[str, Any] = {}
                        try:
                            if snap.get("dialogOpen") is not True:
                                # Wrap perf probes in a tiny watchdog: never hang the flow end.
                                old = _watchdog_start(1.2)
                                try:
                                    # Navigation timings + Long Tasks via Runtime (best-effort).
                                    nav = shared_sess.eval_js(
                                        (
                                            "(() => {"
                                            "  try {"
                                            "    const out = {};"
                                            "    const e = (performance && performance.getEntriesByType) ? performance.getEntriesByType('navigation') : [];"
                                            "    const n = e && e.length ? e[0] : null;"
                                            "    if (n) {"
                                            "      out.nav = {"
                                            "        ttfb: n.responseStart - n.startTime,"
                                            "        dcl: n.domContentLoadedEventEnd - n.startTime,"
                                            "        load: n.loadEventEnd - n.startTime,"
                                            "      };"
                                            "    } else {"
                                            "      const t = performance && performance.timing ? performance.timing : null;"
                                            "      if (t && t.navigationStart) {"
                                            "        out.nav = {"
                                            "          ttfb: t.responseStart - t.navigationStart,"
                                            "          dcl: t.domContentLoadedEventEnd - t.navigationStart,"
                                            "          load: t.loadEventEnd - t.navigationStart,"
                                            "        };"
                                            "      }"
                                            "    }"
                                            "    try {"
                                            "      const lt = (performance && performance.getEntriesByType) ? performance.getEntriesByType('longtask') : [];"
                                            "      if (lt && lt.length) {"
                                            "        const last = lt.slice(-50);"
                                            "        let total = 0;"
                                            "        let max = 0;"
                                            "        for (const x of last) {"
                                            "          const d = (x && typeof x.duration === 'number') ? x.duration : 0;"
                                            "          total += d;"
                                            "          if (d > max) max = d;"
                                            "        }"
                                            "        out.longTasks = { count: last.length, total, max };"
                                            "      }"
                                            "    } catch (e) {}"
                                            "    return out;"
                                            "  } catch (e) {}"
                                            "  return null;"
                                            "})()"
                                        ),
                                        timeout=1.0,
                                    )
                                    if isinstance(nav, dict):
                                        t = nav.get("nav") if isinstance(nav.get("nav"), dict) else None
                                        timing: dict[str, Any] = {}
                                        if isinstance(t, dict):
                                            for k_src, k_out in (
                                                ("ttfb", "ttfb_ms"),
                                                ("dcl", "domContentLoaded_ms"),
                                                ("load", "load_ms"),
                                            ):
                                                v = t.get(k_src)
                                                if isinstance(v, (int, float)) and v >= 0:
                                                    timing[k_out] = int(round(float(v)))
                                        if timing:
                                            perf["timing"] = timing
                                        lt = nav.get("longTasks") if isinstance(nav.get("longTasks"), dict) else None
                                        if isinstance(lt, dict):
                                            lt_out: dict[str, Any] = {}
                                            if isinstance(lt.get("count"), (int, float)) and lt.get("count") > 0:
                                                lt_out["count"] = int(lt.get("count"))
                                            for k_src, k_out in (("total", "total_ms"), ("max", "max_ms")):
                                                v = lt.get(k_src)
                                                if isinstance(v, (int, float)) and v >= 0:
                                                    lt_out[k_out] = int(round(float(v)))
                                            if lt_out:
                                                perf["longTasks"] = lt_out
                                finally:
                                    _watchdog_stop(old)
                        except Exception:
                            perf = {}

                        if counts:
                            final_obj["summary"] = counts
                        if insights:
                            final_obj["insights"] = insights[:3]
                        if resources:
                            final_obj["resources"] = resources
                        if perf:
                            final_obj["performance"] = perf

                        final_obj["signal"] = bool(
                            counts or insights or resources or perf or snap.get("dialogOpen") is True
                        )
            except Exception:
                pass

            attach_screenshot = with_screenshot or (error_happened and screenshot_on_error)
            if attach_screenshot:
                from .ai_format import render_ctx_markdown

                shot = _tools.screenshot(config)
                data = shot.get("content_b64") or shot.get("data", "")
                return ToolResult.with_image(render_ctx_markdown(out), data, "image/png", data=out)

            return ToolResult.json(out)

    registry.register("flow", handle_flow, True)

    def handle_run(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
        """North Star v2: OAVR runner (Observe → Act → Verify → Report).

        Implementation note:
        - Reuses the proven `flow` engine for execution + shared-session stability.
        - Shapes output into a run-centric report (actions + proof) with low noise by default.
        """
        actions_raw = args.get("actions")
        if not isinstance(actions_raw, list) or not actions_raw:
            actions_raw = args.get("steps")  # deprecated alias
        if not isinstance(actions_raw, list) or not actions_raw:
            return ToolResult.error(
                "Missing or empty 'actions' array",
                tool="run",
                suggestion="Provide actions=[{tool:'navigate', args:{url:'...'}}, ...] or actions=[{navigate:{url:'...'}}, ...]",
            )

        # Default to an "observe" snapshot (Tier-0, low noise, fast).
        report = str(args.get("report", "observe") or "observe")
        delta_report = bool(args.get("delta_report", True))
        actions_output = str(args.get("actions_output", "compact") or "compact").lower()
        proof = bool(args.get("proof", True))
        proof_screenshot = str(args.get("proof_screenshot", "artifact") or "artifact").lower()
        if proof_screenshot not in {"none", "artifact"}:
            proof_screenshot = "artifact"
        screenshot_on_ambiguity = bool(args.get("screenshot_on_ambiguity", True))

        # Safety: irreversible guard (deterministic, explicit only).
        confirm_irreversible = bool(args.get("confirm_irreversible", False))
        blocked: list[dict[str, Any]] = []
        for i, step in enumerate(actions_raw):
            if not isinstance(step, dict):
                continue
            if step.get("irreversible") is not True:
                continue
            tool_name = step.get("tool") if isinstance(step.get("tool"), str) else None
            blocked.append({"i": i, **({"tool": tool_name} if tool_name else {})})

        if blocked and not confirm_irreversible:
            return ToolResult.error(
                "Blocked irreversible action(s) (confirmation required)",
                tool="run",
                suggestion="Re-run with confirm_irreversible=true if you have explicit user approval",
                details={"blocked": blocked},
            )

        # Execute via flow (shared-session, delta cursor, screenshot wiring already battle-tested).
        flow_args = {
            "steps": actions_raw,
            "start_at": args.get("start_at", 0),
            "stop_on_error": bool(args.get("stop_on_error", True)),
            "delta_final": delta_report,
            "steps_output": actions_output,
            "screenshot_on_error": bool(args.get("screenshot_on_error", False)),
            "triage_on_error": True,
            "diagnostics_on_error": report == "diagnostics",
            "final": report,
            "final_limit": args.get("report_limit", 30),
            "with_screenshot": bool(args.get("with_screenshot", False)),
            # Internal: per-action proof to avoid extra tool calls.
            "step_proof": proof,
            "proof_screenshot": proof_screenshot,
            "screenshot_on_ambiguity": screenshot_on_ambiguity,
            # Robustness: auto dialog handling + CDP recovery (bounded).
            "auto_dialog": args.get("auto_dialog", "auto"),
            "auto_recover": bool(args.get("auto_recover", True)),
            "max_recoveries": args.get("max_recoveries", 1),
            "recover_hard": bool(args.get("recover_hard", False)),
            "recover_timeout": args.get("recover_timeout", 5.0),
            "action_timeout": args.get("action_timeout", 30.0),
            # UX: auto-capture downloads without an explicit download step.
            "auto_download": bool(args.get("auto_download", False)),
            "auto_download_timeout": args.get("auto_download_timeout", 3.0),
        }

        # Soft recovery loop (no Chrome restart by default): if flow detects a CDP brick, it
        # performs recovery and returns an error with a resume hint. run() should continue
        # executing remaining actions without requiring an extra user/tool call.
        try:
            max_rec = int(args.get("max_recoveries", 1))
        except Exception:
            max_rec = 1
        max_rec = max(0, min(max_rec, 5))

        recoveries: list[dict[str, Any]] = []
        start_at = flow_args.get("start_at", 0)
        try:
            start_at = int(start_at)
        except Exception:
            start_at = 0
        start_at = max(0, start_at)

        flow_res: ToolResult | None = None
        for _attempt in range(max_rec + 1):
            flow_args["start_at"] = start_at
            flow_res = handle_flow(config, launcher, flow_args)

            if not flow_res.is_error and isinstance(flow_res.data, dict):
                break

            # Not recoverable: return the error as-is.
            if not isinstance(getattr(flow_res, "data", None), dict):
                return flow_res

            data = flow_res.data
            err = data.get("error")
            details = data.get("details") if isinstance(data.get("details"), dict) else {}
            failed = details.get("failedStep") if isinstance(details.get("failedStep"), dict) else None
            recovery = details.get("recovery") if isinstance(details.get("recovery"), dict) else None

            # Heuristic: only auto-continue on explicit CDP brick recovery errors.
            if not (isinstance(err, str) and "cdp brick detected" in err.lower()):
                return flow_res

            i = failed.get("i") if isinstance(failed, dict) else None
            if not isinstance(i, int):
                return flow_res

            recoveries.append(
                {
                    "failedAction": {
                        "i": i,
                        "tool": failed.get("tool") if isinstance(failed.get("tool"), str) else None,
                    }
                    if isinstance(failed, dict)
                    else {"i": i},
                    **({"recovery": recovery} if recovery is not None else {}),
                }
            )

            # Resume from the next action. Do not retry the failed one automatically (could be unsafe).
            start_at = i + 1

            # If we've exhausted actions, stop.
            if start_at >= len(actions_raw):
                return flow_res

        if flow_res is None or flow_res.is_error or not isinstance(flow_res.data, dict):
            return flow_res or ToolResult.error("run() failed to execute actions", tool="run")

        raw = flow_res.data

        # Transform: flow → run
        out: dict[str, Any] = {"ok": bool(raw.get("ok"))}
        goal = args.get("goal")
        if isinstance(goal, str) and goal.strip():
            out["goal"] = goal.strip()

        flow_stats = raw.get("flow") if isinstance(raw.get("flow"), dict) else {}
        out["run"] = {
            "actions_total": flow_stats.get("steps_total"),
            "actions_executed": flow_stats.get("steps_executed"),
            "succeeded": flow_stats.get("succeeded"),
            "failed": flow_stats.get("failed"),
            "duration_ms": flow_stats.get("duration_ms"),
            "stopped_on_error": flow_stats.get("stopped_on_error"),
            **({"recoveries": len(recoveries)} if recoveries else {}),
        }
        if recoveries:
            out["run"]["recoveryAttempts"] = recoveries

        if "since" in raw:
            out["since"] = raw.get("since")

        if raw.get("error"):
            out["error"] = raw.get("error")
        if isinstance(raw.get("failed_step"), dict):
            out["failed_action"] = raw.get("failed_step")

        if isinstance(raw.get("steps"), list):
            out["actions"] = raw.get("steps")
        if isinstance(raw.get("stepsArtifact"), dict):
            out["actionsArtifact"] = raw.get("stepsArtifact")
        if isinstance(raw.get("next"), list):
            out["next"] = raw.get("next")

        observe = raw.get("final") if isinstance(raw.get("final"), dict) else None
        if observe is not None:
            out["observe"] = observe

        report_payload: dict[str, Any] = {}
        if "cursor" in raw:
            report_payload["cursor"] = raw.get("cursor")
        if isinstance(raw.get("triage"), dict):
            report_payload["triage"] = raw.get("triage")
        if isinstance(raw.get("diagnostics"), dict):
            report_payload["diagnostics"] = raw.get("diagnostics")
        if isinstance(raw.get("audit"), dict):
            report_payload["audit"] = raw.get("audit")
        if report_payload:
            out["report"] = report_payload

        # Preserve screenshot if the final flow attempt attached one.
        if len(flow_res.content) >= 2 and flow_res.content[1].type == "image":
            from .ai_format import render_ctx_markdown

            img = flow_res.content[1]
            return ToolResult.with_image(
                render_ctx_markdown(out),
                img.data or "",
                img.mime_type or "image/png",
                data=out,
            )

        return ToolResult.json(out)

    registry.register("run", handle_run, True)
    logger.info("Registered %d tool handlers", len(registry))
    return registry
