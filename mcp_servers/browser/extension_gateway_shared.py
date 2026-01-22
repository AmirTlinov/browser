from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .extension_gateway import ExtensionGateway
from .extension_gateway_peer import ExtensionGatewayPeer
from .extension_leader_lock import default_leader_lock


class SharedExtensionGateway:
    """Multi-process extension gateway manager.

    Goal: allow many CLI sessions to run concurrently in MCP_BROWSER_MODE=extension.

    - Exactly one process becomes the leader (binds local WS gateway + accepts the Chrome extension).
    - Other processes connect as peers and proxy all RPC/CDP through the leader.
    - Best-effort promotion: if the leader disappears, a peer can become the new leader.
    """

    def __init__(
        self,
        *,
        on_cdp_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_cdp_event = on_cdp_event
        self._lock = threading.Lock()
        self._leader_lock = default_leader_lock()

        self._leader: ExtensionGateway | None = None
        self._peer: ExtensionGatewayPeer | None = None

        # Public hint for SessionManager: if True, avoid adopting the user's active tab.
        self.is_proxy = False

    def _ensure_backend(self) -> None:
        with self._lock:
            if self._leader_lock.try_acquire():
                # Promote to leader.
                if self._peer is not None:
                    self._peer.stop(timeout=0.5)
                    self._peer = None
                if self._leader is None:
                    self._leader = ExtensionGateway(on_cdp_event=self._on_cdp_event)
                self.is_proxy = False
                self._leader.start(wait_timeout=0.2, require_listening=False)
                return

            # Fall back to peer mode.
            if self._leader is not None:
                # Another process is leader. Release our lock state and behave as peer.
                self._leader.stop(timeout=0.5)
                self._leader = None
            if self._peer is None:
                self._peer = ExtensionGatewayPeer(on_cdp_event=self._on_cdp_event)
            self.is_proxy = True
            self._peer.start(wait_timeout=0.2)

    def _backend(self) -> Any:
        self._ensure_backend()
        return self._peer if self.is_proxy else self._leader

    # ─────────────────────────────────────────────────────────────────────────
    # Public API (ExtensionGateway-like)
    # ─────────────────────────────────────────────────────────────────────────

    def start(self, *, wait_timeout: float = 0.5, require_listening: bool = False) -> None:
        _ = (wait_timeout, require_listening)
        self._ensure_backend()

    def stop(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            if self._peer is not None:
                self._peer.stop(timeout=timeout)
                self._peer = None
            if self._leader is not None:
                self._leader.stop(timeout=timeout)
                self._leader = None
            self._leader_lock.release()
            self.is_proxy = False

    def status(self) -> dict[str, Any]:
        gw = self._backend()
        if gw is None:
            return {"listening": False, "connected": False}
        st = gw.status() if hasattr(gw, "status") else {}
        if not isinstance(st, dict):
            st = {}
        st["role"] = "peer" if self.is_proxy else "leader"
        return st

    def is_connected(self) -> bool:
        gw = self._backend()
        return bool(gw is not None and gw.is_connected())

    def wait_for_connection(self, *, timeout: float = 5.0) -> bool:
        gw = self._backend()
        if gw is None:
            return False
        ok = bool(gw.wait_for_connection(timeout=timeout))
        if ok:
            return True

        # Promotion attempt: if we're a peer and the leader lock is now free, become leader.
        if self.is_proxy:
            with self._lock:
                if self._leader_lock.try_acquire():
                    if self._peer is not None:
                        self._peer.stop(timeout=0.5)
                        self._peer = None
                    if self._leader is None:
                        self._leader = ExtensionGateway(on_cdp_event=self._on_cdp_event)
                    self.is_proxy = False
                    self._leader.start(wait_timeout=0.2, require_listening=False)
            gw2 = self._leader
            if gw2 is not None:
                return bool(gw2.wait_for_connection(timeout=timeout))
        return False

    def rpc_call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        gw = self._backend()
        return gw.rpc_call(method, params, timeout=timeout)

    def cdp_send(
        self,
        tab_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        gw = self._backend()
        return gw.cdp_send(tab_id, method, params, timeout=timeout)

    def cdp_send_many(
        self,
        tab_id: str,
        commands: list[dict[str, Any]],
        *,
        timeout: float = 10.0,
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        gw = self._backend()
        return gw.cdp_send_many(tab_id, commands, timeout=timeout, stop_on_error=stop_on_error)

    def pop_event(self, tab_id: str, event_name: str) -> dict[str, Any] | None:
        gw = self._backend()
        return gw.pop_event(tab_id, event_name)

    def wait_for_event(self, tab_id: str, event_name: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
        gw = self._backend()
        return gw.wait_for_event(tab_id, event_name, timeout=timeout)
