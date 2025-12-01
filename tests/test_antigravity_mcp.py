from __future__ import annotations

import io
import socket
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import URLError

import pytest

from mcp_servers.antigravity_browser import launcher as launcher_module
from mcp_servers.antigravity_browser import server as mcp_server
from mcp_servers.antigravity_browser import smart_tools as cdp_module
from mcp_servers.antigravity_browser.config import BrowserConfig
from mcp_servers.antigravity_browser.http_client import HttpClientError, http_get
from mcp_servers.antigravity_browser.launcher import BrowserLauncher


def test_detect_binary_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_BROWSER_BINARY", raising=False)
    monkeypatch.setenv("PATH", "")
    cfg = BrowserConfig.from_env()
    assert cfg.binary_path  # default path must be non-empty


def test_config_parses_allowlist_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BROWSER_PROFILE", "/tmp/profile")
    monkeypatch.setenv("MCP_ALLOW_HOSTS", "example.com,github.com")
    monkeypatch.setenv("MCP_HTTP_TIMEOUT", "5")
    cfg = BrowserConfig.from_env()
    assert cfg.profile_path == "/tmp/profile"
    assert cfg.allow_hosts == ["example.com", "github.com"]
    assert cfg.http_timeout == 5.0
    assert cfg.is_host_allowed("sub.github.com")
    assert not cfg.is_host_allowed("other.net")


def test_launcher_builds_command_with_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MCP_BROWSER_BINARY", "/usr/bin/chrome")
    monkeypatch.setenv("MCP_BROWSER_PROFILE", "/tmp/profile")
    monkeypatch.setenv("MCP_BROWSER_PORT", "9999")
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    cmd = launcher.build_launch_command()
    assert "/usr/bin/chrome" in cmd[0]
    assert any("--remote-debugging-port=9999" in part for part in cmd)
    assert any("--user-data-dir=/tmp/profile" in part for part in cmd)


def _start_test_server() -> tuple[str, Thread, HTTPServer]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b"hello"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}/", thread, server


def test_http_get_enforces_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    url, thread, srv = _start_test_server()
    try:
        cfg = BrowserConfig.from_env()
        cfg.allow_hosts = ["127.0.0.1"]
        resp = http_get(url, cfg)
        assert resp["status"] == 200
        assert "hello" in resp["body"]

        cfg.allow_hosts = ["example.com"]
        with pytest.raises(HttpClientError):
            http_get(url, cfg)
    finally:
        srv.shutdown()
        thread.join(timeout=1)


def test_http_get_blocks_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = BrowserConfig.from_env()
    with pytest.raises(HttpClientError):
        http_get("ftp://example.com", cfg)


