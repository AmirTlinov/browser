from __future__ import annotations

import contextlib
import json
import os
import select
import struct
import subprocess
import sys
import threading
import time
from typing import Any

import pytest


def _read_exact(fp, n: int, *, timeout_s: float) -> bytes:
    buf = bytearray()
    fd = fp.fileno()
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


def test_native_gateway_peer_rpc_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
    from mcp_servers.browser.extension_gateway_native_peer import NativeExtensionGatewayPeer

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

    stop = threading.Event()
    t: threading.Thread | None = None

    def _extension_responder() -> None:
        while not stop.is_set():
            try:
                msg = _read_native_message(proc.stdout, timeout_s=0.2)
            except TimeoutError:
                continue
            except Exception:
                return
            if msg.get("type") != "rpc":
                continue
            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            if method == "tabs.list":
                _write_native_message(proc.stdin, {"type": "rpcResult", "id": req_id, "ok": True, "result": []})
                continue
            if method == "cdp.send":
                # Ensure the broker subscribes the peer when tabId is present.
                assert str(params.get("tabId") or "") == "55"
                _write_native_message(proc.stdin, {"type": "rpcResult", "id": req_id, "ok": True, "result": {}})
                continue
            _write_native_message(
                proc.stdin,
                {"type": "rpcResult", "id": req_id, "ok": False, "error": {"message": f"unknown method: {method}"}},
            )

    try:
        # Extension hello (starts the broker + IPC listener).
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

        # Start responding to broker-forwarded RPCs only after we consumed the handshake.
        t = threading.Thread(target=_extension_responder, name="native-extension-responder", daemon=True)
        t.start()

        # Point the peer client to our tmp broker dir.
        monkeypatch.setenv("MCP_NATIVE_BROKER_DIR", str(tmp_path))

        gw = NativeExtensionGatewayPeer()
        gw.start(wait_timeout=0.2)
        assert gw.wait_for_connection(timeout=2.0) is True

        assert gw.rpc_call("tabs.list", {}, timeout=2.0) == []
        assert gw.cdp_send("55", "Page.enable", {}, timeout=2.0) == {}
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2.0)
        if t is not None:
            t.join(timeout=1.0)
