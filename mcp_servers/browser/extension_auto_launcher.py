from __future__ import annotations

import atexit
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import BrowserConfig, expand_path
from .extension_leader_lock import auto_launch_lock

_LOGGER = logging.getLogger("mcp.browser.extension_auto_launcher")


@dataclass(frozen=True, slots=True)
class ExtensionLaunchPlan:
    command: list[str]
    binary_path: str
    profile_path: str
    extension_path: str
    log_path: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extension_path(root: Path) -> Path:
    return root / "vendor" / "browser_extension"


def _default_profile_path() -> str:
    return str(Path.home() / ".gemini" / "browser-extension-profile")


def build_extension_launch_plan() -> ExtensionLaunchPlan:
    root = _repo_root()
    extension_path = _extension_path(root)
    binary = os.environ.get("MCP_BROWSER_BINARY") or BrowserConfig.detect_binary()
    profile = os.environ.get("MCP_EXTENSION_PROFILE") or _default_profile_path()

    flags = [
        f"--user-data-dir={expand_path(profile)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-fre",
        f"--disable-extensions-except={extension_path}",
        f"--load-extension={extension_path}",
        "--disable-component-extensions-with-background-pages",
        "--enable-features=ExtensionsMenuAccessControl",
    ]

    if "vendor/chromium" in str(binary):
        flags.append("--no-sandbox")

    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    log_path = str(log_dir / f"extension_auto_launch_{ts}.log")

    return ExtensionLaunchPlan(
        command=[str(binary), *flags],
        binary_path=str(binary),
        profile_path=str(profile),
        extension_path=str(extension_path),
        log_path=log_path,
    )


class ExtensionAutoLauncher:
    def __init__(self) -> None:
        self._lock = auto_launch_lock()
        self._process: subprocess.Popen | None = None
        self._attempted = False
        self._last_error: str | None = None
        atexit.register(self.stop)

    def ensure_running(self) -> bool:
        if str(os.environ.get("MCP_EXTENSION_AUTO_LAUNCH") or "0").lower() in {"0", "false", "no"}:
            return False
        if self._process is not None and self._process.poll() is None:
            return True
        if not self._lock.try_acquire():
            return False
        if self._attempted:
            return False
        self._attempted = True

        try:
            plan = build_extension_launch_plan()
            if not Path(plan.extension_path).exists():
                self._last_error = f"extension path missing: {plan.extension_path}"
                return False
            log_fp = open(plan.log_path, "ab")  # noqa: SIM115
            self._process = subprocess.Popen(
                plan.command,
                stdout=log_fp,
                stderr=log_fp,
                cwd=str(_repo_root()),
            )
            _LOGGER.info("extension_auto_launch_ok log=%s", plan.log_path)
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            _LOGGER.warning("extension_auto_launch_failed %s", exc)
            return False

    def stop(self) -> None:
        proc = self._process
        self._process = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        self._lock.release()


__all__ = ["ExtensionAutoLauncher", "ExtensionLaunchPlan", "build_extension_launch_plan"]