def test_server_list_tools_output(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    def capture(payload: dict) -> None:
        sent.append(payload)

    monkeypatch.setattr(mcp_server, "_write_message", capture)
    srv = mcp_server.McpServer()
    srv.handle_list_tools(request_id="1")

    assert sent
    data = sent[0]
    assert data["result"]["tools"]
    assert any(tool["name"] == "http_get" for tool in data["result"]["tools"])


def test_server_initialize(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.handle_initialize(request_id="init")
    assert sent and sent[0]["result"]["serverInfo"]["name"] == "antigravity-browser"
    assert sent[0]["result"]["protocolVersion"] == mcp_server.LATEST_PROTOCOL_VERSION
    assert "logging" in sent[0]["result"]["capabilities"]
    assert "tools" in sent[0]["result"]["capabilities"]
    assert sent[0]["result"]["instructions"] == ""


def test_initialize_respects_client_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.handle_initialize(request_id="init", params={"protocolVersion": "2024-11-05"})
    assert sent[0]["result"]["protocolVersion"] == "2024-11-05"


def test_initialize_falls_back_to_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.handle_initialize(request_id="init", params={"protocolVersion": "0.0.1"})
    assert sent[0]["result"]["protocolVersion"] == mcp_server.LATEST_PROTOCOL_VERSION


def test_server_call_tool_http(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(mcp_server, "http_get", lambda url, config: {"status": 200, "headers": {}, "body": "ok", "truncated": False})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1", name="http_get", arguments={"url": "http://example.com"})
    assert "ok" in sent[0]["result"]["content"][1]["text"]


def test_server_call_tool_browser_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"ok": True, "status": 200, "statusText": "OK", "body": "ok-fetch"}
    monkeypatch.setattr(cdp_module, "browser_fetch", lambda url, config, method="GET", headers=None, body=None, credentials="include": fake_resp)
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1f", name="browser_fetch", arguments={"url": "http://example.com"})
    assert "ok-fetch" in sent[0]["result"]["content"][1]["text"]


def test_server_call_tool_browser_set_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"success": True}
    monkeypatch.setattr(cdp_module, "set_cookie", lambda **kwargs: fake_resp)
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1c", name="browser_set_cookie", arguments={
        "name": "test", "value": "123", "domain": "example.com"
    })
    assert "success" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_browser_get_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"cookies": [{"name": "test", "value": "123"}], "total": 1, "offset": 0, "limit": 20, "hasMore": False}
    monkeypatch.setattr(cdp_module, "get_all_cookies", lambda config, urls=None, offset=0, limit=20, name_filter=None: fake_resp)
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1g", name="browser_get_cookies", arguments={})
    assert "test" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_dump_dom(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"targetId": "t", "html": "<html></html>", "totalChars": 13, "truncated": False}
    monkeypatch.setattr(cdp_module, "dump_dom_html", lambda config, url, max_chars=50000: fake_resp)
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="2", name="dump_dom", arguments={"url": "http://example.com"})
    response_text = sent[0]["result"]["content"][0]["text"]
    assert "targetId" in response_text
    assert "<html" in response_text


def test_server_call_tool_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    class Dummy:
        started = True
        message = "started"

    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: Dummy())
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="3", name="launch_browser", arguments={})
    assert "started" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)

    # Mock get_session context manager to return fake session
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    @contextmanager
    def fake_get_session(config, timeout=5.0):
        session = MagicMock()
        session.capture_screenshot.return_value = "YWJj"  # base64 of "abc"
        target = {"id": "t"}
        yield session, target

    monkeypatch.setattr(cdp_module, "get_session", fake_get_session)
    monkeypatch.setattr(cdp_module, "navigate_to", lambda config, url: None)

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="5", name="screenshot", arguments={"url": "http://example.com"})
    assert sent and sent[0]["result"]["content"][1]["type"] == "image"


def test_server_call_tool_js_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(cdp_module, "eval_js", lambda expr, config: {"result": 42})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="6", name="js_eval", arguments={"expression": "6*7"})
    assert "42" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_cdp_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))

    class DummyLaunch:
        started = False
        message = "ready"

    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: DummyLaunch())
    monkeypatch.setattr(BrowserLauncher, "cdp_version", lambda self, timeout=0.8: {"version": {"Browser": "Chrome"}})

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="4", name="cdp_version", arguments={})

    assert "ready" in sent[0]["result"]["content"][0]["text"]
    assert "Chrome" in sent[0]["result"]["content"][1]["text"]


def test_server_unknown_method_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))

    srv = mcp_server.McpServer()
    srv.dispatch({"id": "x", "method": "unknown"})

    assert sent and sent[0]["error"]["code"] == -32601


def test_launcher_ensure_running_skips_if_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    monkeypatch.setattr(BrowserLauncher, "_cdp_ready", lambda self, timeout=0.4: True)
    result = launcher.ensure_running()
    assert not result.started


def test_launcher_dump_dom_uses_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyProc:
        returncode = 0
        stdout = b"<html></html>"
        stderr = b""

    monkeypatch.setattr(launcher_module.subprocess, "run", lambda *args, **kwargs: DummyProc())
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    result = launcher.dump_dom("http://example.com")
    captured.update(result)
    assert captured["exit_code"] == 0


