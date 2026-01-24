from __future__ import annotations

import asyncio
import contextlib
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from .extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
from .native_broker_paths import broker_info_path, broker_socket_path, sanitize_broker_id

_MAX_FRAME_BYTES = 8_000_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _debug(message: str) -> None:
    if os.environ.get("MCP_NATIVE_HOST_DEBUG") != "1":
        return
    try:
        sys.stderr.write(f"[native_broker] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _read_exact_fd(fd: int, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_native_message() -> dict[str, Any] | None:
    """Read one Chrome Native Messaging frame from stdin (length-prefixed JSON)."""
    fd = sys.stdin.fileno()
    header = _read_exact_fd(fd, 4)
    if header is None:
        return None
    (length,) = struct.unpack("<I", header)
    if length <= 0 or length > _MAX_FRAME_BYTES:
        _debug(f"invalid native frame length: {length}")
        return None
    raw = _read_exact_fd(fd, int(length))
    if raw is None:
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        _debug("failed to decode native JSON")
        return None
    return obj if isinstance(obj, dict) else None


def write_native_message(msg: dict[str, Any]) -> None:
    """Write one Chrome Native Messaging frame to stdout (length-prefixed JSON)."""
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


async def _read_ipc_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    try:
        header = await reader.readexactly(4)
    except Exception:
        return None
    (length,) = struct.unpack("<I", header)
    if length <= 0 or length > _MAX_FRAME_BYTES:
        return None
    try:
        raw = await reader.readexactly(int(length))
    except Exception:
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


async def _write_ipc_message(writer: asyncio.StreamWriter, msg: dict[str, Any]) -> None:
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    writer.write(struct.pack("<I", len(raw)))
    writer.write(raw)
    await writer.drain()


@dataclass(slots=True)
class _Peer:
    peer_id: str
    writer: asyncio.StreamWriter
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tabs: set[str] = field(default_factory=set)


class NativeBroker:
    """Portless broker: Extension (native messaging) <-> Server peers (IPC).

    - Extension connects to this process via Chrome Native Messaging.
    - Browser MCP server processes connect via local IPC (Unix socket) and speak `peerHello` + `rpc`.
    - The broker multiplexes many peers into a single extension connection with id translation.
    """

    def __init__(self) -> None:
        self._broker_started_at_ms = _now_ms()
        self._broker_id = "default"
        self._socket_path = None

        self._ext_hello: dict[str, Any] | None = None
        self._ext_session_id: str | None = None
        self._ext_write_lock = asyncio.Lock()

        self._peers: dict[str, _Peer] = {}
        self._next_global_id = 1
        self._pending: dict[int, tuple[str, Any]] = {}  # global_id -> (peer_id, local_id)

    def _broker_info(self) -> dict[str, Any]:
        return {
            "type": "browserMcpNativeBroker",
            "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
            "brokerId": self._broker_id,
            "brokerPid": int(os.getpid()),
            "brokerStartedAtMs": int(self._broker_started_at_ms),
            "socketPath": str(self._socket_path or ""),
            "extensionConnected": bool(self._ext_hello is not None),
            "peerCount": int(len(self._peers)),
        }

    async def _ext_send(self, payload: dict[str, Any]) -> None:
        async with self._ext_write_lock:
            await asyncio.to_thread(write_native_message, payload)

    async def _peer_send(self, peer: _Peer, payload: dict[str, Any]) -> None:
        async with peer.write_lock:
            await _write_ipc_message(peer.writer, payload)

    def _peer_subscribe_if_tab(self, peer: _Peer, params: dict[str, Any]) -> None:
        tab_ref = params.get("tabId")
        if isinstance(tab_ref, (str, int)):
            tab_id = str(tab_ref).strip()
            if tab_id:
                peer.tabs.add(tab_id)

    async def _broadcast_cdp_event(self, tab_id: str, method: str, params: dict[str, Any]) -> None:
        if not tab_id or not method:
            return
        payload = {"type": "cdpEvent", "tabId": tab_id, "method": method, "params": params}
        for peer in list(self._peers.values()):
            if tab_id in peer.tabs:
                try:
                    await self._peer_send(peer, payload)
                except Exception:
                    # Best-effort: drop on write errors.
                    continue

    async def _handle_extension_message(self, msg: dict[str, Any]) -> None:
        mtype = str(msg.get("type") or "")

        if mtype == "rpcResult":
            raw_id = msg.get("id")
            if not isinstance(raw_id, (int, str)):
                return
            try:
                global_id = int(raw_id)
            except Exception:
                return
            rec = self._pending.pop(global_id, None)
            if not rec:
                return
            peer_id, local_id = rec
            peer = self._peers.get(peer_id)
            if peer is None:
                return
            out: dict[str, Any] = {"type": "rpcResult", "id": local_id, "ok": bool(msg.get("ok"))}
            if out["ok"]:
                out["result"] = msg.get("result")
            else:
                err = msg.get("error")
                if isinstance(err, dict):
                    out["error"] = err
                else:
                    out["error"] = {"message": "rpc failed"}
            await self._peer_send(peer, out)
            return

        if mtype == "cdpEvent":
            tab_id = str(msg.get("tabId") or "").strip()
            method = msg.get("method")
            if not tab_id or not isinstance(method, str) or not method:
                return
            params = msg.get("params")
            params_dict = params if isinstance(params, dict) else {}
            await self._broadcast_cdp_event(tab_id, method, params_dict)
            return

        if mtype == "ping":
            await self._ext_send({"type": "pong", "ts": _now_ms(), "peerCount": int(len(self._peers))})
            return

        # `log` and other message types are best-effort ignored by the broker.
        return

    async def _extension_loop(self) -> None:
        while True:
            msg = await asyncio.to_thread(read_native_message)
            if msg is None:
                return
            if not isinstance(msg, dict):
                continue
            await self._handle_extension_message(msg)

    async def _peer_dispatch(self, peer: _Peer, msg: dict[str, Any]) -> None:
        if msg.get("type") != "rpc":
            return

        req_id = msg.get("id")
        method = str(msg.get("method") or "").strip()
        raw_params = msg.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

        if params:
            self._peer_subscribe_if_tab(peer, params)

        if not method:
            await self._peer_send(
                peer, {"type": "rpcResult", "id": req_id, "ok": False, "error": {"message": "missing method"}}
            )
            return

        # Local broker methods (no extension roundtrip).
        if method == "gateway.status":
            await self._peer_send(peer, {"type": "rpcResult", "id": req_id, "ok": True, "result": self._broker_info()})
            return
        if method == "gateway.waitForConnection":
            await self._peer_send(peer, {"type": "rpcResult", "id": req_id, "ok": True, "result": {"connected": True}})
            return

        timeout_ms = msg.get("timeoutMs")
        try:
            timeout_ms_i = int(timeout_ms) if timeout_ms is not None else 0
        except Exception:
            timeout_ms_i = 0

        global_id = self._next_global_id
        self._next_global_id += 1
        self._pending[int(global_id)] = (peer.peer_id, req_id)

        fwd: dict[str, Any] = {"type": "rpc", "id": int(global_id), "method": method}
        if params:
            fwd["params"] = params
        if timeout_ms_i > 0:
            fwd["timeoutMs"] = int(timeout_ms_i)
        await self._ext_send(fwd)

    async def _peer_loop(self, peer: _Peer, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                msg = await _read_ipc_message(reader)
                if msg is None:
                    return
                await self._peer_dispatch(peer, msg)
        finally:
            self._peers.pop(peer.peer_id, None)
            # Drop any outstanding mappings for this peer.
            stale = [gid for gid, rec in self._pending.items() if rec[0] == peer.peer_id]
            for gid in stale:
                self._pending.pop(gid, None)

    async def _handle_peer_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        hello = await _read_ipc_message(reader)
        if not isinstance(hello, dict) or hello.get("type") != "peerHello":
            writer.close()
            return

        peer_id = str(hello.get("peerId") or "").strip()
        if not peer_id:
            peer_id = f"peer-{_now_ms()}-{os.getpid()}"
        peer = _Peer(peer_id=peer_id, writer=writer)
        self._peers[peer.peer_id] = peer

        try:
            await self._peer_send(
                peer,
                {
                    "type": "peerHelloAck",
                    "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                    "serverStartedAtMs": int(self._broker_started_at_ms),
                    "peerCount": int(len(self._peers)),
                },
            )
            await self._peer_loop(peer, reader)
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    def _write_registry(self) -> None:
        info_path = broker_info_path(self._broker_id)
        payload = self._broker_info()
        with contextlib.suppress(Exception):
            info_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _cleanup_registry(self) -> None:
        try:
            broker_info_path(self._broker_id).unlink(missing_ok=True)  # py3.11+
        except Exception:
            try:
                p = broker_info_path(self._broker_id)
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    async def run(self) -> int:
        # First message must be the extension hello.
        hello = await asyncio.to_thread(read_native_message)
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            _debug("missing/invalid hello from extension")
            return 2

        profile_id = str(hello.get("profileId") or "").strip()
        if not profile_id:
            profile_id = str(hello.get("extensionId") or "").strip() or "default"
        self._broker_id = sanitize_broker_id(profile_id)
        self._socket_path = broker_socket_path(self._broker_id)

        # Prepare socket path (best-effort cleanup of stale sockets).
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
        except Exception:
            pass

        if not hasattr(asyncio, "start_unix_server"):
            _debug("asyncio.start_unix_server unavailable on this platform")
            return 3

        # Start accepting server peers.
        server = await asyncio.start_unix_server(self._handle_peer_connection, path=str(self._socket_path))
        self._ext_hello = hello
        self._ext_session_id = f"broker-{_now_ms()}-{os.getpid()}"
        self._write_registry()

        # Ack extension.
        state = hello.get("state") if isinstance(hello.get("state"), dict) else None
        await self._ext_send(
            {
                "type": "helloAck",
                "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                "sessionId": str(self._ext_session_id),
                "serverVersion": os.environ.get("MCP_NATIVE_BROKER_VERSION") or "0.1.0",
                "serverStartedAtMs": int(self._broker_started_at_ms),
                "transport": "native",
                "brokerId": self._broker_id,
                "brokerPid": int(os.getpid()),
                "brokerStartedAtMs": int(self._broker_started_at_ms),
                "peerCount": int(len(self._peers)),
                **({"state": state} if isinstance(state, dict) else {}),
            }
        )

        _debug(f"broker ready: id={self._broker_id} socket={self._socket_path}")
        try:
            async with server:
                await self._extension_loop()
        finally:
            try:
                server.close()
                await server.wait_closed()
            except Exception:
                pass
            self._cleanup_registry()
            try:
                if self._socket_path and self._socket_path.exists():
                    self._socket_path.unlink()
            except Exception:
                pass
        return 0
