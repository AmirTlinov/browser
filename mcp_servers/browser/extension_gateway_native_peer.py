from __future__ import annotations

import asyncio
import contextlib
import json
import os
import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from .extension_auto_launcher import ExtensionAutoLauncher
from .extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
from .extension_leader_lock import default_leader_lock
from .http_client import HttpClientError
from .native_broker_discovery import BrokerDiscovery, discover_best_broker

_MAX_FRAME_BYTES = 8_000_000


def _now_ms() -> int:
    return int(time.time() * 1000)


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


class NativeExtensionGatewayPeer:
    """Peer client that talks to the local native broker over IPC (no TCP ports).

    The broker is started by the Chrome extension via Native Messaging.
    This client discovers the best broker and proxies all RPC/CDP through it.
    """

    def __init__(
        self,
        *,
        on_cdp_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_cdp_event = on_cdp_event

        self._lock = threading.Lock()
        self._events_lock = threading.Condition()
        self._stop = threading.Event()
        self._connected = threading.Event()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        self._peer_id = f"peer-{_now_ms()}-{os.getpid()}"
        self._broker: BrokerDiscovery | None = None
        self._extension_connected: bool = False
        self._last_error: str | None = None

        self._next_id = 1
        self._pending: dict[int, Future] = {}

        self._event_queues: dict[str, deque[dict[str, Any]]] = {}
        self._max_events_per_tab = 2500

        # Multi-client safety: only one process is allowed to behave as "leader" for UX decisions.
        self._leader_lock = default_leader_lock()
        self.is_proxy = not self._leader_lock.try_acquire()
        self._auto_launcher = ExtensionAutoLauncher()
        self._auto_launch_attempted = False

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self, *, wait_timeout: float = 0.2) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._connected.clear()

        t = threading.Thread(target=self._run_thread, name="mcp-native-gateway-peer", daemon=True)
        self._thread = t
        t.start()

        # Best-effort: don't block MCP initialize.
        deadline = time.time() + max(0.0, float(wait_timeout))
        while time.time() < deadline:
            with self._lock:
                if self._writer is not None:
                    return
            time.sleep(0.01)

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop).result(timeout=timeout)
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
        self._leader_lock.release()

    def status(self) -> dict[str, Any]:
        with self._lock:
            broker = self._broker
            return {
                "listening": False,
                "connected": bool(self._extension_connected),
                "peerConnected": self._connected.is_set(),
                "peerId": self._peer_id,
                "transport": "native",
                **({"brokerId": broker.broker_id} if broker else {}),
                **({"brokerSocket": str(broker.socket_path)} if broker else {}),
                **({"brokerStartedAtMs": broker.broker_started_at_ms} if broker else {}),
                **({"lastError": self._last_error} if self._last_error else {}),
                **({"role": "peer" if self.is_proxy else "leader"}),
            }

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._extension_connected)

    def wait_for_connection(self, *, timeout: float = 5.0) -> bool:
        try:
            self._connected.wait(timeout=max(0.0, float(timeout)))
        except Exception:
            return False

        # If we can become leader (UX-only), do it.
        if self.is_proxy and self._leader_lock.try_acquire():
            self.is_proxy = False

        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            if self.is_connected():
                return True
            remaining = max(0.0, deadline - time.time())
            try:
                res = self.rpc_call("gateway.waitForConnection", {}, timeout=min(remaining, 2.0))
                if isinstance(res, dict) and res.get("connected") is True:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return self.is_connected()

    # ─────────────────────────────────────────────────────────────────────────
    # RPC + CDP
    # ─────────────────────────────────────────────────────────────────────────

    def rpc_call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        if not isinstance(method, str) or not method.strip():
            raise HttpClientError("Extension RPC method is required")

        loop = None
        writer = None
        with self._lock:
            loop = self._loop
            writer = self._writer

        if (loop is None or writer is None) and self._wait_for_peer_socket(timeout=1.5):
            with self._lock:
                loop = self._loop
                writer = self._writer

        if loop is None or writer is None:
            raise HttpClientError(
                "Native broker is not connected. Ensure the Browser MCP extension is installed/enabled and the native host is installed."
            )

        req_id = None
        fut: Future | None = None
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            fut = Future()
            self._pending[req_id] = fut

        msg: dict[str, Any] = {"type": "rpc", "id": req_id, "method": method, "timeoutMs": int(timeout * 1000)}
        if isinstance(params, dict) and params:
            msg["params"] = params

        try:
            asyncio.run_coroutine_threadsafe(self._ipc_send(writer, msg), loop).result(timeout=timeout)
            return fut.result(timeout=max(0.1, float(timeout)))
        except Exception as exc:  # noqa: BLE001
            raise HttpClientError(str(exc)) from exc
        finally:
            with self._lock:
                self._pending.pop(int(req_id), None)

    def cdp_send(
        self,
        tab_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        res = self.rpc_call(
            "cdp.send",
            {"tabId": str(tab_id), "method": str(method), **({"params": params} if isinstance(params, dict) else {})},
            timeout=timeout,
        )
        return res if isinstance(res, dict) else {}

    def cdp_send_many(
        self,
        tab_id: str,
        commands: list[dict[str, Any]],
        *,
        timeout: float = 10.0,
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        res = self.rpc_call(
            "cdp.sendMany",
            {"tabId": str(tab_id), "commands": list(commands or []), "stopOnError": bool(stop_on_error)},
            timeout=timeout,
        )
        return res if isinstance(res, list) else []

    def pop_event(self, tab_id: str, event_name: str) -> dict[str, Any] | None:
        tid = str(tab_id or "").strip()
        name = str(event_name or "").strip()
        if not tid or not name:
            return None
        with self._events_lock:
            q = self._event_queues.get(tid)
            if not q:
                return None
            for i in range(len(q)):
                ev = q[i]
                if ev.get("method") == name:
                    q.remove(ev)
                    params = ev.get("params")
                    return params if isinstance(params, dict) else {}
        return None

    def wait_for_event(self, tab_id: str, event_name: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
        tid = str(tab_id or "").strip()
        name = str(event_name or "").strip()
        if not tid or not name:
            return None
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            ev = self.pop_event(tid, name)
            if ev is not None:
                return ev
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            with self._events_lock:
                self._events_lock.wait(timeout=min(0.25, max(0.01, remaining)))
        return self.pop_event(tid, name)

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _run_thread(self) -> None:
        asyncio.run(self._run_async())

    async def _shutdown_async(self) -> None:
        with self._lock:
            writer = self._writer
            self._writer = None
            self._reader = None
            self._extension_connected = False
            self._broker = None
            self._connected.clear()
            pending = list(self._pending.items())
            self._pending.clear()
        for _req_id, fut in pending:
            with contextlib.suppress(Exception):
                if not fut.done():
                    fut.set_exception(HttpClientError("Native broker disconnected"))
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    def _wait_for_peer_socket(self, *, timeout: float) -> bool:
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            if self._stop.is_set():
                return False
            with self._lock:
                if self._writer is not None:
                    return True
            time.sleep(0.03)
        return False

    async def _ipc_send(self, writer: asyncio.StreamWriter, msg: dict[str, Any]) -> None:
        await _write_ipc_message(writer, msg)

    async def _connect_once(self, disc: BrokerDiscovery) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        try:
            reader, writer = await asyncio.open_unix_connection(str(disc.socket_path))
        except Exception:
            return None

        try:
            await _write_ipc_message(
                writer,
                {
                    "type": "peerHello",
                    "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                    "peerId": self._peer_id,
                    "pid": int(os.getpid()),
                },
            )
            ack = await asyncio.wait_for(_read_ipc_message(reader), timeout=1.0)
            if not (isinstance(ack, dict) and ack.get("type") == "peerHelloAck"):
                writer.close()
                return None
        except Exception:
            with contextlib.suppress(Exception):
                writer.close()
            return None
        return reader, writer

    async def _run_async(self) -> None:
        self._loop = asyncio.get_running_loop()

        backoff_s = 0.15
        while not self._stop.is_set():
            disc = None
            try:
                disc = discover_best_broker(timeout=0.15)
            except Exception:
                disc = None

            if disc is None:
                with self._lock:
                    self._last_error = "Native broker not found (is the extension connected?)"
                if not self._auto_launch_attempted:
                    self._auto_launch_attempted = True
                    self._auto_launcher.ensure_running()
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.6, 0.8)
                continue

            conn = await self._connect_once(disc)
            if conn is None:
                with self._lock:
                    self._last_error = f"Native broker unreachable: {disc.socket_path}"
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.6, 0.8)
                continue

            reader, writer = conn
            with self._lock:
                self._reader = reader
                self._writer = writer
                self._broker = disc
                self._extension_connected = True
                self._last_error = None
                self._connected.set()

            backoff_s = 0.15

            # Main receive loop.
            try:
                while not self._stop.is_set():
                    msg = await _read_ipc_message(reader)
                    if msg is None:
                        break
                    await self._on_message(msg)
            finally:
                await self._shutdown_async()

    async def _on_message(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        mtype = msg.get("type")

        if mtype == "rpcResult":
            raw_id = msg.get("id")
            if not isinstance(raw_id, (int, str)):
                return
            try:
                req_id = int(raw_id)
            except Exception:
                return
            ok = bool(msg.get("ok"))
            with self._lock:
                fut = self._pending.get(req_id)
            if fut is None:
                return
            if ok:
                with contextlib.suppress(Exception):
                    fut.set_result(msg.get("result"))
                return
            err = msg.get("error")
            err_msg = None
            if isinstance(err, dict) and isinstance(err.get("message"), str):
                err_msg = err.get("message")
            with contextlib.suppress(Exception):
                fut.set_exception(HttpClientError(err_msg or "Native broker RPC failed"))
            return

        if mtype == "cdpEvent":
            tab_id = str(msg.get("tabId") or "").strip()
            method = msg.get("method")
            if not tab_id or not isinstance(method, str) or not method:
                return
            params = msg.get("params")
            ev: dict[str, Any] = {"method": method, "params": params if isinstance(params, dict) else {}}

            with self._events_lock:
                q = self._event_queues.get(tab_id)
                if q is None:
                    q = deque()
                    self._event_queues[tab_id] = q
                q.append(ev)
                if len(q) > self._max_events_per_tab:
                    for _ in range(len(q) - self._max_events_per_tab):
                        with contextlib.suppress(Exception):
                            q.popleft()
                self._events_lock.notify_all()

            cb = self._on_cdp_event
            if cb is not None:
                with contextlib.suppress(Exception):
                    cb(tab_id, ev)
            return
