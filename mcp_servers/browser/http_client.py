from __future__ import annotations

import ssl
import urllib.parse
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .config import BrowserConfig


class HttpClientError(Exception):
    pass


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, config: BrowserConfig) -> None:
        super().__init__()
        self._config = config

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        # urllib may pass relative URLs here; normalize against the previous URL.
        absolute = urllib.parse.urljoin(req.full_url, str(newurl))
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            raise HttpClientError("Only http/https are supported (redirect)")
        if not self._config.is_host_allowed(parsed.hostname or ""):
            raise HttpClientError(f"Host {parsed.hostname} is not in allowlist (redirect)")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


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
        ctx = ssl.create_default_context()
        opener = build_opener(_SafeRedirectHandler(config), HTTPSHandler(context=ctx))
        with opener.open(req, timeout=timeout) as resp:
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
