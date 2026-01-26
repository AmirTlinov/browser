"""`run` tool handler (North Star): OAVR runner built on top of `flow`.

Kept out of `server/registry.py` so registry stays wiring-only.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ..types import ToolResult
from ..reliability import parse_policy_args, policy_summary

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher
    from ..dispatch import HandlerFunc


def make_run_handler(flow_handler: "HandlerFunc") -> "HandlerFunc":
    from ...session import session_manager as _session_manager

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

        policy, args_norm, warnings, errors = parse_policy_args(args)
        if errors:
            return ToolResult.error(
                "Invalid run parameters (strict_params=true)",
                tool="run",
                suggestion="; ".join(errors),
                details={"errors": errors},
            )
        args = args_norm

        # Default report selection:
        # - v1/default toolset: observe (Tier-0, low noise, fast)
        # - v2 toolset: map (actions-first)
        report_arg = args.get("report")
        if report_arg is None:
            toolset = str(os.environ.get("MCP_TOOLSET") or "").strip().lower()
            is_v2 = toolset in {"v2", "northstar", "north-star"}
            report = "map" if is_v2 else "observe"
        else:
            report = str(report_arg or "observe")
        delta_report = bool(args.get("delta_report", True))
        actions_output = str(args.get("actions_output", "compact") or "compact").lower()
        proof = bool(args.get("proof", True))
        proof_screenshot = str(args.get("proof_screenshot", "artifact") or "artifact").lower()
        if proof_screenshot not in {"none", "artifact"}:
            proof_screenshot = "artifact"
        screenshot_on_ambiguity = bool(args.get("screenshot_on_ambiguity", True))

        record_memory_key = args.get("record_memory_key")
        record_mode = str(args.get("record_mode", "sanitized") or "sanitized").strip().lower()
        if record_mode not in {"sanitized", "raw"}:
            record_mode = "sanitized"
        record_on_failure = bool(args.get("record_on_failure", False))

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
            "auto_tab": bool(args.get("auto_tab", False)),
            "auto_affordances": bool(args.get("auto_affordances", True)),
            **({"timeout_profile": args.get("timeout_profile")} if args.get("timeout_profile") is not None else {}),
            **({"recover_timeout": args.get("recover_timeout")} if args.get("recover_timeout") is not None else {}),
            **({"action_timeout": args.get("action_timeout")} if args.get("action_timeout") is not None else {}),
            # UX: auto-capture downloads without an explicit download step.
            "auto_download": bool(args.get("auto_download", False)),
            **(
                {"auto_download_timeout": args.get("auto_download_timeout")}
                if args.get("auto_download_timeout") is not None
                else {}
            ),
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
            flow_res = flow_handler(config, launcher, flow_args)

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
            **({"toolCounts": flow_stats.get("toolCounts")} if isinstance(flow_stats.get("toolCounts"), dict) else {}),
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
        if isinstance(raw.get("map"), dict):
            report_payload["map"] = raw.get("map")
        if isinstance(raw.get("graph"), dict):
            report_payload["graph"] = raw.get("graph")
        if report_payload:
            out["report"] = report_payload

        if isinstance(record_memory_key, str) and record_memory_key.strip():
            key = record_memory_key.strip()
            should_record = bool(out.get("ok") is True or record_on_failure)
            try:
                from ...runbook import sanitize_runbook_steps

                if should_record:
                    if record_mode == "sanitized":
                        stored_steps, redacted = sanitize_runbook_steps([s for s in actions_raw if isinstance(s, dict)])
                    else:
                        stored_steps = [s for s in actions_raw if isinstance(s, dict)]
                        _san, redacted = sanitize_runbook_steps(stored_steps)

                    meta = _session_manager.memory_set(
                        key=key,
                        value=stored_steps,
                        max_bytes=200_000,
                        max_keys=500,
                    )
                    out["recording"] = {
                        "ok": True,
                        "key": key,
                        "mode": record_mode,
                        "steps": len(stored_steps),
                        **({"redacted": int(redacted)} if redacted else {}),
                        **({"sensitive": True} if isinstance(meta, dict) and meta.get("sensitive") is True else {}),
                    }
                else:
                    out["recording"] = {
                        "ok": False,
                        "key": key,
                        "mode": record_mode,
                        "skipped": True,
                        "reason": "run_failed",
                    }
            except Exception as exc:
                out["recording"] = {
                    "ok": False,
                    "key": key,
                    "mode": record_mode,
                    "error": str(exc) or "record failed",
                    "suggestion": "Prefer {{mem:...}} / {{param:...}} placeholders and keep runbooks small",
                }

        policy_info = policy_summary(policy, warnings)
        if policy_info:
            out["policy"] = policy_info

        # Preserve screenshot if the final flow attempt attached one.
        if len(flow_res.content) >= 2 and flow_res.content[1].type == "image":
            from ..ai_format import render_ctx_markdown

            img = flow_res.content[1]
            return ToolResult.with_image(
                render_ctx_markdown(out),
                img.data or "",
                img.mime_type or "image/png",
                data=out,
            )

        return ToolResult.json(out)

    return handle_run


__all__ = ["make_run_handler"]
