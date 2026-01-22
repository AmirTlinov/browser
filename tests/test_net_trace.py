from __future__ import annotations

import pytest


def test_build_net_trace_defaults_to_xhr_fetch_and_hides_urlfull(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.net_trace import build_net_trace
    from mcp_servers.browser.session import session_manager

    cfg = BrowserConfig.from_env()

    class _T0:  # minimal telemetry stub
        def __init__(self, done: dict[str, dict]) -> None:
            self._req_done = done

    done = {
        # insertion order matters; helper iterates newest-first (reversed)
        "1": {
            "type": "Document",
            "url": "https://example.com/",
            "method": "GET",
            "status": 200,
            "ok": True,
            "endTs": 10,
        },
        "2": {
            "type": "XHR",
            "url": "https://example.com/api/a",
            "urlFull": "https://example.com/api/a?secret=1",
            "method": "GET",
            "status": 200,
            "ok": True,
            "endTs": 20,
        },
        "3": {
            "type": "Fetch",
            "url": "https://example.com/api/b",
            "method": "POST",
            "status": 500,
            "ok": False,
            "endTs": 30,
        },
        "4": {
            "type": "Image",
            "url": "https://example.com/i.png",
            "method": "GET",
            "status": 200,
            "ok": True,
            "endTs": 40,
        },
    }

    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: _T0(done))

    out = build_net_trace(cfg, tab_id="tab1", capture="meta", limit=50)
    assert isinstance(out, dict)
    trace = out.get("trace")
    assert isinstance(trace, dict)

    items = trace.get("items")
    assert isinstance(items, list)
    # Default should include only XHR/Fetch when no include/types are provided.
    assert all(isinstance(it, dict) and it.get("type") in {"XHR", "Fetch"} for it in items)

    # urlFull must not be present in tool output (artifact-only).
    assert all(isinstance(it, dict) and "urlFull" not in it for it in items)


def test_build_net_trace_store_includes_urlfull_and_headers_in_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.net_trace import build_net_trace
    from mcp_servers.browser.server.artifacts import ArtifactRef
    from mcp_servers.browser.session import session_manager

    cfg = BrowserConfig.from_env()

    class _T0:  # minimal telemetry stub
        def __init__(self, done: dict[str, dict]) -> None:
            self._req_done = done

    done = {
        "1": {
            "type": "XHR",
            "url": "https://example.com/api/a",
            "urlFull": "https://example.com/api/a?coupon=SECRET",
            "method": "GET",
            "status": 200,
            "ok": True,
            "endTs": 10,
            "reqHeaders": {"keys": ["x-test"], "selected": {"x-test": "1"}},
            "respHeaders": {"keys": ["content-type"], "selected": {"content-type": "application/json"}},
            "initiator": {"type": "script", "url": "https://example.com/app.js", "line": 1, "col": 2},
        }
    }

    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: _T0(done))

    captured: dict = {}

    def _put_json(*, kind: str, obj: object, metadata: object | None = None) -> ArtifactRef:  # noqa: ANN001
        captured["kind"] = kind
        captured["obj"] = obj
        captured["metadata"] = metadata
        return ArtifactRef(
            id="a1", kind=str(kind), mime_type="application/json", bytes=1, created_at="now", path="/tmp/a1.json"
        )

    monkeypatch.setattr("mcp_servers.browser.net_trace.artifact_store.put_json", _put_json)

    out = build_net_trace(cfg, tab_id="tab1", capture="meta", limit=5, store=True)
    assert isinstance(out.get("artifact"), dict)
    assert captured.get("kind") == "net_trace"
    obj = captured.get("obj")
    assert isinstance(obj, dict)
    items = obj.get("items")
    assert isinstance(items, list)
    assert items and isinstance(items[0], dict)
    assert items[0].get("urlFull") == "https://example.com/api/a?coupon=SECRET"
    assert isinstance(items[0].get("reqHeaders"), dict)
    assert isinstance(items[0].get("respHeaders"), dict)
    assert isinstance(items[0].get("initiator"), dict)


def test_build_net_trace_include_exclude_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.net_trace import build_net_trace
    from mcp_servers.browser.session import session_manager

    cfg = BrowserConfig.from_env()

    class _T0:
        def __init__(self, done: dict[str, dict]) -> None:
            self._req_done = done

    done = {
        "1": {
            "type": "XHR",
            "url": "https://example.com/api/foo",
            "urlFull": "https://example.com/api/foo?x=1",
            "endTs": 10,
        },
        "2": {
            "type": "XHR",
            "url": "https://example.com/api/bar",
            "urlFull": "https://example.com/api/bar?x=2",
            "endTs": 20,
        },
        "3": {"type": "XHR", "url": "https://example.com/other", "urlFull": "https://example.com/other", "endTs": 30},
    }

    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: _T0(done))

    out = build_net_trace(cfg, tab_id="tab1", include="api/", exclude=["bar"], types_raw=["XHR"], limit=50)
    trace = out.get("trace")
    assert isinstance(trace, dict)
    items = trace.get("items")
    assert isinstance(items, list)
    urls = [it.get("url") for it in items if isinstance(it, dict)]
    assert "https://example.com/api/foo" in urls
    assert "https://example.com/api/bar" not in urls
    assert "https://example.com/other" not in urls
