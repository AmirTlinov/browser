from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
import urllib.request
from typing import Any

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_extension_gateway_start_fail_soft_then_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import websockets  # type: ignore[import-not-found]  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("websockets not installed")

    from mcp_servers.browser.extension_gateway import ExtensionGateway

    port = _free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)

    # Restrict the gateway to only the blocked port to force an initial bind failure,
    # then verify the retry loop binds once the port becomes available.
    monkeypatch.setenv("MCP_EXTENSION_PORT_RANGE", f"{port}-{port}")

    gw = ExtensionGateway(host="127.0.0.1", port=port, expected_extension_id=None)
    try:
        gw.start(wait_timeout=0.3, require_listening=False)
        st = gw.status()
        assert st.get("listening") is False
        assert st.get("threadAlive") is True
        assert isinstance(st.get("bindError"), str) and st.get("bindError")

        blocker.close()

        deadline = time.time() + 2.5
        while time.time() < deadline:
            if gw.status().get("listening") is True:
                break
            time.sleep(0.05)
        assert gw.status().get("listening") is True
    finally:
        with contextlib.suppress(Exception):
            blocker.close()
        gw.stop(timeout=2.0)


def test_extension_gateway_rpc_and_events_roundtrip() -> None:
    try:
        import websockets  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        pytest.skip("websockets not installed")

    from mcp_servers.browser.extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION, ExtensionGateway

    port = _free_port()
    seen: list[tuple[str, dict[str, Any]]] = []
    # Chrome extension origins are base16-ish ids: 32 chars in [a-p].
    ext_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    gw = ExtensionGateway(
        host="127.0.0.1",
        port=port,
        expected_extension_id=None,
        on_cdp_event=lambda tab_id, ev: seen.append((tab_id, ev)),
    )
    gw.start()

    connected = threading.Event()
    stop = threading.Event()

    def _client() -> None:
        async def _main() -> None:
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri, origin=f"chrome-extension://{ext_id}", ping_interval=None) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "hello",
                            "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                            "extensionId": ext_id,
                            "extensionVersion": "0.0.0",
                            "userAgent": "pytest",
                            "capabilities": {"debugger": True, "tabs": True, "cdpSendMany": True, "rpcBatch": True},
                            "state": {"enabled": True, "followActive": False, "focusedTabId": None},
                        }
                    )
                )
                raw_ack = await ws.recv()
                ack = json.loads(raw_ack)
                assert ack.get("type") == "helloAck"
                assert ack.get("protocolVersion") == EXTENSION_BRIDGE_PROTOCOL_VERSION
                connected.set()

                # Send one CDP event for server-side waits + telemetry hook.
                await ws.send(
                    json.dumps(
                        {
                            "type": "cdpEvent",
                            "tabId": 55,
                            "method": "Page.loadEventFired",
                            "params": {"marker": 1},
                        }
                    )
                )

                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    if msg.get("type") != "rpc":
                        continue
                    req_id = msg.get("id")
                    method = msg.get("method")
                    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

                    if method == "tabs.list":
                        result: Any = [{"id": "55", "url": "https://example.test", "title": "Example"}]
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": result}))
                        continue

                    if method == "tabs.get":
                        tid = str(params.get("tabId") or "")
                        result = {"id": tid, "url": "https://example.test", "title": "Example"} if tid == "55" else None
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": result}))
                        continue

                    if method == "rpc.batch":
                        calls = params.get("calls") if isinstance(params.get("calls"), list) else []
                        out: list[dict[str, Any]] = []
                        for c in calls:
                            if not isinstance(c, dict):
                                continue
                            m2 = c.get("method")
                            p2 = c.get("params") if isinstance(c.get("params"), dict) else {}
                            if m2 == "tabs.list":
                                out.append(
                                    {
                                        "ok": True,
                                        "result": [{"id": "55", "url": "https://example.test", "title": "Example"}],
                                    }
                                )
                                continue
                            if m2 == "tabs.get":
                                tid = str(p2.get("tabId") or "")
                                out.append(
                                    {
                                        "ok": True,
                                        "result": {"id": tid, "url": "https://example.test", "title": "Example"}
                                        if tid == "55"
                                        else None,
                                    }
                                )
                                continue
                            out.append({"ok": False, "error": f"unknown method: {m2}"})
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": out}))
                        continue

                    if method == "cdp.send":
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": {}}))
                        continue

                    if method == "cdp.sendMany":
                        commands = params.get("commands") if isinstance(params.get("commands"), list) else []
                        result = [{} for _ in commands]
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": result}))
                        continue

                    await ws.send(
                        json.dumps(
                            {
                                "type": "rpcResult",
                                "id": req_id,
                                "ok": False,
                                "error": {"message": f"unknown method: {method}"},
                            }
                        )
                    )

        asyncio.run(_main())

    t = threading.Thread(target=_client, name="test-extension-client", daemon=True)
    t.start()
    assert connected.wait(timeout=3.0)

    tabs = gw.rpc_call("tabs.list", {}, timeout=2.0)
    assert isinstance(tabs, list)
    assert tabs and isinstance(tabs[0], dict)
    assert tabs[0].get("id") == "55"

    assert gw.supports_rpc_batch() is True
    batch = gw.rpc_call_many(
        [
            {"method": "tabs.get", "params": {"tabId": "55"}},
            {"method": "tabs.list", "params": {}},
        ],
        timeout=2.0,
    )
    assert isinstance(batch, list)
    assert len(batch) == 2
    assert batch[0].get("ok") is True
    assert isinstance(batch[0].get("result"), dict)
    assert batch[1].get("ok") is True
    assert isinstance(batch[1].get("result"), list)

    assert gw.supports_cdp_send_many() is True
    res_many = gw.cdp_send_many(
        "55",
        commands=[
            {"method": "Runtime.enable", "params": {}},
            {"method": "Page.enable", "params": {}},
        ],
        timeout=2.0,
    )
    assert isinstance(res_many, list)
    assert len(res_many) == 2

    ev = gw.wait_for_event("55", "Page.loadEventFired", timeout=2.0)
    assert isinstance(ev, dict)
    assert ev.get("marker") == 1

    assert seen and seen[0][0] == "55"
    assert seen[0][1].get("method") == "Page.loadEventFired"

    stop.set()
    t.join(timeout=2.0)
    gw.stop(timeout=2.0)


