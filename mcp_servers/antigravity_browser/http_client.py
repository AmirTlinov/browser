from __future__ import annotations

import ssl
import urllib.parse
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import BrowserConfig


class HttpClientError(Exception):
    pass


def _build_request(url: str, timeout: float) -> tuple[Request, float]:
    req = Request(url, headers={"User-Agent": "mcp-browser/1.0"})
    return req, timeout


def http_get(url: str, config: BrowserConfig) -> dict[str, object]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HttpClientError("Only http/https are supported")
    if not config.is_host_allowed(parsed.hostname or ""):
        raise HttpClientError(f"Host {parsed.hostname} is not in allowlist")
    req, timeout = _build_request(url, config.http_timeout)
    try:
        with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            body = resp.read(config.http_max_bytes + 1)
            truncated = len(body) > config.http_max_bytes
            if truncated:
                body = body[: config.http_max_bytes]
            return {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": body.decode(errors="replace"),
                "truncated": truncated,
            }
    except (TimeoutError, URLError) as exc:
        raise HttpClientError(str(exc)) from exc