def test_launcher_list_targets_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher_module, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(URLError("fail")))
    cfg = BrowserConfig.from_env()
    launcher_obj = BrowserLauncher(cfg)
    assert launcher_obj.list_targets() == []


def test_launcher_list_targets_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResp:
        def read(self) -> bytes:
            return b'[{"title":"tab"}]'

        def __enter__(self) -> DummyResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher_module, "urlopen", lambda *args, **kwargs: DummyResp())
    cfg = BrowserConfig.from_env()
    launcher_obj = BrowserLauncher(cfg)
    assert launcher_obj.list_targets() == [{"title": "tab"}]


def test_cdp_ready_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResp:
        status = 200

        def __enter__(self) -> DummyResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher_module, "urlopen", lambda *args, **kwargs: DummyResp())
    cfg = BrowserConfig.from_env()
    launcher_obj = BrowserLauncher(cfg)
    assert launcher_obj._cdp_ready()


def test_launcher_ensure_running_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    timestamps = [0, 10]
    monkeypatch.setattr(BrowserLauncher, "_cdp_ready", lambda self, timeout=0.4: False)
    monkeypatch.setattr(BrowserLauncher, "_port_available", lambda self, timeout=0.2: True)
    monkeypatch.setattr(launcher_module.subprocess, "Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher_module.time, "time", lambda: timestamps.pop(0) if timestamps else 10)
    monkeypatch.setattr(launcher_module.time, "sleep", lambda _: None)
    result = launcher.ensure_running()
    assert result.started is False
    assert "timed out" in result.message


def test_launcher_ensure_running_port_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    monkeypatch.setenv("MCP_BROWSER_PORT", str(port))
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    monkeypatch.setattr(BrowserLauncher, "_cdp_ready", lambda self, timeout=0.4: False)

    try:
        result = launcher.ensure_running()
    finally:
        listener.close()

    assert result.started is False
    assert "already in use" in result.message


def test_read_and_write_message_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", stdout)
    mcp_server._write_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    data = buffer.getvalue()
    assert data.endswith(b"\n")

    payload = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    stdin_buffer = io.BytesIO(payload)

    class DummyStdin:
        buffer = stdin_buffer

    monkeypatch.setattr(sys, "stdin", DummyStdin())
    msg = mcp_server._read_message()
    assert msg["method"] == "ping"


def test_dispatch_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.dispatch({"id": "p", "method": "ping"})
    assert sent[0]["result"]["pong"] is True


def test_logging_called(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(mcp_server.logger, "info", lambda *args, **kwargs: logged.append(args[0]))
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: None)
    monkeypatch.setattr(mcp_server.BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(cdp_module, "eval_js", lambda expr, config: {"result": "ok"})
    srv = mcp_server.McpServer()
    srv.handle_call_tool("x", "js_eval", {"expression": "1"})
    assert logged


def test_dispatch_ignores_initialized_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.dispatch({"method": "notifications/initialized", "params": {}})
    assert sent == []


def test_handle_call_tool_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="err", name="unknown", arguments={})
    assert sent[0]["error"]["code"] == -32001


# --- Pagination Tests ---


def test_get_all_cookies_pagination() -> None:
    """Test get_all_cookies pagination logic."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.cookies import get_all_cookies

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=(mock_session, {"id": "test"}))
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.send = MagicMock(return_value={
        "cookies": [{"name": f"cookie_{i}", "value": f"val_{i}"} for i in range(25)]
    })

    with patch("mcp_servers.antigravity_browser.tools.cookies.get_session", return_value=mock_session):
        config = BrowserConfig.from_env()
        result = get_all_cookies(config, offset=0, limit=10)

        assert result["total"] == 25
        assert len(result["cookies"]) == 10
        assert result["offset"] == 0
        assert result["limit"] == 10
        assert result["hasMore"] is True
        assert "navigation" in result
        assert "next" in result["navigation"]


def test_get_all_cookies_with_filter() -> None:
    """Test get_all_cookies name filtering."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.cookies import get_all_cookies

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=(mock_session, {"id": "test"}))
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.send = MagicMock(return_value={
        "cookies": [
            {"name": "session_id", "value": "123"},
            {"name": "auth_token", "value": "abc"},
            {"name": "session_data", "value": "xyz"},
        ]
    })

    with patch("mcp_servers.antigravity_browser.tools.cookies.get_session", return_value=mock_session):
        config = BrowserConfig.from_env()
        result = get_all_cookies(config, name_filter="session")

        assert result["total"] == 2  # Only session_id and session_data match
        assert all("session" in c["name"].lower() for c in result["cookies"])


