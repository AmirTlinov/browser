"""
Tests for browser MCP server.

Tests cover:
- Configuration parsing
- Browser launcher
- Server initialization and tool listing
- Tool dispatch (unified API)
- Protocol handling
"""

from __future__ import annotations

import socket
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import URLError

import pytest

from mcp_servers.browser import launcher as launcher_module
from mcp_servers.browser import main as mcp_server
from mcp_servers.browser.config import BrowserConfig
from mcp_servers.browser.http_client import HttpClientError, http_get
from mcp_servers.browser.launcher import BrowserLauncher


@pytest.fixture(autouse=True)
def _mock_cdp_ready_for_unit_server_tool_calls(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """
    Unit tests for server tool wiring mock out the actual browser operations.

    The registry now performs a fast CDP health-check (`launcher.cdp_ready()`),
    so we patch it to True for those unit tests to keep them hermetic.
    """
    if "server_call_tool" in request.node.name:
        monkeypatch.setattr(BrowserLauncher, "cdp_ready", lambda self, timeout=0.6: True)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════════════


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
    assert not cfg.is_host_allowed("evilgithub.com")
    assert not cfg.is_host_allowed("other.net")


# ═══════════════════════════════════════════════════════════════════════════════
# LAUNCHER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


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
    """Test that launcher times out when browser never becomes ready."""
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)

    # Simulate time passing to trigger timeout
    call_count = [0]

    def fake_time():
        call_count[0] += 1
        return call_count[0] * 5  # Each call advances 5 seconds

    monkeypatch.setattr(BrowserLauncher, "_cdp_ready", lambda self, timeout=0.4: False)
    monkeypatch.setattr(launcher_module.time, "time", fake_time)
    monkeypatch.setattr(launcher_module.time, "sleep", lambda s: None)

    class FakePopen:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(launcher_module.subprocess, "Popen", FakePopen)
    result = launcher.ensure_running()
    # Should timeout and report started=True (browser was launched but never ready)
    # OR started=False if port was detected in use
    # The key is that it doesn't hang
    assert result.message  # Should have a message explaining the outcome


def test_launcher_ensure_running_port_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = BrowserConfig.from_env()
    launcher = BrowserLauncher(cfg)
    calls = [0]

    def fake_ready(self, timeout=0.4):
        calls[0] += 1
        return calls[0] > 1

    monkeypatch.setattr(BrowserLauncher, "_cdp_ready", fake_ready)

    def fake_popen(*args, **kwargs):
        raise OSError("Address already in use")

    monkeypatch.setattr(launcher_module.subprocess, "Popen", fake_popen)
    result = launcher.ensure_running()
    assert not result.started
    assert "already" in result.message.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════


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


def test_http_get_blocks_redirect_to_disallowed_host() -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://localhost:9/")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = HTTPServer(("127.0.0.1", port), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = BrowserConfig.from_env()
        cfg.allow_hosts = ["127.0.0.1"]
        with pytest.raises(HttpClientError) as exc:
            http_get(f"http://127.0.0.1:{port}/", cfg)
        assert "redirect" in str(exc.value).lower()
    finally:
        server.shutdown()
        thread.join(timeout=1)


# ═══════════════════════════════════════════════════════════════════════════════
# SERVER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_server_list_tools_output(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    def capture(payload: dict) -> None:
        sent.append(payload)

    monkeypatch.setattr(mcp_server, "_write_message", capture)
    srv = mcp_server.McpServer()
    srv.handle_list_tools(request_id="1")

    assert sent
    data = sent[0]
    tools = data["result"]["tools"]
    assert tools
    # Check for unified tool names
    tool_names = [t["name"] for t in tools]
    assert "page" in tool_names
    assert "flow" in tool_names
    assert "run" in tool_names
    assert "navigate" in tool_names
    assert "click" in tool_names
    assert "scroll" in tool_names
    assert "download" in tool_names
    # Keep the tool surface small, but allow deliberate additions.
    assert len(tools) == 25


def test_server_list_tools_toolset_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []

    def capture(payload: dict) -> None:
        sent.append(payload)

    monkeypatch.setattr(mcp_server, "_write_message", capture)
    monkeypatch.setenv("MCP_TOOLSET", "v2")

    srv = mcp_server.McpServer()
    srv.handle_list_tools(request_id="1")

    assert sent
    data = sent[0]
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert tool_names == ["page", "run", "app", "browser"]


