from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from .extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
from .extension_gateway_discovery import discover_best_gateway
from .http_client import HttpClientError


def _now_ms() -> int:
    return int(time.time() * 1000)


def _import_websockets():
    try:
        import websockets  # type: ignore[import-not-found]

        return websockets
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Extension mode requires the 'websockets' Python package. "
            "Install it (pip install websockets) or switch MCP_BROWSER_MODE to launch/attach."
        ) from exc


class ExtensionGatewayPeer:
    """Peer client that proxies through a leader ExtensionGateway.

    This enables multi-CLI concurrency: only one process binds the local gateway port(s),
    other processes connect as peers and share the single Chrome extension connection.
    """

    # Used by SessionManager to avoid adopting the user's active tab in multi-client mode.
    is_proxy = True

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

        self._ws: Any | None = None
        self._peer_id = f"peer-{int(time.time() * 1000)}-{os.getpid()}"

        self._gateway_host: str | None = None
        self._gateway_port: int | None = None
        self._leader_started_at_ms: int | None = None
        self._extension_connected: bool = False
        self._last_error: str | None = None

        self._next_id = 1
        self._pending: dict[int, Future] = {}

        self._event_queues: dict[str, deque[dict[str, Any]]] = {}
        self._max_events_per_tab = 2500

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self, *, wait_timeout: float = 0.2) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._connected.clear()

        t = threading.Thread(target=self._run_thread, name="mcp-extension-peer", daemon=True)
        self._thread = t
        t.start()

        # Best-effort: don't block the MCP initialize handshake.
        deadline = time.time() + max(0.0, float(wait_timeout))
        while time.time() < deadline:
            with self._lock:
                if self._ws is not None:
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

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "listening": False,
                "connected": bool(self._extension_connected),
                "peerConnected": self._connected.is_set(),
                "peerId": self._peer_id,
                **({"gatewayHost": self._gateway_host} if self._gateway_host else {}),
                **({"gatewayPort": self._gateway_port} if isinstance(self._gateway_port, int) else {}),
                **(
                    {"leaderStartedAtMs": self._leader_started_at_ms}
                    if isinstance(self._leader_started_at_ms, int)
                    else {}
                ),
                **({"lastError": self._last_error} if self._last_error else {}),
            }

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._extension_connected)

    def wait_for_connection(self, *, timeout: float = 5.0) -> bool:
        # First wait for the peer socket to be connected.
        try:
            self._connected.wait(timeout=max(0.0, float(timeout)))
        except Exception:
            return False

        # Then wait for the leader to report extension-connected.
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            if self.is_connected():
                return True
            # Ask the leader to block until extension connects (bounded).
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

        ws = None
        loop = None
        req_id = None
        fut: Future | None = None

        with self._lock:
            ws = self._ws
            loop = self._loop

        # Best-effort: give the background peer thread a short chance to connect.
        if (ws is None or loop is None) and self._wait_for_peer_socket(timeout=1.5):
            with self._lock:
                ws = self._ws
                loop = self._loop

        if ws is None or loop is None:
            raise HttpClientError(
                "Extension peer is not connected. Start another Browser MCP session as leader, "
                "or wait for the gateway to appear."
            )

        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            fut = Future()
            self._pending[req_id] = fut

        msg: dict[str, Any] = {"type": "rpc", "id": req_id, "method": method, "timeoutMs": int(timeout * 1000)}
        if isinstance(params, dict) and params:
            msg["params"] = params

        try:
            asyncio.run_coroutine_threadsafe(self._ws_send_json(ws, msg), loop).result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending.pop(int(req_id), None)
            raise HttpClientError(f"Extension peer send failed: {exc}") from exc

        try:
            return fut.result(timeout=max(0.1, float(timeout)))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending.pop(int(req_id), None)
            raise HttpClientError(f"Extension peer RPC timed out: method={method}") from exc
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
        tid = str(tab_id or "").strip()
        if not tid:
            raise HttpClientError("tab_id is required for CDP send")
        if not isinstance(method, str) or not method.strip():
            raise HttpClientError("CDP method is required")
        payload: dict[str, Any] = {"tabId": tid, "method": method}
        if isinstance(params, dict) and params:
            payload["params"] = params
        res = self.rpc_call("cdp.send", payload, timeout=timeout)
        return res if isinstance(res, dict) else {}

    def cdp_send_many(
        self,
        tab_id: str,
        commands: list[dict[str, Any]],
        *,
        timeout: float = 10.0,
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        tid = str(tab_id or "").strip()
        if not tid:
            raise HttpClientError("tab_id is required for CDP sendMany")
        if not isinstance(commands, list) or not commands:
            return []

        payload: dict[str, Any] = {"tabId": tid, "commands": commands, "stopOnError": bool(stop_on_error)}
        res = self.rpc_call("cdp.sendMany", payload, timeout=timeout)
        return res if isinstance(res, list) else []

    # ─────────────────────────────────────────────────────────────────────────
    # Events
    # ─────────────────────────────────────────────────────────────────────────

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

        queued = self.pop_event(tid, name)
        if queued is not None:
            return queued

        deadline = time.time() + max(0.0, float(timeout))
        with self._events_lock:
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._events_lock.wait(timeout=min(0.2, remaining))
                queued = self.pop_event(tid, name)
                if queued is not None:
                    return queued
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _run_thread(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        websockets = _import_websockets()
        backoff_s = 0.25
        max_backoff_s = 5.0

        try:
            self._loop = asyncio.get_running_loop()
        except Exception:
            self._loop = None

        async def _poll_status(ws) -> None:  # type: ignore[no-untyped-def]
            while not self._stop.is_set():
                await asyncio.sleep(1.0)
                try:
                    st = await self._peer_rpc(ws, "gateway.status", {}, timeout=1.0)
                except Exception:
                    continue
                if isinstance(st, dict):
                    with self._lock:
                        self._extension_connected = bool(st.get("connected"))

        while not self._stop.is_set():
            disc = None
            try:
                disc = discover_best_gateway(timeout=0.25, require_peers=True)
            except Exception:
                disc = None

            if disc is None:
                with self._lock:
                    self._last_error = "No gateway discovered"
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.6, max_backoff_s)
                continue

            ws_url = f"ws://{disc.host}:{int(disc.port)}"

            try:
                async with websockets.connect(ws_url, ping_interval=None, open_timeout=1.5) as ws:
                    with self._lock:
                        self._ws = ws
                        self._gateway_host = disc.host
                        self._gateway_port = int(disc.port)
                        self._leader_started_at_ms = int(disc.server_started_at_ms)
                        self._extension_connected = bool(disc.extension_connected)
                        self._last_error = None
                    backoff_s = 0.25

                    hello = {
                        "type": "peerHello",
                        "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                        "peerId": self._peer_id,
                        "pid": int(os.getpid()),
                        "clientStartedAtMs": int(_now_ms()),
                    }
                    await self._ws_send_json(ws, hello)
                    try:
                        raw_ack = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(f"peer helloAck timeout: {exc}") from exc
                    ack = None
                    try:
                        ack = json.loads(raw_ack)
                    except Exception:
                        ack = None
                    if not (isinstance(ack, dict) and ack.get("type") == "peerHelloAck"):
                        raise RuntimeError("peer helloAck invalid")

                    # Mark peer as ready only after a successful hello/ack handshake.
                    self._connected.set()

                    poll_task = asyncio.create_task(_poll_status(ws))

                    try:
                        async for raw in ws:
                            msg = None
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            await self._on_message(msg)
                    finally:
                        poll_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await poll_task
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._last_error = str(exc)
                self._disconnect()
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.6, max_backoff_s)

        await self._shutdown_async()

    async def _shutdown_async(self) -> None:
        ws = None
        with self._lock:
            ws = self._ws
        try:
            if ws is not None:
                await ws.close()
        except Exception:
            pass
        self._disconnect()

    def _disconnect(self) -> None:
        with self._lock:
            self._ws = None
            self._extension_connected = False
            self._connected.clear()
            pending = list(self._pending.items())
            self._pending.clear()
        for _req_id, fut in pending:
            with contextlib.suppress(Exception):
                if not fut.done():
                    fut.set_exception(HttpClientError("Extension peer disconnected"))

    def _wait_for_peer_socket(self, *, timeout: float) -> bool:
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() < deadline:
            with self._lock:
                if self._ws is not None and self._loop is not None and self._connected.is_set():
                    return True
            # Give the peer thread a chance to connect.
            with contextlib.suppress(Exception):
                self._connected.wait(timeout=0.05)
        return False

    async def _peer_rpc(self, ws, method: str, params: dict[str, Any], *, timeout: float) -> Any:  # type: ignore[no-untyped-def]
        req_id = None
        fut: Future | None = None
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            fut = Future()
            self._pending[req_id] = fut

        msg: dict[str, Any] = {
            "type": "rpc",
            "id": req_id,
            "method": method,
            "timeoutMs": int(timeout * 1000),
            "params": params,
        }
        await self._ws_send_json(ws, msg)
        try:
            wrapped = asyncio.wrap_future(fut)
            return await asyncio.wait_for(wrapped, timeout=max(0.1, float(timeout)))
        finally:
            with self._lock:
                self._pending.pop(int(req_id), None)

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
                fut.set_exception(HttpClientError(err_msg or "Extension peer RPC failed"))
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

    async def _ws_send_json(self, ws, payload: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
        await ws.send(json.dumps(payload, ensure_ascii=False))
