from __future__ import annotations

from typing import Any

from mcp_servers.browser.session import BrowserSession


def test_eval_js_does_not_use_repl_mode() -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []

    class DummyConn:
        def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            calls.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"type": "number", "value": 123}}
            return {}

    session = BrowserSession(DummyConn(), tab_id="t1")
    value = session.eval_js("1 + 2")
    assert value == 123

    # Expect a Runtime.evaluate call with awaitPromise+returnByValue and no replMode.
    eval_calls = [(m, p) for (m, p) in calls if m == "Runtime.evaluate"]
    assert len(eval_calls) == 1
    params = eval_calls[0][1] or {}
    assert params.get("awaitPromise") is True
    assert params.get("returnByValue") is True
    assert "replMode" not in params


def test_eval_js_maps_undefined_to_none() -> None:
    class DummyConn:
        def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ARG002
            if method == "Runtime.evaluate":
                return {"result": {"type": "undefined"}}
            return {}

    session = BrowserSession(DummyConn(), tab_id="t1")
    assert session.eval_js("globalThis.__nope && 1") is None


def test_eval_js_maps_null_to_none() -> None:
    class DummyConn:
        def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ARG002
            if method == "Runtime.evaluate":
                return {"result": {"type": "object", "subtype": "null"}}
            return {}

    session = BrowserSession(DummyConn(), tab_id="t1")
    assert session.eval_js("null") is None
