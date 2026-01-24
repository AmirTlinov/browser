from __future__ import annotations

import pytest


def test_runbook_save_list_get_delete() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    handler, _requires_browser = registry.get("runbook")  # type: ignore[assignment]

    res_save = handler(
        cfg,
        launcher=None,
        args={"action": "save", "key": "rb1", "steps": [{"click": {"text": "X"}}]},
    )
    assert not res_save.is_error
    assert isinstance(res_save.data, dict)
    assert res_save.data.get("ok") is True

    res_list = handler(cfg, launcher=None, args={"action": "list", "limit": 10})
    assert not res_list.is_error
    assert isinstance(res_list.data, dict)
    items = res_list.data.get("runbooks")
    assert isinstance(items, list)
    assert any(isinstance(it, dict) and it.get("key") == "rb1" and it.get("steps") == 1 for it in items)

    res_get = handler(cfg, launcher=None, args={"action": "get", "key": "rb1"})
    assert not res_get.is_error
    assert isinstance(res_get.data, dict)
    preview = res_get.data.get("preview")
    assert isinstance(preview, dict)
    assert preview.get("steps_total") == 1
    assert isinstance(preview.get("steps_preview"), list)

    res_del = handler(cfg, launcher=None, args={"action": "delete", "key": "rb1"})
    assert not res_del.is_error
    assert isinstance(res_del.data, dict)
    assert res_del.data.get("deleted") is True


def test_runbook_save_refuses_sensitive_literals_by_default() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()
    handler, _requires_browser = registry.get("runbook")  # type: ignore[assignment]

    res = handler(
        cfg,
        launcher=None,
        args={"action": "save", "key": "rb_sensitive", "steps": [{"type": {"text": "secret"}}]},
    )
    assert res.is_error is True

    res_ok = handler(
        cfg,
        launcher=None,
        args={"action": "save", "key": "rb_sensitive", "allow_sensitive": True, "steps": [{"type": {"text": "secret"}}]},
    )
    assert not res_ok.is_error
    assert isinstance(res_ok.data, dict)
    assert res_ok.data.get("ok") is True


def test_runbook_save_refuses_browser_memory_set_sensitive_key_by_default() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()
    handler, _requires_browser = registry.get("runbook")  # type: ignore[assignment]

    res = handler(
        cfg,
        launcher=None,
        args={
            "action": "save",
            "key": "rb_mem",
            "steps": [
                {"browser": {"action": "memory", "memory_action": "set", "key": "token", "value": "secret"}},
            ],
        },
    )
    assert res.is_error is True

def test_runbook_run_dispatches_to_run_with_include_memory_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    called: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        called.append((name, dict(arguments or {})))
        if name == "run":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("runbook")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={"action": "run", "key": "rb_run", "params": {"path": "x"}, "run_args": {"report": "none"}},
    )

    assert not res.is_error
    assert called and called[0][0] == "run"
    actions = called[0][1].get("actions")
    assert isinstance(actions, list) and actions
    macro = actions[0].get("macro") if isinstance(actions[0], dict) else None
    assert isinstance(macro, dict)
    assert macro.get("name") == "include_memory_steps"
    margs = macro.get("args")
    assert isinstance(margs, dict)
    assert margs.get("memory_key") == "rb_run"
    assert margs.get("params") == {"path": "x"}
