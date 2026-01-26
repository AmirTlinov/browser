from __future__ import annotations


def test_extract_strict_params_rejects_invalid_auto_expand() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.handlers.unified import handle_extract_content

    config = BrowserConfig.from_env()
    res = handle_extract_content(
        config,
        None,  # type: ignore[arg-type]
        {"auto_expand": "nope", "strict_params": True},
    )

    assert res.is_error