def test_server_initialize(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.handle_initialize(request_id="init")
    assert sent and sent[0]["result"]["serverInfo"]["name"] == "browser"
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


def test_server_unknown_method_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))

    srv = mcp_server.McpServer()
    srv.dispatch({"id": "x", "method": "unknown"})

    assert sent and sent[0]["error"]["code"] == -32601


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED TOOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_server_call_tool_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified http tool."""
    from mcp_servers.browser import http_client

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(
        http_client, "http_get", lambda url, config: {"status": 200, "headers": {}, "body": "ok", "truncated": False}
    )
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1", name="http", arguments={"url": "http://example.com"})
    assert "ok" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified fetch tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"ok": True, "status": 200, "statusText": "OK", "body": "ok-fetch"}
    monkeypatch.setattr(
        unified.tools,
        "browser_fetch",
        lambda config, url, method="GET", headers=None, body=None, credentials="include": fake_resp,
    )
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1f", name="fetch", arguments={"url": "http://example.com"})
    assert "ok-fetch" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_cookies_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified cookies tool - set action."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"success": True}
    # Mock set_cookie with correct signature (config, name, value, domain, **kwargs)
    monkeypatch.setattr(unified.tools, "set_cookie", lambda config, **kwargs: fake_resp)
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(
        request_id="1c",
        name="cookies",
        arguments={"action": "set", "name": "test", "value": "123", "domain": "example.com"},
    )
    assert "success" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_cookies_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified cookies tool - get action."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    fake_resp = {"cookies": [{"name": "test", "value": "123"}], "total": 1, "offset": 0, "limit": 20, "hasMore": False}
    monkeypatch.setattr(
        unified.tools, "get_all_cookies", lambda config, urls=None, offset=0, limit=20, name_filter=None: fake_resp
    )
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1g", name="cookies", arguments={"action": "get"})
    assert "test" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_browser_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified browser tool - status action."""
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(
        BrowserLauncher, "cdp_version", lambda self, timeout=0.8: {"status": 200, "version": {"Browser": "Chrome/130"}}
    )
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="4", name="browser", arguments={"action": "status"})
    assert "Chrome" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_browser_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified browser tool - launch action."""
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="3", name="browser", arguments={"action": "launch"})
    assert "launched" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test screenshot tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(unified.tools, "screenshot", lambda config, **kwargs: {"data": "YWJj", "target": "t"})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="5", name="screenshot", arguments={})
    assert sent and sent[0]["result"]["content"][0]["type"] == "image"


def test_server_call_tool_page_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test page(detail='diagnostics') wiring."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "get_page_diagnostics",
        lambda config, offset=0, limit=50, sort="start", clear=False: {
            "diagnostics": {"summary": {"consoleErrors": 1}}
        },
    )

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="pd", name="page", arguments={"detail": "diagnostics"})
    assert sent
    assert "consoleErrors" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_page_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test page(detail='resources') wiring."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "get_page_resources",
        lambda config, offset=0, limit=50, sort="start": {"resources": {"total": 1, "items": []}},
    )

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="pr", name="page", arguments={"detail": "resources"})
    assert sent
    assert "resources" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_page_performance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test page(detail='performance') wiring."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "get_page_performance",
        lambda config: {"performance": {"vitals": {"cls": 0.0}}},
    )

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="pp", name="page", arguments={"detail": "performance"})
    assert sent
    assert "performance" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_page_locators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test page(detail='locators') wiring."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "get_page_locators",
        lambda config, kind="all", offset=0, limit=50: {"locators": {"total": 1, "items": []}},
    )

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="pl", name="page", arguments={"detail": "locators"})
    assert sent
    assert "locators" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_js(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified js tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(unified.tools, "eval_js", lambda config, code: {"result": 42})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="6", name="js", arguments={"code": "6*7"})
    assert "42" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_navigate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified navigate tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "navigate_to",
        lambda config, url, wait_load=True: {"url": "https://example.com", "target": "t"},
    )
    monkeypatch.setattr(unified.tools, "wait_for", lambda config, condition, timeout=10: {"found": True})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="7", name="navigate", arguments={"url": "https://example.com"})
    assert "example.com" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_scroll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified scroll tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(unified.tools, "scroll_page", lambda config, dx, dy: {"deltaX": dx, "deltaY": dy})
    monkeypatch.setattr(unified.tools, "get_page_info", lambda config: {"pageInfo": {"scrollX": 0, "scrollY": 300}})
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="8", name="scroll", arguments={"direction": "down", "amount": 300})
    assert "300" in sent[0]["result"]["content"][0]["text"]


def test_server_call_tool_click(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unified click tool."""
    from mcp_servers.browser.server.handlers import unified

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)
    monkeypatch.setattr(
        unified.tools,
        "click_element",
        lambda config, text=None, role=None, near_text=None, index=0, button="left", double=False: {
            "result": {"success": True, "tagName": "BUTTON", "text": "Submit"}
        },
    )
    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="9", name="click", arguments={"text": "Submit", "wait_after": "none"})
    assert "success" in sent[0]["result"]["content"][0]["text"]


