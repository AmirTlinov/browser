from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from .extension_health import collect_extension_health
from .native_host_installer import install_native_host

_LOGGER = logging.getLogger("mcp.browser.extension_auto_heal")


class _Gateway(Protocol):
    def is_connected(self) -> bool: ...

    def status(self) -> dict[str, Any]: ...


def _bool_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no"}


def _float_env(name: str, *, default: float, lo: float, hi: float) -> float:
    try:
        val = float(os.environ.get(name) or default)
    except Exception:
        val = default
    return max(lo, min(val, hi))


@dataclass(frozen=True, slots=True)
class AutoHealConfig:
    enabled: bool
    grace_s: float
    interval_s: float
    max_attempts: int


def _auto_heal_config_from_env() -> AutoHealConfig:
    enabled = _bool_env("MCP_EXTENSION_AUTO_HEAL", default=True)
    # Back-compat: the older one-shot watcher used MCP_EXTENSION_HEALTH_WATCH.
    if not _bool_env("MCP_EXTENSION_HEALTH_WATCH", default=True):
        enabled = False
    grace_s = _float_env("MCP_EXTENSION_HEALTH_GRACE", default=8.0, lo=0.5, hi=60.0)
    interval_s = _float_env("MCP_EXTENSION_AUTO_HEAL_INTERVAL", default=30.0, lo=2.0, hi=300.0)
    max_attempts = int(_float_env("MCP_EXTENSION_AUTO_HEAL_MAX_ATTEMPTS", default=3, lo=0, hi=20))
    return AutoHealConfig(enabled=enabled, grace_s=grace_s, interval_s=interval_s, max_attempts=max_attempts)


class ExtensionAutoHealer:
    """Best-effort self-heal for extension mode (portless Native Messaging).

    Goal: keep the system "just works" without user debugging when the native host drifts:
    - missing manifest
    - group-writable manifest (Chrome rejects it)
    - missing allowed_origins
    - missing wrapper

    Constraints:
    - If the extension is not installed/enabled, we can't fix that automatically.
    - In multi-client mode, only the leader should perform file-writes (avoid thundering herd).
    """

    def __init__(
        self,
        gateway: _Gateway,
        *,
        on_log: Callable[[str], None] | None = None,
        config: AutoHealConfig | None = None,
    ) -> None:
        self._gw = gateway
        self._on_log = on_log
        self._cfg = config or _auto_heal_config_from_env()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._last_status: str | None = None
        self._attempts = 0

    @staticmethod
    def should_attempt_install(*, status: str | None) -> bool:
        return str(status or "") in {"native_host_missing", "native_host_misconfigured"}

    def start(self) -> bool:
        if not self._cfg.enabled:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        t = threading.Thread(target=self._run, name="mcp-extension-auto-heal", daemon=True)
        self._thread = t
        t.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _is_leader(self) -> bool:
        try:
            st = self._gw.status()
        except Exception:
            return False
        role = str(st.get("role") or "").strip().lower()
        if role:
            return role == "leader"
        # Conservative default: avoid writes when we can't prove leadership.
        return False

    def _log(self, message: str) -> None:
        _LOGGER.info("%s", message)
        if self._on_log is not None:
            with suppress(Exception):
                self._on_log(message)

    def _warn(self, message: str) -> None:
        _LOGGER.warning("%s", message)
        if self._on_log is not None:
            with suppress(Exception):
                self._on_log(message)

    def _run(self) -> None:
        time.sleep(self._cfg.grace_s)

        while not self._stop.is_set():
            try:
                if self._gw.is_connected():
                    self._attempts = 0
                    self._last_status = "connected"
                    time.sleep(min(self._cfg.interval_s, 15.0))
                    continue
            except Exception:
                time.sleep(self._cfg.interval_s)
                continue

            if not self._is_leader():
                # Let the leader handle installs; peers just wait.
                time.sleep(min(self._cfg.interval_s, 10.0))
                continue

            health = {}
            try:
                health = collect_extension_health(include_profiles=False)
            except Exception:
                health = {}

            summary = health.get("summary") if isinstance(health, dict) else None
            status = summary.get("status") if isinstance(summary, dict) else None
            status_str = str(status or "unknown")

            if status_str != (self._last_status or ""):
                reason = summary.get("reason") if isinstance(summary, dict) else ""
                hint = summary.get("hint") if isinstance(summary, dict) else ""
                self._log(f"extension_auto_heal status={status_str} reason={reason} hint={hint}")
                self._last_status = status_str

            if self._cfg.max_attempts and self._attempts >= self._cfg.max_attempts:
                time.sleep(self._cfg.interval_s)
                continue

            if self.should_attempt_install(status=status_str):
                self._attempts += 1
                report = None
                try:
                    report = install_native_host()
                except Exception as exc:  # noqa: BLE001
                    self._warn(f"extension_auto_heal install_failed error={exc}")
                    report = None

                if report and report.ok:
                    self._log(f"extension_auto_heal install_ok wrote={len(report.wrote)}")
                else:
                    errs = report.errors if report else []
                    self._warn(f"extension_auto_heal install_failed errors={errs}")

                # Give the extension time to retry connectNative.
                time.sleep(2.0)
                continue

            time.sleep(self._cfg.interval_s)


__all__ = ["AutoHealConfig", "ExtensionAutoHealer"]
