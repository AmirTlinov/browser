from __future__ import annotations

import pytest


def test_browser_memory_set_list_get_delete_clear() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager.set_policy("permissive")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res_set = handler(
        cfg, launcher=None, args={"action": "memory", "memory_action": "set", "key": "foo", "value": "bar"}
    )
    assert not res_set.is_error
    assert isinstance(res_set.data, dict)
    assert res_set.data.get("memory_action") == "set"

    res_list = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "list"})
    assert not res_list.is_error
    keys = res_list.data.get("memory", {}).get("keys")
    assert isinstance(keys, list)
    assert any(isinstance(it, dict) and it.get("key") == "foo" for it in keys)

    res_get_default = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "get", "key": "foo"})
    assert not res_get_default.is_error
    mem = res_get_default.data.get("memory")
    assert isinstance(mem, dict)
    assert mem.get("found") is True
    assert "value" not in mem  # redacted by default

    res_get_reveal = handler(
        cfg,
        launcher=None,
        args={"action": "memory", "memory_action": "get", "key": "foo", "reveal": True, "memory_max_chars": 10},
    )
    assert not res_get_reveal.is_error
    mem2 = res_get_reveal.data.get("memory")
    assert isinstance(mem2, dict)
    assert mem2.get("value") == "bar"

    res_del = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "delete", "key": "foo"})
    assert not res_del.is_error
    assert res_del.data.get("memory", {}).get("deleted") in {True, False}

    res_clear = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "clear"})
    assert not res_clear.is_error
    assert isinstance(res_clear.data.get("memory", {}).get("cleared"), int)


def test_browser_memory_strict_policy_blocks_mutation() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()
    session_manager.set_policy("strict")

    registry = create_default_registry()
    handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(cfg, launcher=None, args={"action": "memory", "memory_action": "set", "key": "foo", "value": "bar"})
    assert res.is_error
