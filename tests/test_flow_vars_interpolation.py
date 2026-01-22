from __future__ import annotations

from contextlib import contextmanager

import pytest


def _install_hermetic_flow_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared mocks so flow/run tests don't require a real browser."""
    from mcp_servers.browser.session import session_manager

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

    @contextmanager
    def fake_shared_session(_cfg, timeout: float = 5.0):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(
        session_manager, "tier0_snapshot", lambda *_a, **_k: {"cursor": 1, "summary": {}, "harLite": []}
    )
    session_manager._session_tab_id = "tab1"  # best-effort for code paths that read tab_id

    # flow() always tries to attach a final get_page_info() snapshot; patch it to avoid CDP.
    from mcp_servers.browser import tools as tools_module

    monkeypatch.setattr(
        tools_module,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "about:blank", "title": "Dummy", "readyState": "complete"}},
    )


def test_flow_export_interpolates_later_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow should persist export scalars and interpolate them in later steps."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, dict(arguments or {})))
        if name == "page":
            return ToolResult.json({"cursor": 123, "artifact": {"id": "art_abc"}})
        if name == "wait":
            assert arguments.get("timeout") == 123  # exact placeholder keeps int type
            return ToolResult.json({"ok": True})
        if name == "navigate":
            assert arguments.get("url") == "https://example.test/art_abc"
            return ToolResult.json({"ok": True})
        raise AssertionError(f"Unexpected dispatch: {name}")

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "tool": "page",
                    "args": {"detail": "triage"},
                    "export": {"cursor": "cursor", "artId": "artifact.id"},
                },
                {"tool": "wait", "args": {"for": "navigation", "timeout": "{{cursor}}"}},
                {"tool": "navigate", "args": {"url": "https://example.test/{{artId}}"}},
            ],
            "final": "none",
            "auto_recover": False,
        },
    )

    assert not res.is_error
    assert calls[0][0] == "page"
    assert calls[1][0] == "wait"
    assert calls[2][0] == "navigate"


def test_flow_missing_var_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow should fail-fast with a helpful error when a referenced var is missing."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry

    _install_hermetic_flow_mocks(monkeypatch)

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        raise AssertionError(f"dispatch should not be called (missing vars should fail before tool call): {name}")

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"tool": "wait", "args": {"for": "navigation", "timeout": "{{missingVar}}"}}],
            "final": "none",
            "auto_recover": False,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    entry = steps[0]
    assert isinstance(entry, dict)
    assert entry.get("ok") is False
    assert entry.get("error") == "Missing flow variable"
    details = entry.get("details")
    assert isinstance(details, dict)
    assert details.get("var") == "missingVar"
