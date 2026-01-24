from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION, EXTENSION_GATEWAY_WELL_KNOWN_PATH


@dataclass(frozen=True, slots=True)
class GatewayDiscovery:
    host: str
    port: int
    server_started_at_ms: int
    extension_connected: bool
    peer_count: int
    supports_peers: bool
    protocol_version: str
    server_version: str
    pid: int


def _port_candidates() -> list[int]:
    base = 8765
    try:
        base = int(os.environ.get("MCP_EXTENSION_PORT") or 8765)
    except Exception:
        base = 8765

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
        span = int(os.environ.get("MCP_EXTENSION_PORT_SPAN") or 50)
    except Exception:
        span = 50
    span = max(0, min(span, 250))
    for p in range(base, base + span + 1):
        _add(p)
    return ports


def _probe_one(host: str, port: int, *, timeout: float) -> GatewayDiscovery | None:
    url = f"http://{host}:{int(port)}{EXTENSION_GATEWAY_WELL_KNOWN_PATH}"
    req = urllib.request.Request(url, method="GET", headers={"Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(req, timeout=max(0.05, float(timeout))) as resp:  # noqa: S310
            raw = resp.read()
    except Exception:
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("type") != "browserMcpGateway":
        return None

    started = 0
    try:
        started = int(data.get("serverStartedAtMs") or 0)
    except Exception:
        started = 0

    gw_port = port
    try:
        gw_port = int(data.get("gatewayPort") or port)
    except Exception:
        gw_port = port

    ext_connected = bool(data.get("extensionConnected"))
    peer_count = 0
    try:
        peer_count = int(data.get("peerCount") or 0)
    except Exception:
        peer_count = 0

    pid = 0
    try:
        pid = int(data.get("pid") or 0)
    except Exception:
        pid = 0

    supports_peers = bool(data.get("supportsPeers"))

    return GatewayDiscovery(
        host=str(host),
        port=int(gw_port),
        server_started_at_ms=max(0, started),
        extension_connected=bool(ext_connected),
        peer_count=max(0, peer_count),
        supports_peers=bool(supports_peers),
        protocol_version=str(data.get("protocolVersion") or ""),
        server_version=str(data.get("serverVersion") or ""),
        pid=max(0, pid),
    )


def _probe_one_ws(host: str, port: int, *, timeout: float) -> GatewayDiscovery | None:
    try:
        from websockets.sync.client import connect  # type: ignore[import-not-found]
    except Exception:
        return None

    url = f"ws://{host}:{int(port)}"
    peer_id = f"probe-{int(time.time() * 1000)}-{os.getpid()}"
    timeout_s = max(0.05, float(timeout))

    def _recv_json(ws):  # type: ignore[no-untyped-def]
        try:
            raw = ws.recv(timeout=timeout_s)
        except Exception:
            return None
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "ignore")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    try:
        with connect(
            url,
            open_timeout=timeout_s,
            close_timeout=timeout_s,
            ping_interval=None,
            ping_timeout=None,
        ) as ws:
            hello = {
                "type": "peerHello",
                "peerId": peer_id,
                "pid": int(os.getpid()),
                "protocolVersion": EXTENSION_BRIDGE_PROTOCOL_VERSION,
            }
            ws.send(json.dumps(hello, separators=(",", ":")))
            ack = _recv_json(ws)
            if not isinstance(ack, dict) or ack.get("type") != "peerHelloAck":
                return None

            started = 0
            try:
                started = int(ack.get("serverStartedAtMs") or 0)
            except Exception:
                started = 0

            gw_port = port
            try:
                gw_port = int(ack.get("gatewayPort") or port)
            except Exception:
                gw_port = port

            # Request gateway status to determine extension connectivity.
            req_id = 1
            ws.send(
                json.dumps(
                    {"type": "rpc", "id": req_id, "method": "gateway.status", "timeoutMs": int(timeout_s * 1000)},
                    separators=(",", ":"),
                )
            )

            status = None
            for _ in range(3):
                msg = _recv_json(ws)
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") != "rpcResult":
                    continue
                try:
                    if int(msg.get("id") or 0) != req_id:
                        continue
                except Exception:
                    continue
                if msg.get("ok") is True and isinstance(msg.get("result"), dict):
                    status = msg.get("result")
                break

            ext_connected = bool(status.get("connected")) if isinstance(status, dict) else False
            started_at = started
            if isinstance(status, dict):
                try:
                    started_at = int(status.get("serverStartedAtMs") or started)
                except Exception:
                    started_at = started

            return GatewayDiscovery(
                host=str(host),
                port=int(gw_port),
                server_started_at_ms=max(0, started_at),
                extension_connected=bool(ext_connected),
                peer_count=0,
                supports_peers=True,
                protocol_version=str(ack.get("protocolVersion") or ""),
                server_version="",
                pid=0,
            )
    except Exception:
        return None


def discover_best_gateway(*, timeout: float = 0.25, require_peers: bool = False) -> GatewayDiscovery | None:
    host = (os.environ.get("MCP_EXTENSION_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    ports = _port_candidates()
    if not ports:
        return None

    # Parallel probes keep startup fast even when most ports are closed.
    max_workers = min(8, max(1, len(ports)))
    results: list[GatewayDiscovery] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_probe_one, host, p, timeout=timeout) for p in ports]
        for f in futs:
            try:
                r = f.result(timeout=max(0.05, float(timeout) + 0.25))
            except Exception:
                r = None
            if isinstance(r, GatewayDiscovery):
                results.append(r)

    if not results:
        # HTTP discovery can fail because WS servers don't handle plain GET requests.
        # Fall back to a short WS probe on a small subset of ports.
        ws_ports = ports[: min(6, len(ports))]
        if ws_ports:
            max_ws_workers = min(4, max(1, len(ws_ports)))
            with ThreadPoolExecutor(max_workers=max_ws_workers) as ex:
                futs = [ex.submit(_probe_one_ws, host, p, timeout=timeout) for p in ws_ports]
                for f in futs:
                    try:
                        r = f.result(timeout=max(0.05, float(timeout) + 0.4))
                    except Exception:
                        r = None
                    if isinstance(r, GatewayDiscovery):
                        results.append(r)

    if not results:
        return None

    if require_peers:
        results = [r for r in results if r.supports_peers]
        if not results:
            return None

    # Prefer a gateway that is already extension-connected, otherwise fall back to newest.
    results.sort(
        key=lambda r: (
            1 if r.extension_connected else 0,
            int(r.server_started_at_ms or 0),
        ),
        reverse=True,
    )
    return results[0]


def is_gateway_healthy(discovery: GatewayDiscovery | None) -> bool:
    if discovery is None:
        return False
    return bool(discovery.host and discovery.port > 0)
