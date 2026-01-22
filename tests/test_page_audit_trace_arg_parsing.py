from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_page_audit_trace_parses_json_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Some MCP clients coerce JSON objects into strings. Ensure page(detail="audit", trace="{}")
    still applies the trace configuration.
    """
    import mcp_servers.browser.tools as tools
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield None, {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    session_manager.recover_reset()
    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)

    audit_payload = {"audit": {}, "cursor": 1_000_000, "duration_ms": 1, "sessionTabId": "tab1", "target": "tab1"}
    monkeypatch.setattr(tools, "get_page_audit", lambda *a, **k: audit_payload)

    captured: dict[str, object] = {}

    def fake_build_net_trace(_cfg: BrowserConfig, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {
            "trace": {
                "cursor": 1_000_000,
                "filters": {"capture": kwargs.get("capture"), "include": kwargs.get("include")},
                "items": [],
            },
            "artifact": {"id": "trace1", "kind": "net_trace", "mimeType": "application/json", "bytes": 1},
            "next": [],
        }

    import mcp_servers.browser.net_trace as net_trace

    monkeypatch.setattr(net_trace, "build_net_trace", fake_build_net_trace)

    registry = create_default_registry()
    handler, _requires_browser = registry.get("page")  # type: ignore[assignment]

    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={"detail": "audit", "trace": '{"capture":"full","include":"api/","limit":5}'},
    )

    assert not res.is_error
    assert captured.get("capture") == "full"
    assert captured.get("include") == "api/"
