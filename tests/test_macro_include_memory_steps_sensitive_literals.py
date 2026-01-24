from __future__ import annotations

from contextlib import contextmanager

import pytest


def _install_hermetic_flow_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic mocks so flow tests don't require a real browser."""
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg, timeout: float = 5.0):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(
        session_manager,
        "tier0_snapshot",
        lambda *a, **k: {"cursor": 1_000_000, "summary": {}, "harLite": [], "network": [], "dialogOpen": False},
    )
    session_manager._session_tab_id = "tab1"


def test_include_memory_steps_refuses_sensitive_literals_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)

    # Step list that would be redacted by the runbook sanitizer.
    session_manager.memory_set(key="rb", value=[{"type": {"text": "hello"}}], max_bytes=20000, max_keys=200)

    cfg = BrowserConfig.from_env()
    registry = create_default_registry()
    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]

    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "include_memory_steps", "args": {"memory_key": "rb"}}}],
            "final": "none",
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    assert "sensitive literals" in str(res.data.get("error") or "").lower()

