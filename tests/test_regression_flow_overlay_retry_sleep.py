from __future__ import annotations

import time
from contextlib import contextmanager

import pytest


def test_flow_overlay_retry_does_not_crash_on_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: flow() overlay retry must not NameError on sleep().

    We previously had `time.sleep(...)` in server/registry.py but imported time as `_time`,
    which crashed the whole run()/flow() pipeline at runtime.
    """

    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001, ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    # Keep the test hermetic: no real Chrome.
    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    session_manager._session_tab_id = "tab1"

    # Make the retry fast and side-effect free.
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    registry = create_default_registry()

    # Force the exact transient error gate: click -> ToolResult.error("Element not found").
    real_dispatch = registry.dispatch

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "click":
            return ToolResult.error("Element not found")
        return real_dispatch(name, cfg, launcher, arguments)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    res = handler(
        cfg,
        launcher=None,  # dispatch is mocked
        args={
            "steps": [{"tool": "click", "args": {"text": "nope"}}],
            "final": "none",
        },
    )

    # flow() returns ok:true with step errors embedded; it must not crash.
    assert res.is_error is False
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is False
