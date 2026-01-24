from __future__ import annotations

from contextlib import contextmanager

import pytest


def _install_hermetic_flow_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared mocks so flow/run recorder tests don't require a real browser."""
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


def test_flow_recorder_saves_sanitized_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"click": {"text": "X"}}],
            "final": "none",
            "record_memory_key": "rb_rec",
            "record_mode": "sanitized",
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    rec = res.data.get("recording")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True

    entry = session_manager.memory_get(key="rb_rec")
    assert isinstance(entry, dict)
    value = entry.get("value")
    assert isinstance(value, list) and value
    assert value[0].get("click", {}).get("text") == "X"


def test_flow_recorder_redacts_type_text_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "type":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"type": {"text": "secret"}}],
            "final": "none",
            "record_memory_key": "rb_redact",
            "record_mode": "sanitized",
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    rec = res.data.get("recording")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert int(rec.get("redacted") or 0) >= 1

    entry = session_manager.memory_get(key="rb_redact")
    assert isinstance(entry, dict)
    value = entry.get("value")
    assert isinstance(value, list) and value
    txt = value[0].get("type", {}).get("text")
    assert isinstance(txt, str) and "<redacted" in txt


def test_flow_recorder_redacts_browser_memory_set_sensitive_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "browser":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "browser": {
                        "action": "memory",
                        "memory_action": "set",
                        "key": "token",
                        "value": "secret",
                    }
                }
            ],
            "final": "none",
            "record_memory_key": "rb_mem",
            "record_mode": "sanitized",
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    rec = res.data.get("recording")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert int(rec.get("redacted") or 0) >= 1

    entry = session_manager.memory_get(key="rb_mem")
    assert isinstance(entry, dict)
    value = entry.get("value")
    assert isinstance(value, list) and value
    v = value[0].get("browser", {}).get("value")
    assert isinstance(v, str) and "<redacted" in v


def test_flow_recorder_keeps_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    session_manager.memory_set(key="pwd", value="secret", max_bytes=20000, max_keys=200)
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "type":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"type": {"text": "{{mem:pwd}}"}}],
            "final": "none",
            "record_memory_key": "rb_ph",
            "record_mode": "sanitized",
        },
    )

    assert not res.is_error
    entry = session_manager.memory_get(key="rb_ph")
    assert isinstance(entry, dict)
    value = entry.get("value")
    assert isinstance(value, list) and value
    assert value[0].get("type", {}).get("text") == "{{mem:pwd}}"


def test_flow_recorder_record_on_failure_still_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/start", "title": "Example"}},
    )

    cfg = BrowserConfig.from_env()
    registry = create_default_registry()
    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"assert": {"url": "/never"}}],
            "final": "none",
            "record_memory_key": "rb_fail",
            "record_on_failure": True,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    rec = res.data.get("recording")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    assert isinstance(session_manager.memory_get(key="rb_fail"), dict)


def test_run_recorder_writes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    cfg = BrowserConfig.from_env()
    registry = create_default_registry()

    def fake_dispatch(name: str, _cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("run")  # type: ignore[assignment]
    res = handler(
        cfg,
        launcher=None,
        args={
            "actions": [{"click": {"text": "X"}}],
            "report": "none",
            "record_memory_key": "rb_run",
            "record_mode": "sanitized",
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    rec = res.data.get("recording")
    assert isinstance(rec, dict)
    assert rec.get("ok") is True
    entry = session_manager.memory_get(key="rb_run")
    assert isinstance(entry, dict)
