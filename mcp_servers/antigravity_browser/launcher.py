from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import BrowserConfig, expand_path


@dataclass
class LaunchResult:
    command: list[str]
    started: bool
    message: str


class BrowserLauncher:
    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig.from_env()
        self.process: subprocess.Popen | None = None

    def _build_common_flags(self) -> list[str]:
        flags = [
            f"--remote-debugging-port={self.config.cdp_port}",
            f"--user-data-dir={expand_path(self.config.profile_path)}",
            "--remote-allow-origins=*",
            "--disable-fre",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=ExtensionInstallVerification,ExtensionInstallVerificationIfOffStoreOnly",
            "--enable-features=ExtensionsMenuAccessControl",
        ]

        # Add --no-sandbox for portable chromium builds (required for local vendor installation)
        if "vendor/chromium" in self.config.binary_path:
            flags.append("--no-sandbox")

        # Window visibility control
        headless = os.environ.get("MCP_HEADLESS", "0") == "1"
        if headless:
            flags.append("--headless=new")
        else:
            # Visible window mode - set initial size and position
            window_size = os.environ.get("MCP_WINDOW_SIZE", "1280,900")
            flags.append(f"--window-size={window_size}")
            # Don't start minimized in visible mode
            if "--start-minimized" not in self.config.extra_flags:
                flags.append("--start-maximized")

        return flags

    def build_launch_command(self, extra: list[str] | None = None) -> list[str]:
        flags = self._build_common_flags() + self.config.extra_flags
        if extra:
            flags.extend(extra)
        return [self.config.binary_path, *flags]

    def _port_available(self, timeout: float = 0.2) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            try:
                result = sock.connect_ex(("127.0.0.1", self.config.cdp_port))
                return result != 0
            except OSError:
                return False

    def _cdp_ready(self, timeout: float = 0.4) -> bool:
        endpoint = f"http://127.0.0.1:{self.config.cdp_port}/json/version"
        try:
            with urlopen(endpoint, timeout=timeout) as resp:
                return resp.status == 200
        except (OSError, TimeoutError, URLError):
            return False

    def ensure_running(self, timeout: float = 5.0) -> LaunchResult:
        if self._cdp_ready():
            return LaunchResult([], False, "Chrome already listening on CDP port")

        if not self._port_available():
            return LaunchResult([], False, f"Port {self.config.cdp_port} already in use")

        cmd = self.build_launch_command()
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._cdp_ready():
                return LaunchResult(cmd, True, "Chrome launched")
            time.sleep(0.1)
        return LaunchResult(cmd, False, "Chrome launch timed out")

    @staticmethod
    def find_free_port() -> int:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def dump_dom(self, url: str, timeout: float = 15.0) -> dict:
        headless = os.environ.get("MCP_HEADLESS", "1") != "0"
        dump_flags = [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={expand_path(self.config.profile_path)}",
            "--remote-allow-origins=*",
            "--dump-dom",
            url,
        ]
        if headless:
            dump_flags.insert(0, "--headless=new")
        else:
            dump_flags.extend(["--start-minimized", "--no-sandbox"])
        cmd = [self.config.binary_path, *dump_flags]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout.decode(errors="replace"),
            "stderr": proc.stderr.decode(errors="replace"),
            "command": cmd,
        }

    def cdp_version(self, timeout: float = 0.8) -> dict:
        endpoint = f"http://127.0.0.1:{self.config.cdp_port}/json/version"
        try:
            req = Request(endpoint, headers={"User-Agent": "mcp-browser"})
            with urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
                return {"status": resp.status, "version": payload}
        except URLError as exc:  # noqa: BLE001
            raise RuntimeError(f"CDP not reachable on port {self.config.cdp_port}: {exc}") from exc

    def list_targets(self) -> list[dict]:
        endpoint = f"http://127.0.0.1:{self.config.cdp_port}/json/list"
        try:
            req = Request(endpoint, headers={"User-Agent": "mcp-browser"})
            with urlopen(req, timeout=0.5) as resp:
                payload = resp.read()
                return json.loads(payload.decode())
        except URLError:
            return []
