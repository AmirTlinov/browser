from __future__ import annotations

import contextlib
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .extension_gateway import EXTENSION_BRIDGE_PROTOCOL_VERSION
from .native_broker_paths import broker_info_path, broker_socket_path, runtime_dir, sanitize_broker_id


@dataclass(frozen=True, slots=True)
class BrokerDiscovery:
    broker_id: str
    socket_path: Path
    broker_started_at_ms: int
    broker_pid: int | None
    peer_count: int


def _probe_socket(path: Path, *, timeout: float) -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except Exception:
        return False
    try:
        s.settimeout(max(0.05, float(timeout)))
        s.connect(str(path))
        return True
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            s.close()


def _load_info_file(p: Path) -> dict[str, Any] | None:
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def discover_best_broker(*, timeout: float = 0.15) -> BrokerDiscovery | None:
    """Discover the best live native broker (portless extension mode).

    Selection policy:
    - If MCP_NATIVE_BROKER_SOCKET is set, use it.
    - If MCP_NATIVE_BROKER_ID is set, use that broker id.
    - Otherwise, pick the newest broker info file under the runtime dir that has a
      connectable socket.
    """
    raw_socket = os.environ.get("MCP_NATIVE_BROKER_SOCKET")
    if isinstance(raw_socket, str) and raw_socket.strip():
        sp = Path(raw_socket.strip()).expanduser()
        if sp.exists() and _probe_socket(sp, timeout=timeout):
            return BrokerDiscovery(
                broker_id="explicit",
                socket_path=sp,
                broker_started_at_ms=0,
                broker_pid=None,
                peer_count=0,
            )
        return None

    raw_id = os.environ.get("MCP_NATIVE_BROKER_ID")
    if isinstance(raw_id, str) and raw_id.strip():
        bid = sanitize_broker_id(raw_id.strip())
        sp = broker_socket_path(bid)
        ip = broker_info_path(bid)
        info = _load_info_file(ip) or {}
        started_at = (
            int(info.get("brokerStartedAtMs") or 0) if str(info.get("brokerStartedAtMs") or "").isdigit() else 0
        )
        pid = int(info.get("brokerPid") or 0) if str(info.get("brokerPid") or "").isdigit() else None
        peer_count = int(info.get("peerCount") or 0) if str(info.get("peerCount") or "").isdigit() else 0
        if sp.exists() and _probe_socket(sp, timeout=timeout):
            return BrokerDiscovery(
                broker_id=bid,
                socket_path=sp,
                broker_started_at_ms=started_at,
                broker_pid=pid,
                peer_count=peer_count,
            )
        return None

    best: BrokerDiscovery | None = None
    for p in sorted(runtime_dir().glob("broker-*.json")):
        info = _load_info_file(p)
        if not isinstance(info, dict):
            continue
        if info.get("type") != "browserMcpNativeBroker":
            continue
        if (
            str(info.get("protocolVersion") or "")
            and str(info.get("protocolVersion") or "") != EXTENSION_BRIDGE_PROTOCOL_VERSION
        ):
            # Mismatch: skip.
            continue
        raw_sp = info.get("socketPath")
        if not isinstance(raw_sp, str) or not raw_sp.strip():
            continue
        sp = Path(raw_sp.strip())
        if not sp.exists():
            continue
        started_at = 0
        try:
            started_at = int(info.get("brokerStartedAtMs") or 0)
        except Exception:
            started_at = 0
        pid = None
        try:
            pid = int(info.get("brokerPid") or 0)
        except Exception:
            pid = None
        peer_count = 0
        try:
            peer_count = int(info.get("peerCount") or 0)
        except Exception:
            peer_count = 0

        if not _probe_socket(sp, timeout=timeout):
            continue

        broker_id = str(info.get("brokerId") or "").strip() or "unknown"
        cand = BrokerDiscovery(
            broker_id=broker_id,
            socket_path=sp,
            broker_started_at_ms=started_at,
            broker_pid=pid,
            peer_count=peer_count,
        )
        if best is None or cand.broker_started_at_ms >= best.broker_started_at_ms:
            best = cand
    return best
