from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from .http_client import HttpClientError

EXTENSION_BRIDGE_PROTOCOL_VERSION = "2026-01-11"
EXTENSION_GATEWAY_WELL_KNOWN_PATH = "/.well-known/browser-mcp-gateway"


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


@dataclass(frozen=True)
class ExtensionClientInfo:
    extension_id: str
    extension_version: str | None = None
    user_agent: str | None = None
    capabilities: dict[str, Any] | None = None
    state: dict[str, Any] | None = None


class ExtensionGateway:
    """Local WebSocket gateway for the Browser MCP Chrome extension.

    Design goals:
    - Sync API for the server/tooling (blocking rpc_call / cdp_send / wait_for_event).
    - Async server internally (runs in a dedicated daemon thread).
    - Fail-closed: if extension is not connected or disabled, refuse commands.
    - Low noise: bounded event buffers; do not spam logs on flakey MV3 reconnects.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        expected_extension_id: str | None = None,
        on_cdp_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.host = (host or os.environ.get("MCP_EXTENSION_HOST") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            self.port = int(port or os.environ.get("MCP_EXTENSION_PORT") or 8765)
        except Exception:
            self.port = 8765

        # Keep the configured port stable for diagnostics. `self.port` may be updated to the
        # actual bound port when the gateway picks an adjacent free port.
        self._configured_port = int(self.port)
        self._last_bind_port: int | None = None

        self.expected_extension_id = (expected_extension_id or os.environ.get("MCP_EXTENSION_ID") or "").strip() or None
        self._on_cdp_event = on_cdp_event
        self._server_started_at_ms = _now_ms()

        self._lock = threading.Lock()
        self._events_lock = threading.Condition()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()

        # NOTE: explicitly typed as Any to avoid coupling this module to a specific
        # websockets protocol class across versions (keeps typecheckers calm).
        self._server: Any | None = None
        self._ws: Any | None = None
        self._bind_error: str | None = None

        self._session_id: str | None = None
        self._client: ExtensionClientInfo | None = None
        self._client_last_seen_ms: int = 0
        self._connected = threading.Event()

        self._next_id = 1
        self._pending: dict[int, Future] = {}

        # Connected peer clients (other Browser MCP processes) when running as the gateway.
        # This enables multi-CLI usage: multiple MCP servers can proxy through one extension.
        self._peers: dict[str, dict[str, Any]] = {}

        # tabId(str) -> deque of {"method": str, "params": dict}
        self._event_queues: dict[str, deque[dict[str, Any]]] = {}
        self._max_events_per_tab = 2500

        # small gateway log buffer (for diagnostics)
        self._logs: deque[dict[str, Any]] = deque(maxlen=200)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self, *, wait_timeout: float = 5.0, require_listening: bool = True) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop.clear()
        self._ready.clear()
        with self._lock:
            self._bind_error = None

        t = threading.Thread(target=self._run_thread, name="mcp-extension-gateway", daemon=True)
        self._thread = t
        t.start()

        deadline = time.time() + max(0.05, float(wait_timeout))
        # Wait for the server to actually bind (not just for the thread to start).
        # In extension mode we want "just works" behavior: if the default port is busy,
        # the gateway will try adjacent ports and (if needed) retry with backoff.
        while time.time() < deadline:
            with self._lock:
                server = self._server
                thread_alive = bool(self._thread and self._thread.is_alive())
            if server is not None:
                return
            if not thread_alive:
                break
            time.sleep(0.05)

        with self._lock:
            bind_error = self._bind_error
            server = self._server
            thread_alive = bool(self._thread and self._thread.is_alive())

        if server is not None:
            return

        if not thread_alive:
            raise RuntimeError(f"Extension gateway thread died during startup on {self.host}:{self.port}")

        # If the caller requires a bound listener, fail-fast with the latest bind error.
        if require_listening:
            if bind_error:
                raise RuntimeError(f"Extension gateway bind failed on {self.host}:{self.port}: {bind_error}")
            raise RuntimeError(f"Extension gateway failed to start on {self.host}:{self.port}")
        # Otherwise, fail-soft: the gateway thread will keep retrying to bind.
        return

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
            connected = self._ws is not None
            client = self._client
            sid = self._session_id
            last_seen = int(self._client_last_seen_ms or 0)
            bind_error = self._bind_error
            server = self._server
            thread_alive = bool(self._thread is not None and self._thread.is_alive())
            started_at = int(self._server_started_at_ms or 0)
            configured_port = self._configured_port
            last_bind_port = self._last_bind_port

        # Keep status payload small; candidates are only useful when we're not listening yet.
        candidates: list[int] = []
        truncated = False
        if server is None:
            try:
                candidates = self._port_candidates()
            except Exception:
                candidates = []
            if len(candidates) > 12:
                candidates = candidates[:12]
                truncated = True

        return {
            # listening means "a TCP listener is bound" (not just "thread exists").
            "listening": bool(server is not None),
            "host": self.host,
            "port": self.port,
            "configuredPort": configured_port,
            **({"lastBindPort": last_bind_port} if last_bind_port is not None else {}),
            **({"portCandidates": candidates} if candidates else {}),
            **({"portCandidatesTruncated": True} if truncated else {}),
            "connected": bool(connected),
            "sessionId": sid,
            **({"threadAlive": True} if thread_alive else {}),
            **({"bindError": bind_error} if bind_error else {}),
            **({"serverStartedAtMs": started_at} if started_at else {}),
            "client": (
                {
                    "extensionId": client.extension_id,
                    **({"extensionVersion": client.extension_version} if client.extension_version else {}),
                    **({"userAgent": client.user_agent} if client.user_agent else {}),
                    **({"capabilities": client.capabilities} if isinstance(client.capabilities, dict) else {}),
                    **({"state": client.state} if isinstance(client.state, dict) else {}),
                    **({"lastSeenMs": last_seen} if last_seen else {}),
                }
                if isinstance(client, ExtensionClientInfo)
                else None
            ),
        }

    def is_connected(self) -> bool:
        with self._lock:
            return self._ws is not None

    def wait_for_connection(self, *, timeout: float = 5.0) -> bool:
        """Block until an extension client is connected (handshake complete) or timeout."""
        try:
            return bool(self._connected.wait(timeout=max(0.0, float(timeout))))
        except Exception:
            return False

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
            if ws is None or loop is None:
                raise HttpClientError(
                    "Extension is not connected. Install/enable the extension and ensure it can connect to the gateway."
                )
            req_id = self._next_id
            self._next_id += 1
            fut = Future()
            self._pending[req_id] = fut

        msg: dict[str, Any] = {"type": "rpc", "id": req_id, "method": method}
        if isinstance(params, dict) and params:
            msg["params"] = params

        try:
            asyncio.run_coroutine_threadsafe(self._ws_send_json(ws, msg), loop).result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending.pop(int(req_id), None)
            raise HttpClientError(f"Extension RPC send failed: {exc}") from exc

        try:
            return fut.result(timeout=max(0.1, float(timeout)))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending.pop(int(req_id), None)
            raise HttpClientError(f"Extension RPC timed out: method={method}") from exc
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

    async def _rpc_call_async(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        """Async variant of rpc_call for use inside the gateway event loop.

        This is required to serve peer clients without blocking the asyncio loop.
        """
        if not isinstance(method, str) or not method.strip():
            raise HttpClientError("Extension RPC method is required")

        with self._lock:
            ws = self._ws
            if ws is None:
                raise HttpClientError(
                    "Extension is not connected. Install/enable the extension and ensure it can connect to the gateway."
                )
            req_id = self._next_id
            self._next_id += 1
            fut = Future()
            self._pending[req_id] = fut

        msg: dict[str, Any] = {"type": "rpc", "id": req_id, "method": method}
        if isinstance(params, dict) and params:
            msg["params"] = params

        try:
            await self._ws_send_json(ws, msg)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending.pop(int(req_id), None)
            raise HttpClientError(f"Extension RPC send failed: {exc}") from exc

        try:
            wrapped = asyncio.wrap_future(fut)
            return await asyncio.wait_for(wrapped, timeout=max(0.1, float(timeout)))
        except Exception as exc:  # noqa: BLE001
            raise HttpClientError(f"Extension RPC timed out: method={method}") from exc
        finally:
            with self._lock:
                self._pending.pop(int(req_id), None)

    def supports_cdp_send_many(self) -> bool:
        """Return True if the connected extension advertises cdpSendMany capability."""
        with self._lock:
            client = self._client
            caps = client.capabilities if isinstance(client, ExtensionClientInfo) else None
        if not isinstance(caps, dict):
            return False
        return bool(caps.get("cdpSendMany"))

    def supports_rpc_batch(self) -> bool:
        """Return True if the connected extension advertises rpcBatch capability."""
        with self._lock:
            client = self._client
            caps = client.capabilities if isinstance(client, ExtensionClientInfo) else None
        if not isinstance(caps, dict):
            return False
        return bool(caps.get("rpcBatch"))

    def rpc_call_many(
        self,
        calls: list[dict[str, Any]],
        *,
        timeout: float = 10.0,
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        """Batch multiple extension RPC calls into a single round-trip when supported.

        Each call is a dict:
        - method: str (required)
        - params: dict (optional)

        Returns a list of per-call results:
        - {ok:true, result:<any>}
        - {ok:false, error:<str>, method?:<str>}
        """
        if not isinstance(calls, list) or not calls:
            return []

        if self.supports_rpc_batch():
            res = self.rpc_call(
                "rpc.batch",
                {"calls": calls, "stopOnError": bool(stop_on_error)},
                timeout=timeout,
            )
            return res if isinstance(res, list) else []

        out: list[dict[str, Any]] = []
        for i, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            method = call.get("method")
            if not isinstance(method, str) or not method.strip():
                if stop_on_error:
                    raise HttpClientError(f"rpc_call_many failed at {i}: missing method")
                out.append({"ok": False, "error": "missing method"})
                continue
            params = call.get("params") if isinstance(call.get("params"), dict) else None
            try:
                out.append({"ok": True, "result": self.rpc_call(method, params, timeout=timeout)})
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if stop_on_error:
                    raise HttpClientError(f"rpc_call_many failed at {i}: {method}: {msg}") from exc
                out.append({"ok": False, "error": msg, "method": method})
        return out

    def cdp_send_many(
        self,
        tab_id: str,
        commands: list[dict[str, Any]],
        *,
        timeout: float = 10.0,
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        """Send multiple CDP commands in a single gateway round-trip (extension mode).

        Each command is a dict:
        - method: str (required)
        - params: dict (optional)
        - delayMs: int (optional)  # best-effort spacing between commands
        """
        tid = str(tab_id or "").strip()
        if not tid:
            raise HttpClientError("tab_id is required for CDP sendMany")
        if not isinstance(commands, list) or not commands:
            return []

        # Back-compat with older extensions: fall back to per-command RPC.
        if not self.supports_cdp_send_many():
            out: list[dict[str, Any]] = []
            for cmd in commands:
                if not isinstance(cmd, dict):
                    continue
                method = cmd.get("method")
                if not isinstance(method, str) or not method.strip():
                    raise HttpClientError("cdp_send_many: each command must include a non-empty 'method'")
                params = cmd.get("params") if isinstance(cmd.get("params"), dict) else None
                out.append(self.cdp_send(tid, method, params, timeout=timeout))
                try:
                    delay_ms = int(cmd.get("delayMs") or 0)
                except Exception:
                    delay_ms = 0
                if delay_ms > 0:
                    time.sleep(min(5.0, delay_ms / 1000.0))
            return out

        payload: dict[str, Any] = {"tabId": tid, "commands": commands, "stopOnError": bool(stop_on_error)}
        res = self.rpc_call("cdp.sendMany", payload, timeout=timeout)
        return res if isinstance(res, list) else []

    # ─────────────────────────────────────────────────────────────────────────
    # Events (tab-scoped)
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

        # Fast-path: consume queued.
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
    # Internals (async)
    # ─────────────────────────────────────────────────────────────────────────

    def _port_candidates(self) -> list[int]:
        """Port candidates for binding the local extension gateway.

        Default behavior:
        - Try MCP_EXTENSION_PORT (or 8765)
        - If busy, try a small adjacent range (port..port+10)

        Override:
        - MCP_EXTENSION_PORT_RANGE="8765-8775" (inclusive) to control the range.
        - MCP_EXTENSION_PORT_SPAN=10 to control the default span.
        """
        base = int(self.port or 8765)
        ports: list[int] = []

        def _add(p: int) -> None:
            if p < 1 or p > 65535:
                return
            if p not in ports:
                ports.append(p)

        _add(base)

        raw_range = (os.environ.get("MCP_EXTENSION_PORT_RANGE") or "").strip()
        if raw_range:
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", raw_range)
            if m:
                lo = int(m.group(1))
                hi = int(m.group(2))
                if lo > hi:
                    lo, hi = hi, lo
                for p in range(lo, hi + 1):
                    _add(p)
            return ports

        try:
            span = int(os.environ.get("MCP_EXTENSION_PORT_SPAN") or 10)
        except Exception:
            span = 10
        span = max(0, min(span, 250))
        for p in range(base, base + span + 1):
            _add(p)
        return ports

    def _run_thread(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        websockets = _import_websockets()
        # websockets 15+ exposes HTTP types via websockets.http11
        from websockets.datastructures import Headers as WsHeaders  # type: ignore[import-not-found]
        from websockets.http11 import Response as WsResponse  # type: ignore[import-not-found]

        async def _handler(ws):  # type: ignore[no-untyped-def]
            # Expect hello as first message.
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.5)
            except Exception:
                with self._lock:
                    self._logs.append({"ts": _now_ms(), "level": "warn", "message": "extension hello timeout"})
                return

            hello = None
            try:
                hello = json.loads(raw)
            except Exception:
                hello = None

            if not isinstance(hello, dict):
                with contextlib.suppress(Exception):
                    await ws.close(code=1002, reason="expected hello")
                return

            hello_type = str(hello.get("type") or "").strip()

            if hello_type == "peerHello":
                await _handle_peer_connection(ws, hello)
                return

            if hello_type != "hello":
                with contextlib.suppress(Exception):
                    await ws.close(code=1002, reason="expected hello")
                return

            ext_id = str(hello.get("extensionId") or "").strip()
            if not ext_id:
                with contextlib.suppress(Exception):
                    await ws.close(code=1002, reason="missing extensionId")
                return

            if self.expected_extension_id is not None and ext_id != self.expected_extension_id:
                with contextlib.suppress(Exception):
                    await ws.close(code=1008, reason="unexpected extensionId")
                return

            client = ExtensionClientInfo(
                extension_id=ext_id,
                extension_version=str(hello.get("extensionVersion") or "") or None,
                user_agent=str(hello.get("userAgent") or "") or None,
                capabilities=hello.get("capabilities") if isinstance(hello.get("capabilities"), dict) else None,
                state=hello.get("state") if isinstance(hello.get("state"), dict) else None,
            )

            session_id = f"ext-{int(time.time() * 1000)}-{os.getpid()}"

            # Replace active client (MV3 can reconnect often).
            with self._lock:
                self._ws = ws
                self._client = client
                self._session_id = session_id
                self._client_last_seen_ms = _now_ms()
                self._connected.clear()

            try:
                await self._ws_send_json(
                    ws,
                    {
                        "type": "helloAck",
                        "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                        "sessionId": session_id,
                        "serverVersion": os.environ.get("MCP_SERVER_VERSION") or "0.1.0",
                        "serverStartedAtMs": int(self._server_started_at_ms),
                        "gatewayPort": int(self.port),
                        **({"state": client.state} if isinstance(client.state, dict) else {}),
                    },
                )
            except Exception:
                # If ack fails, abort quickly.
                with self._lock:
                    self._ws = None
                    self._connected.clear()
                return
            self._connected.set()

            # Main receive loop.
            try:
                async for raw_msg in ws:
                    self._client_last_seen_ms = _now_ms()
                    msg = None
                    try:
                        msg = json.loads(raw_msg)
                    except Exception:
                        continue
                    await self._on_message(msg)
            except Exception:
                pass
            finally:
                self._disconnect()

        async def _peer_rpc_reply(
            ws,
            req_id: Any,
            *,
            ok: bool,
            result: Any = None,
            error: str | None = None,
        ) -> None:
            payload: dict[str, Any] = {"type": "rpcResult", "id": req_id, "ok": bool(ok)}
            if ok:
                payload["result"] = result
            else:
                payload["error"] = {"message": str(error or "unknown error")}
            with contextlib.suppress(Exception):
                await self._ws_send_json(ws, payload)

        async def _peer_dispatch(method: str, params: dict[str, Any], *, timeout: float) -> Any:
            m = str(method or "").strip()
            if not m:
                raise HttpClientError("peer rpc: missing method")

            if m == "gateway.status":
                return self.status()
            if m == "gateway.waitForConnection":
                ok = await asyncio.to_thread(self.wait_for_connection, timeout=timeout)
                return {"connected": bool(ok)}
            if m == "gateway.popEvent":
                tab_id = str(params.get("tabId") or "")
                event_name = str(params.get("eventName") or "")
                return self.pop_event(tab_id, event_name)
            if m == "gateway.waitForEvent":
                tab_id = str(params.get("tabId") or "")
                event_name = str(params.get("eventName") or "")
                ev = await asyncio.to_thread(self.wait_for_event, tab_id, event_name, timeout=timeout)
                return ev

            # Default: pass-through to the extension.
            return await self._rpc_call_async(m, params, timeout=timeout)

        async def _peer_loop(ws, peer_id: str) -> None:
            try:
                async for raw_msg in ws:
                    msg = None
                    try:
                        msg = json.loads(raw_msg)
                    except Exception:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") != "rpc":
                        continue

                    req_id = msg.get("id")
                    method = str(msg.get("method") or "")
                    raw_params = msg.get("params")
                    params: dict[str, Any] = {}
                    if isinstance(raw_params, dict):
                        for k, v in raw_params.items():
                            if isinstance(k, str):
                                params[k] = v

                    # Subscribe the peer to tab-scoped events when it references a tabId.
                    tab_ref = params.get("tabId")
                    if isinstance(tab_ref, (str, int)):
                        tab_s = str(tab_ref).strip()
                        if tab_s:
                            with self._lock:
                                peer = self._peers.get(peer_id)
                                tabs = peer.get("tabs") if isinstance(peer, dict) else None
                                if isinstance(tabs, set):
                                    tabs.add(tab_s)
                    try:
                        timeout_ms = int(msg.get("timeoutMs") or 0)
                    except Exception:
                        timeout_ms = 0
                    timeout = float(timeout_ms / 1000.0) if timeout_ms > 0 else 10.0
                    timeout = max(0.1, min(timeout, 60.0))

                    try:
                        res = await _peer_dispatch(method, params, timeout=timeout)
                        await _peer_rpc_reply(ws, req_id, ok=True, result=res)
                    except Exception as exc:  # noqa: BLE001
                        await _peer_rpc_reply(ws, req_id, ok=False, error=str(exc))
            finally:
                with self._lock:
                    self._peers.pop(peer_id, None)

        async def _handle_peer(ws, hello_msg: dict[str, Any]) -> None:
            peer_id = str(hello_msg.get("peerId") or "").strip() or f"peer-{int(time.time() * 1000)}-{os.getpid()}"
            with self._lock:
                self._peers[peer_id] = {
                    "peerId": peer_id,
                    "pid": int(hello_msg.get("pid") or 0) if str(hello_msg.get("pid") or "").isdigit() else None,
                    "startedAtMs": int(time.time() * 1000),
                    "tabs": set(),
                    "ws": ws,
                }

            with contextlib.suppress(Exception):
                await self._ws_send_json(
                    ws,
                    {
                        "type": "peerHelloAck",
                        "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                        "gatewayPort": int(self.port),
                        "serverStartedAtMs": int(self._server_started_at_ms),
                    },
                )

            await _peer_loop(ws, peer_id)

        async def _handle_peer_connection(ws, hello_msg: dict[str, Any]) -> None:
            await _handle_peer(ws, hello_msg)

        def _maybe_build_well_known_response(request) -> WsResponse | None:  # type: ignore[name-defined]
            """Serve a tiny HTTP discovery endpoint on the WS port.

            Why:
            - The Chrome extension can probe ports with `fetch()` (quiet) and only open a WebSocket
              to the best (newest) gateway, instead of spamming failed `new WebSocket(...)` attempts
              that appear as noisy errors in the extension console.
            """
            try:
                path = str(getattr(request, "path", "") or "")
                if path != EXTENSION_GATEWAY_WELL_KNOWN_PATH:
                    return None

                with self._lock:
                    ext_connected = self._ws is not None
                    peer_count = len(self._peers)

                payload = {
                    "type": "browserMcpGateway",
                    "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
                    "serverVersion": os.environ.get("MCP_SERVER_VERSION") or "0.1.0",
                    "serverStartedAtMs": int(self._server_started_at_ms),
                    "gatewayPort": int(self.port),
                    "pid": int(os.getpid()),
                    "extensionConnected": bool(ext_connected),
                    "peerCount": int(peer_count),
                }
                body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

                headers = WsHeaders()
                headers["Content-Type"] = "application/json"
                headers["Cache-Control"] = "no-store"
                headers["Access-Control-Allow-Origin"] = "*"
                headers["X-Browser-MCP-Gateway"] = "1"
                return WsResponse(200, "OK", headers, body)
            except Exception:
                return None

        def _http_not_found() -> WsResponse:  # type: ignore[name-defined]
            headers = WsHeaders()
            headers["Content-Type"] = "text/plain"
            headers["Cache-Control"] = "no-store"
            headers["Access-Control-Allow-Origin"] = "*"
            return WsResponse(404, "Not Found", headers, b"not found")

        async def _process_request(_conn, request):  # type: ignore[no-untyped-def]
            try:
                # If this is a WS upgrade request, let the normal handshake proceed.
                try:
                    upgrade = str(request.headers.get("Upgrade") or "").lower()
                except Exception:
                    upgrade = ""
                if upgrade == "websocket":
                    return None

                # Otherwise, only serve the discovery endpoint and return 404 for everything else.
                resp = _maybe_build_well_known_response(request)
                if resp is not None:
                    return resp
                return _http_not_found()
            except Exception:
                # Fail-open: if our HTTP handling breaks, don't wedge WS handshakes.
                return None

        # Keep retrying bind with backoff until stop. This makes extension mode resilient
        # when multiple Codex sessions race for the default port.
        backoff_s = 0.25
        max_backoff_s = 5.0

        try:
            self._loop = asyncio.get_running_loop()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._bind_error = str(exc)
                self._logs.append({"ts": _now_ms(), "level": "error", "message": f"gateway loop failed: {exc}"})
            return

        # Signal that the thread is alive; actual listening is reflected via status().
        self._ready.set()

        try:
            while not self._stop.is_set():
                with self._lock:
                    has_server = self._server is not None
                if has_server:
                    await asyncio.sleep(0.25)
                    continue

                bind_error: str | None = None
                server = None
                selected_port = None
                last_attempted_port: int | None = None

                for port in self._port_candidates():
                    last_attempted_port = int(port)
                    try:
                        server = await websockets.serve(
                            _handler,
                            self.host,
                            int(port),
                            # Some Chrome contexts may omit Origin on localhost WS connects; allow it.
                            origins=[None, re.compile(r"^null$"), re.compile(r"^chrome-extension://[a-p]{32}/?$")],
                            process_request=_process_request,
                            max_size=2_000_000,
                            ping_interval=None,
                        )
                        selected_port = int(port)
                        break
                    except OSError as exc:
                        bind_error = str(exc)
                        if getattr(exc, "errno", None) in {errno.EADDRINUSE, errno.EACCES}:
                            continue
                        break
                    except Exception as exc:  # noqa: BLE001
                        bind_error = str(exc)
                        break

                if server is not None:
                    with self._lock:
                        self._server = server
                        if selected_port is not None:
                            self.port = int(selected_port)
                        self._last_bind_port = int(selected_port) if selected_port is not None else last_attempted_port
                        self._bind_error = None
                        self._logs.append(
                            {
                                "ts": _now_ms(),
                                "level": "info",
                                "message": f"gateway listening on {self.host}:{self.port}",
                            }
                        )
                    backoff_s = 0.25
                    await asyncio.sleep(0.05)
                    continue

                # Bind failed on all candidates (or fatally). Keep state for diagnostics and retry.
                with self._lock:
                    self._bind_error = bind_error or "unknown bind error"
                    self._last_bind_port = last_attempted_port
                    # Low-noise: only keep a bounded log buffer, callers can query status().
                    self._logs.append(
                        {
                            "ts": _now_ms(),
                            "level": "error",
                            "message": f"gateway bind failed: {self._bind_error}",
                        }
                    )

                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.6, max_backoff_s)
        finally:
            await self._shutdown_async()

    async def _shutdown_async(self) -> None:
        srv = self._server
        self._server = None
        try:
            if srv is not None:
                srv.close()
                await srv.wait_closed()  # type: ignore[misc]
        except Exception:
            pass

        ws = None
        with self._lock:
            ws = self._ws
        try:
            if ws is not None:
                await ws.close()  # type: ignore[misc]
        except Exception:
            pass
        self._disconnect()

    def _disconnect(self) -> None:
        with self._lock:
            self._ws = None
            self._client = None
            self._session_id = None
            self._client_last_seen_ms = 0
            self._connected.clear()
            pending = list(self._pending.items())
            self._pending.clear()

        for _req_id, fut in pending:
            try:
                if not fut.done():
                    fut.set_exception(HttpClientError("Extension disconnected"))
            except Exception:
                pass

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
                fut.set_exception(HttpClientError(err_msg or "Extension RPC failed"))
            return

        if mtype == "cdpEvent":
            tab_id = str(msg.get("tabId") or "").strip()
            method = msg.get("method")
            if not tab_id or not isinstance(method, str) or not method:
                return
            params = msg.get("params")
            params_dict = params if isinstance(params, dict) else {}
            ev: dict[str, Any] = {"method": method, "params": params_dict}

            # Queue (bounded) for server-side waits.
            with self._events_lock:
                q = self._event_queues.get(tab_id)
                if q is None:
                    q = deque()
                    self._event_queues[tab_id] = q
                q.append(ev)
                if len(q) > self._max_events_per_tab:
                    for _ in range(len(q) - self._max_events_per_tab):
                        try:
                            q.popleft()
                        except Exception:
                            break
                self._events_lock.notify_all()

            # Tier-0 ingest hook (best-effort).
            cb = self._on_cdp_event
            if cb is not None:
                with contextlib.suppress(Exception):
                    cb(tab_id, ev)

            # Forward to subscribed peers (multi-CLI support).
            peers = []
            with self._lock:
                for rec in self._peers.values():
                    if not isinstance(rec, dict):
                        continue
                    ws_peer = rec.get("ws")
                    tabs = rec.get("tabs")
                    if ws_peer is None or not isinstance(tabs, set):
                        continue
                    if tab_id in tabs:
                        peers.append(ws_peer)
            if peers:
                payload = {"type": "cdpEvent", "tabId": tab_id, "method": method, "params": params_dict}
                with contextlib.suppress(Exception):
                    await asyncio.gather(
                        *[self._ws_send_json(w, payload) for w in peers],
                        return_exceptions=True,
                    )
            return

        if mtype == "log":
            try:
                level = str(msg.get("level") or "info")
                message = str(msg.get("message") or "")
                meta = msg.get("meta")
            except Exception:
                return
            with self._lock:
                self._logs.append(
                    {
                        "ts": _now_ms(),
                        "level": level if level in {"debug", "info", "warn", "error"} else "info",
                        "message": message[:2000],
                        **({"meta": meta} if isinstance(meta, dict) else {}),
                    }
                )
            return

        if mtype == "ping":
            ws = None
            with self._lock:
                ws = self._ws
            if ws is None:
                return
            try:
                await self._ws_send_json(ws, {"type": "pong", "ts": _now_ms()})
            except Exception:
                return
            return

    async def _ws_send_json(self, ws, payload: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
        await ws.send(json.dumps(payload, ensure_ascii=False))