def test_handle_call_tool_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test unknown tool returns error."""
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))

    srv = mcp_server.McpServer()
    srv.handle_call_tool(request_id="1", name="unknown_tool_xyz", arguments={})

    assert sent
    assert sent[0]["result"]["isError"] is True
    assert "Unknown" in sent[0]["result"]["content"][0]["text"]


# ═══════════════════════════════════════════════════════════════════════════════
# PROTOCOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_read_and_write_message_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test message serialization by capturing output."""
    captured: list[bytes] = []

    class FakeBuffer:
        def write(self, data: bytes) -> int:
            captured.append(data)
            return len(data)

        def flush(self) -> None:
            pass

    fake_stdout = type("FakeStdout", (), {"buffer": FakeBuffer()})()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    mcp_server._write_message({"hello": "world"})

    assert captured
    data = captured[0]
    assert b"hello" in data
    assert b"world" in data


def test_dispatch_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.dispatch({"id": "p", "method": "ping"})
    assert sent and sent[0]["result"]["pong"] is True


def test_logging_called(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that tool calls are logged."""
    import logging

    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    monkeypatch.setattr(BrowserLauncher, "ensure_running", lambda self: None)

    from mcp_servers.browser.server.handlers import unified

    monkeypatch.setattr(unified.tools, "scroll_page", lambda config, dx, dy: {"deltaX": dx, "deltaY": dy})
    monkeypatch.setattr(unified.tools, "get_page_info", lambda config: {"pageInfo": {"scrollX": 0, "scrollY": 300}})

    # Enable logging capture for the mcp.browser logger
    with caplog.at_level(logging.INFO, logger="mcp.browser"):
        srv = mcp_server.McpServer()
        srv.handle_call_tool(request_id="log", name="scroll", arguments={"direction": "down"})

    assert "scroll" in caplog.text.lower()


def test_dispatch_ignores_initialized_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_write_message", lambda payload: sent.append(payload))
    srv = mcp_server.McpServer()
    srv.dispatch({"method": "notifications/initialized"})
    assert not sent


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED HANDLER INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


def test_unified_handler_registry() -> None:
    """Test that all unified handlers are registered."""
    from mcp_servers.browser.server.handlers.unified import UNIFIED_HANDLERS

    expected_tools = {
        "page",
        "navigate",
        "app",
        "click",
        "type",
        "scroll",
        "form",
        "screenshot",
        "tabs",
        "cookies",
        "captcha",
        "mouse",
        "resize",
        "js",
        "http",
        "fetch",
        "upload",
        "download",
        "storage",
        "dialog",
        "totp",
        "wait",
        "browser",
        "artifact",
    }
    assert set(UNIFIED_HANDLERS.keys()) == expected_tools
    assert len(UNIFIED_HANDLERS) == 24


def test_tool_result_json() -> None:
    """Test ToolResult.json returns correct structure."""
    from mcp_servers.browser.server.types import ToolResult

    result = ToolResult.json({"foo": "bar"})
    content = result.to_content_list()
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "foo" in content[0]["text"]


def test_tool_result_image() -> None:
    """Test ToolResult.image returns correct structure."""
    from mcp_servers.browser.server.types import ToolResult

    result = ToolResult.image("YWJj", "target123")
    content = result.to_content_list()
    assert len(content) == 1
    assert content[0]["type"] == "image"
    assert content[0]["data"] == "YWJj"


def test_tool_result_error() -> None:
    """Test ToolResult.error returns correct structure."""
    from mcp_servers.browser.server.types import ToolResult

    result = ToolResult.error("Something failed")
    content = result.to_content_list()
    assert len(content) == 1
    assert "Something failed" in content[0]["text"]
    assert result.is_error


def test_registry_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test registry dispatches to correct handler."""
    from mcp_servers.browser.server.registry import ToolRegistry

    calls: list[str] = []

    def fake_handler(config, launcher, args):
        calls.append("called")
        from mcp_servers.browser.server.types import ToolResult

        return ToolResult.json({"ok": True})

    registry = ToolRegistry()
    registry.register("test_tool", fake_handler, requires_browser=False)

    cfg = BrowserConfig.from_env()
    lnchr = BrowserLauncher(cfg)
    result = registry.dispatch("test_tool", cfg, lnchr, {})

    assert calls == ["called"]
    assert "ok" in result.to_content_list()[0]["text"]


def test_registry_unknown_tool() -> None:
    """Test registry raises for unknown tool."""
    from mcp_servers.browser.server.registry import ToolRegistry

    registry = ToolRegistry()

    cfg = BrowserConfig.from_env()
    lnchr = BrowserLauncher(cfg)

    with pytest.raises(KeyError):
        registry.dispatch("nonexistent", cfg, lnchr, {})


def test_tool_result_image_empty_fallback() -> None:
    """Test ToolResult.image returns error when data is empty."""
    from mcp_servers.browser.server.types import ToolResult

    result = ToolResult.image("")
    assert result.is_error
    content = result.to_content_list()
    assert content[0]["type"] == "text"
    assert "empty" in content[0]["text"].lower()


def test_tool_result_with_image_empty_fallback() -> None:
    """Test ToolResult.with_image returns only text when image is empty."""
    from mcp_servers.browser.server.types import ToolResult

    result = ToolResult.with_image("Some text", "")
    content = result.to_content_list()
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "Some text" in content[0]["text"]
