from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest


def test_flow_watchdog_uses_abort_in_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """flow() must never wedge the server when a step blocks.

    Regression guard for a real-world failure mode:
    - A CDP operation can block inside websocket-client send()/recv() while a JS dialog is open.
    - The watchdog must break the socket via conn.abort() (not close()) so the handler thread
      returns in bounded time and the MCP server stays responsive.
    """
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.http_client import HttpClientError
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    abort_called = threading.Event()

    class DummyConn:
        def abort(self) -> None:
            abort_called.set()

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"
        conn = DummyConn()

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001, ARG002
            # Used by flow() for a tiny "now" cursor.
            if "Date.now" in expression:
                return 1_000_000
            return None

        def close(self) -> None:
            # Simulate a dialog-brick where websocket-client close() can hang or is unsafe.
            raise RuntimeError("close is not a safe breaker")

    @contextmanager
    def fake_shared_session(_cfg: BrowserConfig, timeout: float = 5.0):  # noqa: ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    # Keep the test hermetic: no real Chrome.
    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    session_manager._session_tab_id = "tab1"  # best-effort for code paths that read tab_id

    registry = create_default_registry()

    # Force a "blocked" step that only unblocks when abort() is called by the watchdog.
    real_dispatch = registry.dispatch

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001
        if name == "js":
            # Block until watchdog fires; then simulate the CDP failure we'd see after abort.
            abort_called.wait(timeout=5.0)
            raise HttpClientError("CDP response timed out")
        return real_dispatch(name, cfg, launcher, arguments)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    result_holder: list[object] = []

    def _runner() -> None:
        res = handler(
            cfg,
            launcher=None,  # dispatch is mocked; flow won't use launcher directly in this test
            args={
                "steps": [{"tool": "js", "args": {"code": "1"}}],
                "final": "none",
                "auto_recover": False,
                # Keep the watchdog tight to make this test fast.
                "action_timeout": 1.0,
            },
        )
        result_holder.append(res)

    t0 = time.time()
    th = threading.Thread(target=_runner, name="flow-test-thread", daemon=True)
    th.start()
    th.join(timeout=8.0)
    elapsed = time.time() - t0

    assert not th.is_alive(), "flow() should return in bounded time (thread watchdog path)"
    assert elapsed < 8.0
    assert abort_called.is_set(), "watchdog must use conn.abort() as the breaker"
    assert result_holder, "flow() should return a ToolResult"

    res = result_holder[0]
    assert hasattr(res, "is_error") and hasattr(res, "data")
    assert res.is_error is False  # flow returns ok:true with step errors embedded
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("ok") is False
    assert "timed out" in str(steps[0].get("error", "")).lower()
