from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_local_chromium_path() -> str:
    """Get path to locally installed Chromium in vendor directory."""
    # Resolve path relative to this file
    config_dir = Path(__file__).resolve().parent
    project_root = config_dir.parent.parent
    local_chrome = project_root / "vendor" / "chromium" / "chrome"
    return str(local_chrome)


DEFAULT_BINARY_CANDIDATES: list[str] = [
    # First priority: locally installed Chromium in project (portable, no system deps)
    _get_local_chromium_path(),
    # Prefer Chromium/ungoogled-chromium for better compatibility.
    # IMPORTANT: Avoid snap versions - they ignore --user-data-dir!
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/local/bin/chromium",
    "/opt/chromium/chromium",
    # Snap version moved to end (known issues with profiles)
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "C:\\Program Files\\Chromium\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Chromium\\Application\\chrome.exe",
    # Chrome entries kept as fallback.
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome-beta",
    "/opt/google/chrome/chrome",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    # Snap versions last resort (SingletonLock issues, profile conflicts)
    "/snap/bin/chromium",
]


def expand_path(raw: str) -> str:
    return str(Path(raw).expanduser())


@dataclass
class BrowserConfig:
    binary_path: str
    profile_path: str
    cdp_port: int = 9222
    mode: str = "launch"
    extra_flags: list[str] = field(default_factory=list)
    allow_hosts: list[str] = field(default_factory=list)
    http_timeout: float = 10.0
    http_max_bytes: int = 1_000_000

    @staticmethod
    def normalize_mode(raw: str | None) -> str:
        mode = (raw or "").strip().lower()
        if mode in {"extension", "ext"}:
            return "extension"
        if mode in {"attach", "connect", "external"}:
            return "attach"
        if mode in {"launch", "spawn", "start", ""}:
            return "launch"
        return "launch"

    @classmethod
    def detect_binary(cls) -> str:
        env_path = os.environ.get("MCP_BROWSER_BINARY")
        if env_path:
            return expand_path(env_path)
        for candidate in DEFAULT_BINARY_CANDIDATES:
            path = Path(candidate)
            # Prefer executables only. A common footgun: vendor/chromium/chrome exists
            # but lacks +x, which would make launches fail with "Permission denied".
            if path.exists() and os.access(str(path), os.X_OK):
                return str(path)
        # Last resort: rely on PATH lookup
        return "google-chrome"

    @classmethod
    def from_env(cls) -> BrowserConfig:
        mode = cls.normalize_mode(os.environ.get("MCP_BROWSER_MODE"))
        profile = expand_path(os.environ.get("MCP_BROWSER_PROFILE", "~/.gemini/browser-profile"))
        port = int(os.environ.get("MCP_BROWSER_PORT", "9222"))
        flags_raw = os.environ.get("MCP_BROWSER_FLAGS", "")
        extra_flags = [flag for flag in flags_raw.split(",") if flag.strip()]
        allow_raw = os.environ.get("MCP_ALLOW_HOSTS", "")
        allow_hosts = [host.strip().lower() for host in allow_raw.split(",") if host.strip() and host.strip() != "*"]
        timeout = float(os.environ.get("MCP_HTTP_TIMEOUT", "10"))
        max_bytes = int(os.environ.get("MCP_HTTP_MAX_BYTES", "1000000"))
        return cls(
            binary_path=cls.detect_binary(),
            profile_path=profile,
            cdp_port=port,
            mode=mode,
            extra_flags=extra_flags,
            allow_hosts=allow_hosts,
            http_timeout=timeout,
            http_max_bytes=max_bytes,
        )

    def is_host_allowed(self, host: str) -> bool:
        host = (host or "").strip().lower().rstrip(".")
        if not self.allow_hosts:
            return True
        for raw_allowed in self.allow_hosts:
            allowed = (raw_allowed or "").strip().lower().lstrip(".").rstrip(".")
            if not allowed:
                continue
            if host == allowed:
                return True
            if host.endswith("." + allowed):
                return True
        return False
