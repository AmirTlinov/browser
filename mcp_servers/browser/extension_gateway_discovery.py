from __future__ import annotations

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .extension_gateway import EXTENSION_GATEWAY_WELL_KNOWN_PATH


@dataclass(frozen=True, slots=True)
class GatewayDiscovery:
    host: str
    port: int
    server_started_at_ms: int
    extension_connected: bool
    peer_count: int
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
        span = int(os.environ.get("MCP_EXTENSION_PORT_SPAN") or 10)
    except Exception:
        span = 10
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

    return GatewayDiscovery(
        host=str(host),
        port=int(gw_port),
        server_started_at_ms=max(0, started),
        extension_connected=bool(ext_connected),
        peer_count=max(0, peer_count),
        protocol_version=str(data.get("protocolVersion") or ""),
        server_version=str(data.get("serverVersion") or ""),
        pid=max(0, pid),
    )


def discover_best_gateway(*, timeout: float = 0.25) -> GatewayDiscovery | None:
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
