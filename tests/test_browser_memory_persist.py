from __future__ import annotations

from pathlib import Path

import pytest


def test_browser_memory_save_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_AGENT_MEMORY_DIR", str(tmp_path))

    session_manager.recover_reset()
    session_manager.set_policy("permissive")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res_set = handler(
        cfg, launcher=None, args={"action": "memory", "memory_action": "set", "key": "foo", "value": "bar"}
    )
    assert not res_set.is_error

    res_save = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "save"})
    assert not res_save.is_error
    persisted = res_save.data.get("memory", {}).get("persisted")
    assert isinstance(persisted, dict) and persisted.get("ok") is True

    assert (tmp_path / "agent_memory.json").exists()

    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "clear"})

    res_load = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "load"})
    assert not res_load.is_error

    res_get = handler(
        cfg, launcher=None, args={"action": "memory", "memory_action": "get", "key": "foo", "reveal": True}
    )
    assert not res_get.is_error
    assert res_get.data.get("memory", {}).get("value") == "bar"


def test_browser_memory_save_excludes_sensitive_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_AGENT_MEMORY_DIR", str(tmp_path))

    session_manager.recover_reset()
    session_manager.set_policy("permissive")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "set", "key": "token", "value": "secret"})
    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "save"})
    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "clear"})
    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "load"})

    res_get = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "get", "key": "token"})
    assert not res_get.is_error
    assert res_get.data.get("memory", {}).get("found") is False


def test_browser_memory_save_load_sensitive_with_allow_sensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_AGENT_MEMORY_DIR", str(tmp_path))

    session_manager.recover_reset()
    session_manager.set_policy("permissive")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "set", "key": "token", "value": "secret"})
    res_save = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "save", "allow_sensitive": True})
    assert not res_save.is_error

    handler(cfg, launcher=None, args={"action": "memory", "memory_action": "clear"})
    res_load = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "load", "allow_sensitive": True})
    assert not res_load.is_error

    res_get = handler(
        cfg,
        launcher=None,
        args={"action": "memory", "memory_action": "get", "key": "token", "reveal": True},
    )
    assert not res_get.is_error
    assert res_get.data.get("memory", {}).get("value") == "secret"


def test_browser_memory_persist_flag_on_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_AGENT_MEMORY_DIR", str(tmp_path))

    session_manager.recover_reset()
    session_manager.set_policy("permissive")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res_set = handler(
        cfg,
        launcher=None,
        args={
            "action": "memory",
            "memory_action": "set",
            "key": "foo",
            "value": "bar",
            "persist": True,
        },
    )
    assert not res_set.is_error
    assert isinstance(res_set.data.get("memory", {}).get("persisted"), dict)
    assert (tmp_path / "agent_memory.json").exists()


def test_browser_memory_persist_strict_policy_blocks_save_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    monkeypatch.setenv("MCP_AGENT_MEMORY_DIR", str(tmp_path))

    session_manager.recover_reset()
    session_manager.set_policy("strict")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "save"})
    assert res.is_error