def test_extension_gateway_well_known_and_wait_for_connection() -> None:
    try:
        import websockets  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        pytest.skip("websockets not installed")

    from mcp_servers.browser.extension_gateway import (
        EXTENSION_BRIDGE_PROTOCOL_VERSION,
        EXTENSION_GATEWAY_WELL_KNOWN_PATH,
        ExtensionGateway,
    )

    port = _free_port()
    gw = ExtensionGateway(host="127.0.0.1", port=port, expected_extension_id=None)
    gw.start()

    # No client yet.
    assert gw.wait_for_connection(timeout=0.05) is False
    assert gw.is_connected() is False

    # Well-known discovery endpoint (quiet HTTP probe).
    url = f"http://127.0.0.1:{port}{EXTENSION_GATEWAY_WELL_KNOWN_PATH}"
    with urllib.request.urlopen(url, timeout=1.0) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    assert data.get("type") == "browserMcpGateway"
    assert int(data.get("gatewayPort")) == port
    assert int(data.get("serverStartedAtMs") or 0) > 0
    assert data.get("supportsPeers") is True

    connected = threading.Event()
    stop = threading.Event()

    def _client() -> None:
        async def _main() -> None:
            # Chrome extension origins are base16-ish ids: 32 chars in [a-p].
            ext_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri, origin=f"chrome-extension://{ext_id}", ping_interval=None) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "hello",
                            "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                            "extensionId": ext_id,
                            "extensionVersion": "0.0.0",
                            "userAgent": "pytest",
                            "capabilities": {"debugger": True, "tabs": True, "cdpSendMany": True, "rpcBatch": True},
                            "state": {"enabled": True, "followActive": False, "focusedTabId": None},
                        }
                    )
                )
                ack = json.loads(await ws.recv())
                assert ack.get("type") == "helloAck"
                connected.set()
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue

        asyncio.run(_main())

    t = threading.Thread(target=_client, name="test-extension-client-well-known", daemon=True)
    t.start()
    assert connected.wait(timeout=3.0)
    assert gw.wait_for_connection(timeout=2.0) is True
    assert gw.is_connected() is True

    stop.set()
    t.join(timeout=2.0)
    gw.stop(timeout=2.0)


def test_session_manager_extension_mode_adopts_focused_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.session import ExtensionCdpConnection, session_manager

    class FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def is_connected(self) -> bool:
            return True

        def rpc_call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:  # noqa: ARG002
            self.calls.append((method, params))
            if method == "state.get":
                return {"followActive": True, "focusedTabId": "55"}
            if method == "tabs.get":
                if (params or {}).get("tabId") == "55":
                    return {"id": "55", "url": "https://example.test", "title": "Example"}
                return None
            if method == "tabs.create":
                return {"tabId": "99"}
            if method == "tabs.activate":
                return {"success": True}
            if method == "tabs.close":
                return {"success": True}
            raise RuntimeError(f"unexpected rpc_call: {method}")

        def cdp_send(
            self,
            tab_id: str,
            method: str,
            params: dict[str, Any] | None = None,
            *,
            timeout: float = 10.0,  # noqa: ARG002
        ) -> dict[str, Any]:
            self.calls.append(("cdp_send", {"tabId": tab_id, "method": method, "params": params}))
            return {}

        def pop_event(self, tab_id: str, event_name: str) -> dict[str, Any] | None:  # noqa: ARG002
            return None

        def wait_for_event(self, tab_id: str, event_name: str, *, timeout: float = 10.0) -> dict[str, Any] | None:  # noqa: ARG002
            return None

    cfg = BrowserConfig.from_env()
    cfg.mode = "extension"

    fake = FakeGateway()

    # Preserve global singleton state to avoid leaking across tests.
    old_gw = getattr(session_manager, "_extension_gateway", None)  # noqa: SLF001
    old_tab = getattr(session_manager, "_session_tab_id", None)  # noqa: SLF001
    try:
        session_manager.set_extension_gateway(fake)  # type: ignore[arg-type]
        monkeypatch.setattr(session_manager, "_session_tab_id", None)  # noqa: SLF001

        sess = session_manager.get_session(cfg, timeout=1.0)
        assert sess.tab_id == "55"
        assert isinstance(sess.conn, ExtensionCdpConnection)
        sess.send("Page.enable")
        assert any(c[0] == "cdp_send" for c in fake.calls)
    finally:
        session_manager.set_extension_gateway(old_gw)  # type: ignore[arg-type]
        monkeypatch.setattr(session_manager, "_session_tab_id", old_tab)  # noqa: SLF001
