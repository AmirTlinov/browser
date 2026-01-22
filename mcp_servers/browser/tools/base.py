"""
Base utilities for browser automation tools.

Provides:
- SmartToolError: Structured errors for AI agents
- PageContext: Cached page state
- Session management with context manager
- URL validation functions
- Retry decorator with exponential backoff
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from ..config import BrowserConfig
from ..http_client import HttpClientError
from ..session import BrowserSession, session_manager


# URL Validation
def ensure_allowed(url: str, config: BrowserConfig) -> None:
    """Strict allowlist check for HTTP(S) fetches."""
    try:
        policy = session_manager.get_policy()
    except Exception:
        policy = {"mode": "permissive"}

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HttpClientError("Only http/https are supported")

    # Safety-as-mode: in strict policy, require an explicit allowlist (deny-by-default).
    if policy.get("mode") == "strict" and not config.allow_hosts:
        raise HttpClientError("Strict policy requires explicit MCP_ALLOW_HOSTS allowlist (no default allow-all)")

    if not config.is_host_allowed(parsed.hostname or ""):
        raise HttpClientError(f"Host {parsed.hostname} is not in allowlist")


def ensure_allowed_navigation(url: str, config: BrowserConfig) -> None:
    """Relaxed check for browser navigation - allows about:, data:, file: schemes."""
    try:
        policy = session_manager.get_policy()
    except Exception:
        policy = {"mode": "permissive"}

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in ("about", "data", "blob"):
        return
    if parsed.scheme == "file":
        if policy.get("mode") == "strict":
            raise HttpClientError("Strict policy forbids file:// navigation")
        if config.allow_hosts and "*" not in config.allow_hosts:
            raise HttpClientError("file:// scheme requires permissive allowlist (set MCP_ALLOW_HOSTS=*)")
        return
    if parsed.scheme not in ("http", "https"):
        raise HttpClientError(f"Unsupported scheme: {parsed.scheme} (allowed: http, https, about, data, blob, file)")

    if policy.get("mode") == "strict" and not config.allow_hosts:
        raise HttpClientError("Strict policy requires explicit MCP_ALLOW_HOSTS allowlist (no default allow-all)")

    if not config.is_host_allowed(parsed.hostname or ""):
        raise HttpClientError(f"Host {parsed.hostname} is not in allowlist")


# Error Handling
@dataclass
class SmartToolError(Exception):
    """Structured error with context for AI agents."""

    tool: str
    action: str
    reason: str
    suggestion: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.tool}] {self.action} failed: {self.reason}. Suggestion: {self.suggestion}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": True,
            "tool": self.tool,
            "action": self.action,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "details": self.details,
        }


def with_retry(max_attempts: int = 3, delay: float = 0.3, backoff: float = 1.5) -> Callable:
    """Decorator for automatic retry with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            current_delay = delay
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (HttpClientError, SmartToolError) as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
            if last_error:
                raise last_error
            raise RuntimeError("Retry exhausted without error")

        return wrapper

    return decorator


# Session Management
@dataclass
class PageContext:
    """Cached context about the current page for efficient multi-step operations."""

    url: str = ""
    title: str = ""
    forms: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    text_content: str = ""
    timestamp: float = 0.0

    def is_stale(self, max_age: float = 5.0) -> bool:
        return time.time() - self.timestamp > max_age


def _create_session(
    config: BrowserConfig,
    timeout: float = 5.0,
    *,
    ensure_diagnostics: bool = True,
    ensure_telemetry: bool = True,
    enable_page: bool = True,
) -> tuple[BrowserSession, dict[str, str], bool]:
    """Create browser session - internal, use get_session context manager instead.

    Returns:
        (session, target, should_close)
    """
    sess: BrowserSession | None = None
    should_close = False
    try:
        shared = session_manager.get_active_shared_session()
        if shared is not None:
            sess, target = shared
            # Best-effort: ensure domains/instrumentation (cache makes this cheap).
            # Some tools (e.g., dialog) must avoid Page.enable/Runtime.evaluate here:
            # alert/prompt can block the JS thread and some CDP commands may time out.
            if enable_page:
                with suppress(Exception):
                    sess.enable_page()
            if ensure_telemetry:
                with suppress(Exception):
                    session_manager.ensure_telemetry(sess)
            if ensure_diagnostics:
                with suppress(Exception):
                    session_manager.ensure_diagnostics(sess)
            return sess, target, False

        sess = session_manager.get_session(config, timeout)
        should_close = True
        if enable_page:
            with suppress(Exception):
                sess.enable_page()
        if ensure_telemetry:
            with suppress(Exception):
                session_manager.ensure_telemetry(sess)
        if ensure_diagnostics:
            # Best-effort: Tier-1 injection must never prevent tool execution.
            # On hardened pages or during dialogs, Runtime.evaluate may be blocked.
            with suppress(Exception):
                session_manager.ensure_diagnostics(sess)
        target = {"id": sess.tab_id, "webSocketDebuggerUrl": sess.conn.ws_url, "url": sess.tab_url}
        return sess, target, True
    except Exception as e:
        # Critical: never leak a session WebSocket if initialization fails (timeouts are common under dialogs).
        if should_close and sess is not None:
            with suppress(Exception):
                sess.close()
        raise SmartToolError(
            tool="session",
            action="connect",
            reason=str(e),
            suggestion="Ensure Chrome is running with --remote-debugging-port=9222",
        ) from e


@contextmanager
def get_session(
    config: BrowserConfig,
    timeout: float = 5.0,
    *,
    ensure_diagnostics: bool = True,
    ensure_telemetry: bool = True,
    enable_page: bool = True,
) -> Generator[tuple[BrowserSession, dict[str, str]], None, None]:
    """Context manager for browser session with automatic cleanup.

    Usage:
        with get_session(config) as (session, target):
            result = session.eval_js("document.title")
    """
    session, target, should_close = _create_session(
        config,
        timeout,
        ensure_diagnostics=ensure_diagnostics,
        ensure_telemetry=ensure_telemetry,
        enable_page=enable_page,
    )
    try:
        yield session, target
    finally:
        if should_close:
            session.close()


def get_session_tab_id() -> str | None:
    """Get the current session's isolated tab ID."""
    return session_manager.tab_id
