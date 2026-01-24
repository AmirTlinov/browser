"""`runbook` tool handler: save/run/list/get/delete for step lists stored in agent memory.

Kept out of `server/registry.py` so registry stays wiring-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..types import ToolResult

if TYPE_CHECKING:
    from ...config import BrowserConfig
    from ...launcher import BrowserLauncher
    from ..dispatch import HandlerFunc, ToolRegistry


def make_runbook_handler(registry: "ToolRegistry") -> "HandlerFunc":
    from ...session import session_manager as _session_manager

    def handle_runbook(config: BrowserConfig, launcher: BrowserLauncher, args: dict[str, Any]) -> ToolResult:
        def _save(_cfg: BrowserConfig, _launcher: BrowserLauncher, a: dict[str, Any]) -> ToolResult:
            key = a.get("key")
            steps = a.get("steps")
            allow_sensitive = bool(a.get("allow_sensitive", False))
            if not (isinstance(key, str) and key.strip()):
                return ToolResult.error("'key' required", tool="runbook", suggestion="Provide key='runbook_name'")
            if not isinstance(steps, list) or not steps:
                return ToolResult.error(
                    "Missing or empty 'steps' array",
                    tool="runbook",
                    suggestion="Provide steps=[{navigate:{...}}, {click:{...}}, ...]",
                )
            steps_list = [s for s in steps if isinstance(s, dict)]
            if len(steps_list) != len(steps):
                return ToolResult.error(
                    "Invalid step list (non-object entries)",
                    tool="runbook",
                    suggestion="Ensure every step is an object like {click:{...}} or {tool:'click', args:{...}}",
                )

            if not allow_sensitive:
                from ...runbook import has_sensitive_literals

                if has_sensitive_literals(steps_list):
                    return ToolResult.error(
                        "Refusing to store runbook with sensitive literals",
                        tool="runbook",
                        suggestion="Use {{mem:...}} placeholders for secrets or re-run with allow_sensitive=true",
                    )

            try:
                meta = _session_manager.memory_set(key=key.strip(), value=steps_list, max_bytes=200_000, max_keys=500)
                return ToolResult.json(
                    {
                        "ok": True,
                        "action": "save",
                        "key": key.strip(),
                        "steps": len(steps_list),
                        **(
                            {"bytes": meta.get("bytes")}
                            if isinstance(meta, dict) and isinstance(meta.get("bytes"), int)
                            else {}
                        ),
                        **({"sensitive": True} if isinstance(meta, dict) and meta.get("sensitive") is True else {}),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult.error(str(exc) or "Failed to save runbook", tool="runbook")

        def _run(cfg: BrowserConfig, l: BrowserLauncher, a: dict[str, Any]) -> ToolResult:
            key = a.get("key")
            if not (isinstance(key, str) and key.strip()):
                return ToolResult.error("'key' required", tool="runbook", suggestion="Provide key='runbook_name'")
            params = a.get("params") if isinstance(a.get("params"), dict) else {}
            allow_sensitive = bool(a.get("allow_sensitive", False))
            run_args = a.get("run_args") if isinstance(a.get("run_args"), dict) else {}

            inner = dict(run_args)
            inner["actions"] = [
                {
                    "macro": {
                        "name": "include_memory_steps",
                        "args": {"memory_key": key.strip(), "params": params, "allow_sensitive": allow_sensitive},
                    }
                }
            ]
            if "goal" not in inner and isinstance(a.get("goal"), str) and a.get("goal").strip():
                inner["goal"] = str(a.get("goal")).strip()
            return registry.dispatch("run", cfg, l, inner)

        def _list(_cfg: BrowserConfig, _launcher: BrowserLauncher, a: dict[str, Any]) -> ToolResult:
            try:
                limit = int(a.get("limit", 20))
            except Exception:
                limit = 20
            limit = max(1, min(limit, 200))
            include_sensitive = bool(a.get("include_sensitive", False))

            items = _session_manager.memory_list()
            out_items: list[dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("sensitive") is True and not include_sensitive:
                    continue
                k = it.get("key")
                if not isinstance(k, str) or not k.strip():
                    continue
                entry = _session_manager.memory_get(key=k)
                value = entry.get("value") if isinstance(entry, dict) else None
                if not isinstance(value, list):
                    continue
                steps_list = [s for s in value if isinstance(s, dict)]
                if not steps_list or len(steps_list) != len(value):
                    continue
                out_items.append(
                    {
                        "key": k,
                        "steps": len(steps_list),
                        **({"bytes": it.get("bytes")} if isinstance(it.get("bytes"), int) else {}),
                        **({"updatedAt": it.get("updatedAt")} if isinstance(it.get("updatedAt"), int) else {}),
                        **({"sensitive": True} if it.get("sensitive") is True else {}),
                    }
                )
                if len(out_items) >= limit:
                    break
            return ToolResult.json({"ok": True, "action": "list", "runbooks": out_items, "total": len(out_items)})

        def _get(_cfg: BrowserConfig, _launcher: BrowserLauncher, a: dict[str, Any]) -> ToolResult:
            key = a.get("key")
            if not (isinstance(key, str) and key.strip()):
                return ToolResult.error("'key' required", tool="runbook", suggestion="Provide key='runbook_name'")
            allow_sensitive = bool(a.get("allow_sensitive", False))
            entry = _session_manager.memory_get(key=key.strip())
            if not isinstance(entry, dict):
                return ToolResult.error("Runbook not found", tool="runbook", suggestion="Use runbook(action='list')")
            if entry.get("sensitive") is True and not allow_sensitive:
                return ToolResult.error(
                    "Refusing to read a sensitive runbook key",
                    tool="runbook",
                    suggestion="Re-run with allow_sensitive=true only if you explicitly accept the risk",
                )
            value = entry.get("value")
            if not isinstance(value, list):
                return ToolResult.error("Memory value is not a runbook step list", tool="runbook")
            steps_list = [s for s in value if isinstance(s, dict)]
            if len(steps_list) != len(value) or not steps_list:
                return ToolResult.error("Invalid runbook step list", tool="runbook")
            from ...runbook import preview_runbook_steps

            preview = preview_runbook_steps(steps_list, limit=a.get("limit", 5))
            return ToolResult.json(
                {
                    "ok": True,
                    "action": "get",
                    "key": key.strip(),
                    **({"bytes": entry.get("bytes")} if isinstance(entry.get("bytes"), int) else {}),
                    **({"updatedAt": entry.get("updatedAt")} if isinstance(entry.get("updatedAt"), int) else {}),
                    **({"sensitive": True} if entry.get("sensitive") is True else {}),
                    "preview": preview,
                    "next": [f'runbook(action=\"run\", key=\"{key.strip()}\")'],
                }
            )

        def _delete(_cfg: BrowserConfig, _launcher: BrowserLauncher, a: dict[str, Any]) -> ToolResult:
            key = a.get("key")
            if not (isinstance(key, str) and key.strip()):
                return ToolResult.error("'key' required", tool="runbook", suggestion="Provide key='runbook_name'")
            deleted = bool(_session_manager.memory_delete(key=key.strip()))
            return ToolResult.json({"ok": deleted, "action": "delete", "deleted": deleted, "key": key.strip()})

        action = str(args.get("action", "list") or "list").strip().lower()
        handlers = {"save": _save, "run": _run, "list": _list, "get": _get, "delete": _delete}
        fn = handlers.get(action)
        if fn is None:
            return ToolResult.error(
                f"Unknown action: {action}",
                tool="runbook",
                suggestion="Use action='save' | 'run' | 'list' | 'get' | 'delete'",
            )
        return fn(config, launcher, args)

    return handle_runbook


__all__ = ["make_runbook_handler"]
