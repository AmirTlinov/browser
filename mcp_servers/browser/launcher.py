from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import BrowserConfig, expand_path


@dataclass
class LaunchResult:
    command: list[str]
    started: bool
    message: str
    log_path: str | None = None
    log_tail: str | None = None


class BrowserLauncher:
    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig.from_env()
        self.process: subprocess.Popen | None = None

    def cdp_ready(self, timeout: float = 0.4) -> bool:
        """Return True if the CDP HTTP endpoint responds."""
        return self._cdp_ready(timeout=timeout)

    def stop(self, *, timeout: float = 2.0) -> bool:
        """Best-effort stop of the launcher-owned Chrome process."""
        proc = self.process
        if proc is None:
            return False
        try:
            if proc.poll() is not None:
                return True
        except Exception:
            pass

        with contextlib.suppress(Exception):
            proc.terminate()

        deadline = time.time() + max(0.1, float(timeout))
        while time.time() < deadline:
            try:
                if proc.poll() is not None:
                    return True
            except Exception:
                break
            time.sleep(0.05)

        # Escalate to kill.
        with contextlib.suppress(Exception):
            proc.kill()
        return True

    def restart(self, timeout: float = 5.0) -> LaunchResult:
        """Hard recovery: stop launcher-owned Chrome and relaunch."""
        if getattr(self.config, "mode", "launch") == "attach":
            return LaunchResult([], False, "Attach mode: restart is not supported (external browser)")
        if getattr(self.config, "mode", "launch") == "extension":
            return LaunchResult([], False, "Extension mode: restart is not supported (user-owned browser)")

        stopped = self.stop(timeout=2.0)

        # Wait for port to become available (avoid immediate 'port in use').
        deadline = time.time() + 2.0
        while time.time() < deadline and not self._port_available(timeout=0.2):
            time.sleep(0.05)

        result = self.ensure_running(timeout=timeout)
        # Keep a high-signal message for callers.
        if stopped and result.message:
            result.message = "Recovered: restarted Chrome. " + result.message
        elif stopped:
            result.message = "Recovered: restarted Chrome"
        return result

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
        headless = os.environ.get("MCP_HEADLESS", "1") == "1"
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
        if getattr(self.config, "mode", "launch") == "extension":
            return LaunchResult([], False, "Extension mode: no launch required (install/enable the extension)")

        def _repo_root() -> Path:
            # mcp_servers/browser/launcher.py -> repo root is parents[2]
            return Path(__file__).resolve().parents[2]

        def _make_log_path(prefix: str) -> str:
            root = _repo_root()
            log_dir = root / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time() * 1000)
            return str(log_dir / f"{prefix}_{ts}.log")

        def _tail_text(path: str, max_chars: int = 4000) -> str | None:
            try:
                p = Path(path)
                if not p.exists():
                    return None
                raw = p.read_text(encoding="utf-8", errors="replace")
                if len(raw) <= max_chars:
                    return raw
                return raw[-max_chars:]
            except Exception:
                return None

        if getattr(self.config, "mode", "launch") == "attach":
            if self._cdp_ready():
                return LaunchResult([], False, "Attached to existing Chrome on CDP port")
            if self._port_available():
                return LaunchResult(
                    [],
                    False,
                    f"Attach mode: no Chrome listening on CDP port {self.config.cdp_port} (start Chrome with --remote-debugging-port)",
                )
            return LaunchResult(
                [],
                False,
                f"Attach mode: port {self.config.cdp_port} is in use but CDP is not reachable (ensure Chrome was started with --remote-debugging-port)",
            )

        if self._cdp_ready():
            return LaunchResult([], False, "Chrome already listening on CDP port")

        headless = os.environ.get("MCP_HEADLESS", "1") == "1"

        if not self._port_available():
            # Port is in use but the CDP endpoint did not respond. This is commonly a hung
            # or external Chrome on the default port. Prefer launching an owned Chrome on
            # a free port so the MCP server can recover autonomously (Playwright-like).
            if os.environ.get("MCP_AUTO_PORT_FALLBACK", "0") != "0":
                old_port = int(self.config.cdp_port)
                old_profile = str(self.config.profile_path)
                new_port = self.find_free_port()

                # Switch to a fresh port + (best-effort) avoid profile lock conflicts.
                self.config.cdp_port = int(new_port)
                self.config.profile_path = f"{old_profile}-owned-{new_port}"

                cmd = self.build_launch_command()
                log_path: str | None = None
                try:
                    popen_kwargs: dict[str, object] = {}
                    if not headless:
                        log_path = _make_log_path("chrome_owned_launch")
                        log_fh = open(log_path, "ab", buffering=0)  # noqa: SIM115
                        popen_kwargs.update(
                            {
                                "stdout": log_fh,
                                "stderr": log_fh,
                                "stdin": subprocess.DEVNULL,
                                "start_new_session": True,
                            }
                        )
                    else:
                        popen_kwargs.update({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})

                    try:
                        self.process = subprocess.Popen(cmd, **popen_kwargs)  # type: ignore[arg-type]
                    finally:
                        try:
                            if "log_fh" in locals():
                                log_fh.close()  # type: ignore[name-defined]
                        except Exception:
                            pass
                except OSError as exc:
                    return LaunchResult(cmd, False, str(exc), log_path=log_path, log_tail=_tail_text(log_path or ""))

                deadline = time.time() + timeout
                while time.time() < deadline:
                    if self._cdp_ready():
                        return LaunchResult(
                            cmd,
                            True,
                            f"Port {old_port} was busy/unresponsive; launched owned Chrome on port {new_port}",
                            log_path=log_path,
                        )
                    time.sleep(0.1)
                return LaunchResult(
                    cmd,
                    False,
                    f"Port {old_port} was busy/unresponsive; attempted owned Chrome on port {new_port} but launch timed out",
                    log_path=log_path,
                    log_tail=_tail_text(log_path or ""),
                )

            return LaunchResult([], False, f"Port {self.config.cdp_port} already in use")

        cmd = self.build_launch_command()
        log_path: str | None = None
        try:
            popen_kwargs2: dict[str, object] = {}
            if not headless:
                log_path = _make_log_path("chrome_launch")
                log_fh2 = open(log_path, "ab", buffering=0)  # noqa: SIM115
                popen_kwargs2.update(
                    {
                        "stdout": log_fh2,
                        "stderr": log_fh2,
                        "stdin": subprocess.DEVNULL,
                        "start_new_session": True,
                    }
                )
            else:
                popen_kwargs2.update({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})

            try:
                self.process = subprocess.Popen(cmd, **popen_kwargs2)  # type: ignore[arg-type]
            finally:
                try:
                    if "log_fh2" in locals():
                        log_fh2.close()  # type: ignore[name-defined]
                except Exception:
                    pass
        except OSError as exc:
            return LaunchResult(cmd, False, str(exc), log_path=log_path, log_tail=_tail_text(log_path or ""))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._cdp_ready():
                return LaunchResult(cmd, True, "Chrome launched", log_path=log_path)
            time.sleep(0.1)
        return LaunchResult(
            cmd, False, "Chrome launch timed out", log_path=log_path, log_tail=_tail_text(log_path or "")
        )

    @staticmethod
    def find_free_port() -> int:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def dump_dom(self, url: str, timeout: float = 15.0) -> dict:
        headless = os.environ.get("MCP_HEADLESS", "1") != "0"
        with contextlib.suppress(Exception):
            Path(expand_path(self.config.profile_path)).mkdir(parents=True, exist_ok=True)
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
        if getattr(self.config, "mode", "launch") == "extension":
            raise RuntimeError("Extension mode: CDP /json/version is not used (check browser(action='status'))")
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