def test_list_tabs_pagination() -> None:
    """Test list_tabs pagination logic."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.tabs import list_tabs

    mock_tabs = [{"id": f"tab_{i}", "url": f"https://example{i}.com", "title": f"Tab {i}"} for i in range(15)]

    with patch("mcp_servers.antigravity_browser.tools.tabs.session_manager") as mock_sm:
        mock_sm.list_tabs = MagicMock(return_value=mock_tabs)
        mock_sm.tab_id = "current_tab"

        config = BrowserConfig.from_env()
        result = list_tabs(config, offset=5, limit=5)

        assert result["total"] == 15
        assert len(result["tabs"]) == 5
        assert result["offset"] == 5
        assert result["hasMore"] is True
        assert "navigation" in result
        assert "prev" in result["navigation"]
        assert "next" in result["navigation"]


def test_list_tabs_url_filter() -> None:
    """Test list_tabs URL filtering."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.tabs import list_tabs

    mock_tabs = [
        {"id": "1", "url": "https://github.com/repo", "title": "GitHub"},
        {"id": "2", "url": "https://google.com", "title": "Google"},
        {"id": "3", "url": "https://github.com/issues", "title": "Issues"},
    ]

    with patch("mcp_servers.antigravity_browser.tools.tabs.session_manager") as mock_sm:
        mock_sm.list_tabs = MagicMock(return_value=mock_tabs)
        mock_sm.tab_id = "current_tab"

        config = BrowserConfig.from_env()
        result = list_tabs(config, url_filter="github")

        assert result["total"] == 2  # Only github URLs
        assert all("github" in t["url"].lower() for t in result["tabs"])


# --- DOM Tools Truncation Tests ---


def test_get_dom_truncation() -> None:
    """Test get_dom truncates large HTML and returns metadata."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.dom import get_dom

    # Create large HTML (100KB)
    large_html = "<html>" + ("x" * 100000) + "</html>"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=(mock_session, {"id": "test"}))
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.get_dom = MagicMock(return_value=large_html)

    with patch("mcp_servers.antigravity_browser.tools.dom.get_session", return_value=mock_session):
        config = BrowserConfig.from_env()

        # Test with default limit (50000)
        result = get_dom(config, max_chars=50000)

        assert result["truncated"] is True
        assert result["totalChars"] == len(large_html)
        assert result["returnedChars"] == 50000
        assert len(result["html"]) == 50000
        assert "hint" in result


def test_get_dom_no_truncation() -> None:
    """Test get_dom doesn't truncate small HTML."""
    from unittest.mock import MagicMock, patch

    from mcp_servers.antigravity_browser.tools.dom import get_dom

    small_html = "<html><body>Hello</body></html>"

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=(mock_session, {"id": "test"}))
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.get_dom = MagicMock(return_value=small_html)

    with patch("mcp_servers.antigravity_browser.tools.dom.get_session", return_value=mock_session):
        config = BrowserConfig.from_env()
        result = get_dom(config)

        assert result["truncated"] is False
        assert result["totalChars"] == len(small_html)
        assert result["html"] == small_html
        assert "hint" not in result
