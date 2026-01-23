from __future__ import annotations

import pytest


def test_page_default_v2_uses_map(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry

    monkeypatch.setenv("MCP_TOOLSET", "v2")

    map_payload = {"map": {"page": {"url": "about:blank"}, "actions": {"items": []}}, "cursor": 1}
    monkeypatch.setattr(tools, "get_page_map", lambda *_a, **_k: map_payload)

    registry = create_default_registry()
    handler, _requires_browser = registry.get("page")  # type: ignore[assignment]

    cfg = BrowserConfig.from_env()
    res = handler(cfg, launcher=None, args={})

    assert not res.is_error
    assert res.data == map_payload
