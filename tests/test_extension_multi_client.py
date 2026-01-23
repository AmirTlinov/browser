from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Any

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_extension_gateway_peer_roundtrip_and_event_forwarding() -> None:
    try:
        import websockets  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        pytest.skip("websockets not installed")

    from mcp_servers.browser.extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION, ExtensionGateway

    port = _free_port()
    ext_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    gw = ExtensionGateway(host="127.0.0.1", port=port, expected_extension_id=None)
    gw.start()

    stop = threading.Event()
    ext_ready = threading.Event()
    peer_ready = threading.Event()
    saw_peer_event = threading.Event()

    def _extension_stub() -> None:
        async def _main() -> None:
            from websockets.typing import Origin as WsOrigin  # type: ignore

            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(
                uri, origin=WsOrigin(f"chrome-extension://{ext_id}"), ping_interval=None
            ) as ws:
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
                ext_ready.set()

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

                    if method == "cdp.send":
                        await ws.send(json.dumps({"type": "rpcResult", "id": req_id, "ok": True, "result": {}}))
                        # Emit one event after the first cdp.send to validate peer forwarding.
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

    def _peer_client() -> None:
        async def _main() -> None:
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri, ping_interval=None) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "peerHello",
                            "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                            "peerId": "peer-test",
                            "pid": 0,
                        }
                    )
                )
                ack = json.loads(await ws.recv())
                assert ack.get("type") == "peerHelloAck"
                peer_ready.set()

                # Subscribe by referencing tabId.
                await ws.send(
                    json.dumps(
                        {
                            "type": "rpc",
                            "id": 1,
                            "method": "cdp.send",
                            "timeoutMs": 1000,
                            "params": {"tabId": "55", "method": "Runtime.enable", "params": {}},
                        }
                    )
                )

                got_result = False
                deadline = time.time() + 3.0
                while time.time() < deadline and not stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    msg = json.loads(raw)
                    if msg.get("type") == "rpcResult" and msg.get("id") == 1:
                        assert msg.get("ok") is True
                        got_result = True
                        if saw_peer_event.is_set():
                            break
                        continue
                    if (
                        msg.get("type") == "cdpEvent"
                        and str(msg.get("tabId")) == "55"
                        and msg.get("method") == "Page.loadEventFired"
                    ):
                        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                        assert params.get("marker") == 1
                        saw_peer_event.set()
                        if got_result:
                            break

                assert got_result is True
                assert saw_peer_event.is_set() is True

        asyncio.run(_main())

    t_ext = threading.Thread(target=_extension_stub, name="ext-stub", daemon=True)
    t_peer = threading.Thread(target=_peer_client, name="peer-client", daemon=True)
    t_ext.start()
    t_peer.start()

    assert ext_ready.wait(timeout=3.0)
    assert peer_ready.wait(timeout=3.0)
    assert saw_peer_event.wait(timeout=3.0)

    stop.set()
    t_peer.join(timeout=2.0)
    t_ext.join(timeout=2.0)
    gw.stop(timeout=2.0)


def test_extension_gateway_many_peers_can_share_one_extension() -> None:
    try:
        import websockets  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        pytest.skip("websockets not installed")

    from mcp_servers.browser.extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION, ExtensionGateway

    port = _free_port()
    ext_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    gw = ExtensionGateway(host="127.0.0.1", port=port, expected_extension_id=None)
    gw.start()

    stop = threading.Event()
    ext_ready = threading.Event()

    def _extension_stub() -> None:
        async def _main() -> None:
            from websockets.typing import Origin as WsOrigin  # type: ignore

            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(
                uri, origin=WsOrigin(f"chrome-extension://{ext_id}"), ping_interval=None
            ) as ws:
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
                ext_ready.set()

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
                    if method == "tabs.list":
                        result: Any = [{"id": "1", "url": "https://example.test", "title": "Example"}]
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

    t_ext = threading.Thread(target=_extension_stub, name="ext-stub-many", daemon=True)
    t_ext.start()
    assert ext_ready.wait(timeout=3.0)

    results: list[bool] = []
    results_lock = threading.Lock()

    def _peer(i: int) -> None:
        async def _main() -> None:
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri, ping_interval=None) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "peerHello",
                            "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                            "peerId": f"peer-{i}",
                            "pid": 0,
                        }
                    )
                )
                ack = json.loads(await ws.recv())
                assert ack.get("type") == "peerHelloAck"

                await ws.send(
                    json.dumps({"type": "rpc", "id": 1, "method": "tabs.list", "timeoutMs": 1000, "params": {}})
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                assert msg.get("type") == "rpcResult"
                assert msg.get("ok") is True

        try:
            asyncio.run(_main())
            ok = True
        except Exception:
            ok = False
        with results_lock:
            results.append(ok)

    peers = [threading.Thread(target=_peer, args=(i,), name=f"peer-{i}", daemon=True) for i in range(10)]
    for t in peers:
        t.start()
    for t in peers:
        t.join(timeout=4.0)

    assert len(results) == 10
    assert all(results)

    stop.set()
    t_ext.join(timeout=2.0)
    gw.stop(timeout=2.0)
