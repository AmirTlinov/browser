from __future__ import annotations


def test_flow_strict_params_rejects_invalid_auto_dialog() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry

    registry = create_default_registry()
    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]

    config = BrowserConfig.from_env()
    res = flow_handler(
        config,
        None,  # type: ignore[arg-type]
        {
            "steps": [{"js": {"code": "1 + 1"}}],
            "strict_params": True,
            "auto_dialog": "maybe",
        },
    )

    assert res.is_error
