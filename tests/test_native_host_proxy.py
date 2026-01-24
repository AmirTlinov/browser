from __future__ import annotations

import contextlib
import json
import os
import select
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _read_exact(fp, n: int, *, timeout_s: float) -> bytes:
    buf = bytearray()
    fd = fp.fileno()
    deadline = time.time() + max(0.01, float(timeout_s))
    while len(buf) < n:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"timeout while reading {n} bytes")
        r, _w, _x = select.select([fp], [], [], remaining)
        if not r:
            continue
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise EOFError("unexpected EOF")
        buf.extend(chunk)
    return bytes(buf)


def _read_exact_fd(fd: int, n: int, *, timeout_s: float) -> bytes:
    buf = bytearray()
    deadline = time.time() + max(0.01, float(timeout_s))
    while len(buf) < n:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"timeout while reading {n} bytes")
        r, _w, _x = select.select([fd], [], [], remaining)
        if not r:
            continue
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise EOFError("unexpected EOF")
        buf.extend(chunk)
    return bytes(buf)


def _read_native_message(fp, *, timeout_s: float) -> dict[str, Any]:
    header = _read_exact(fp, 4, timeout_s=timeout_s)
    (length,) = struct.unpack("<I", header)
    raw = _read_exact(fp, int(length), timeout_s=timeout_s)
    data = json.loads(raw.decode("utf-8"))
    assert isinstance(data, dict)
    return data


def _write_native_message(fp, msg: dict[str, Any]) -> None:
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    fp.write(struct.pack("<I", len(raw)))
    fp.write(raw)
    fp.flush()


def _read_ipc_message(fd: int, *, timeout_s: float) -> dict[str, Any]:
    header = _read_exact_fd(fd, 4, timeout_s=timeout_s)
    (length,) = struct.unpack("<I", header)
    raw = _read_exact_fd(fd, int(length), timeout_s=timeout_s)
    data = json.loads(raw.decode("utf-8"))
    assert isinstance(data, dict)
    return data


def _write_ipc_message(fd: int, msg: dict[str, Any]) -> None:
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.write(fd, struct.pack("<I", len(raw)) + raw)


def test_native_host_broker_roundtrip(tmp_path: Path) -> None:
    from mcp_servers.browser.extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
    from mcp_servers.browser.native_broker_paths import broker_socket_path

    env = os.environ.copy()
    env["MCP_NATIVE_BROKER_DIR"] = str(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_servers.browser.native_host"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    peer: socket.socket | None = None
    old_dir = os.environ.get("MCP_NATIVE_BROKER_DIR")
    os.environ["MCP_NATIVE_BROKER_DIR"] = str(tmp_path)
    try:
        # 1) Extension -> native host handshake.
        _write_native_message(
            proc.stdin,
            {
                "type": "hello",
                "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                "extensionId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "extensionVersion": "pytest",
                "userAgent": "pytest",
                "profileId": "pytest-profile",
                "capabilities": {"debugger": True},
                "state": {"enabled": True, "followActive": False, "focusedTabId": None},
            },
        )

        ack = _read_native_message(proc.stdout, timeout_s=2.0)
        assert ack.get("type") == "helloAck"
        assert ack.get("transport") == "native"
        broker_id = str(ack.get("brokerId") or "").strip()
        assert broker_id

        # 2) Server peer connects via IPC.
        sock_path = broker_socket_path(broker_id)
        deadline = time.time() + 2.0
        while time.time() < deadline and not sock_path.exists():
            time.sleep(0.02)
        assert sock_path.exists()

        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.connect(str(sock_path))
        peer_fd = peer.fileno()

        _write_ipc_message(
            peer_fd,
            {
                "type": "peerHello",
                "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                "peerId": "pytest-peer",
                "pid": 123,
            },
        )
        peer_ack = _read_ipc_message(peer_fd, timeout_s=2.0)
        assert peer_ack.get("type") == "peerHelloAck"

        # 3) Peer -> broker -> extension: RPC forwarding + id translation.
        peer_req_id = 999
        _write_ipc_message(peer_fd, {"type": "rpc", "id": peer_req_id, "method": "tabs.list", "params": {}})
        rpc = _read_native_message(proc.stdout, timeout_s=2.0)
        assert rpc.get("type") == "rpc"
        assert rpc.get("method") == "tabs.list"
        req_id = rpc.get("id")
        assert req_id is not None
        assert req_id != peer_req_id  # broker must translate ids across peers

        _write_native_message(proc.stdin, {"type": "rpcResult", "id": req_id, "ok": True, "result": []})
        peer_res = _read_ipc_message(peer_fd, timeout_s=2.0)
        assert peer_res.get("type") == "rpcResult"
        assert peer_res.get("id") == peer_req_id
        assert peer_res.get("ok") is True
        assert peer_res.get("result") == []

        # 4) CDP event forwarding to subscribed peers.
        _write_ipc_message(
            peer_fd,
            {
                "type": "rpc",
                "id": 2,
                "method": "cdp.send",
                "params": {"tabId": "55", "method": "Page.enable", "params": {}},
            },
        )
        rpc2 = _read_native_message(proc.stdout, timeout_s=2.0)
        assert rpc2.get("type") == "rpc"
        req2 = rpc2.get("id")
        assert req2 is not None
        _write_native_message(proc.stdin, {"type": "rpcResult", "id": req2, "ok": True, "result": {}})
        peer_res2 = _read_ipc_message(peer_fd, timeout_s=2.0)
        assert peer_res2.get("type") == "rpcResult"
        assert peer_res2.get("id") == 2
        assert peer_res2.get("ok") is True

        _write_native_message(
            proc.stdin,
            {"type": "cdpEvent", "tabId": "55", "method": "Page.loadEventFired", "params": {"marker": 1}},
        )
        ev = _read_ipc_message(peer_fd, timeout_s=2.0)
        assert ev.get("type") == "cdpEvent"
        assert str(ev.get("tabId")) == "55"
        assert ev.get("method") == "Page.loadEventFired"
        assert isinstance(ev.get("params"), dict) and ev.get("params", {}).get("marker") == 1
    finally:
        if old_dir is None:
            with contextlib.suppress(Exception):
                del os.environ["MCP_NATIVE_BROKER_DIR"]
        else:
            os.environ["MCP_NATIVE_BROKER_DIR"] = old_dir
        if peer is not None:
            with contextlib.suppress(Exception):
                peer.close()
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2.0)
