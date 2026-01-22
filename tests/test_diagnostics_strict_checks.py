from __future__ import annotations

import time

import pytest


def test_ensure_diagnostics_requires_strict_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_diagnostics() must not treat truthy non-bool values as 'available'."""
    from mcp_servers.browser.diagnostics import DIAGNOSTICS_SCRIPT_SOURCE, DIAGNOSTICS_SCRIPT_VERSION
    from mcp_servers.browser.session import session_manager

    tab_id = "tab_diag_strict_1"
    session_manager._diagnostics_state.pop(tab_id, None)
    session_manager._bootstrap_scripts.pop(tab_id, None)

    injected: list[bool] = []
    check_calls: list[object] = []

    class DummySession:
        tab_id = ""

        def enable_page(self) -> None:
            return

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.addScriptToEvaluateOnNewDocument":
                return {"identifier": "script-1"}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if expression == DIAGNOSTICS_SCRIPT_SOURCE:
                injected.append(True)
                return None
            if "typeof globalThis.__mcpDiag.snapshot" in expression:
                # First check returns a truthy-but-not-True value (simulates old undefined/dict pitfall).
                check_calls.append(object())
                return {"type": "undefined"} if len(check_calls) == 1 else True
            return None

    monkeypatch.setenv("MCP_DIAGNOSTICS", "1")

    sess = DummySession()
    sess.tab_id = tab_id
    res = session_manager.ensure_diagnostics(sess)
    assert res.get("enabled") is True
    assert res.get("available") is True
    assert injected, "expected an explicit injection attempt when availability check isn't strict True"
    state = session_manager._diagnostics_state.get(tab_id)
    assert isinstance(state, dict)
    assert state.get("version") == DIAGNOSTICS_SCRIPT_VERSION
    assert state.get("available") is True


def test_ensure_diagnostics_cached_recheck_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cached 'available=true' must be revalidated via strict boolean checks."""
    from mcp_servers.browser.diagnostics import DIAGNOSTICS_SCRIPT_SOURCE, DIAGNOSTICS_SCRIPT_VERSION
    from mcp_servers.browser.session import session_manager

    tab_id = "tab_diag_strict_2"
    session_manager._bootstrap_scripts.pop(tab_id, None)
    session_manager._diagnostics_state[tab_id] = {
        "version": DIAGNOSTICS_SCRIPT_VERSION,
        "available": True,
        "scriptId": "script-1",
        "lastCheck": time.time(),
    }

    injected: list[bool] = []
    recheck_calls: list[object] = []

    class DummySession:
        tab_id = ""

        def enable_page(self) -> None:
            return

        def send(self, method: str, params=None):  # noqa: ANN001
            if method == "Page.addScriptToEvaluateOnNewDocument":
                return {"identifier": "script-1"}
            return {}

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if expression == DIAGNOSTICS_SCRIPT_SOURCE:
                injected.append(True)
                return None
            if "typeof globalThis.__mcpDiag.snapshot" in expression:
                recheck_calls.append(object())
                # First call is the cached re-check: return a truthy non-bool, which must NOT pass.
                return {"type": "undefined"} if len(recheck_calls) == 1 else True
            return None

    monkeypatch.setenv("MCP_DIAGNOSTICS", "1")

    sess = DummySession()
    sess.tab_id = tab_id
    res = session_manager.ensure_diagnostics(sess)
    assert res.get("enabled") is True
    assert res.get("available") is True
    assert res.get("cached") is not True
    assert injected, "expected reinstall path when cached availability re-check is not strict True"
