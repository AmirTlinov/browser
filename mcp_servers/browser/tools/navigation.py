"""
Navigation tools for browser automation.

Provides:
- navigate_to: Navigate to URL
- go_back: Browser history back
- go_forward: Browser history forward
- reload_page: Reload current page
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from ..permissions import apply_permission_policy
from .base import SmartToolError, ensure_allowed_navigation, get_session


def navigate_to(config: BrowserConfig, url: str, wait_load: bool = True) -> dict[str, Any]:
    """Navigate to a URL in the session's isolated tab.

    Args:
        config: Browser configuration
        url: URL to navigate to
        wait_load: Wait for page to load (default: True)

    Returns:
        Dict with url, target ID, and session tab ID
    """
    ensure_allowed_navigation(url, config)

    with get_session(config) as (session, target):
        try:
            with suppress(Exception):
                apply_permission_policy(session, config.permission_policy, url)
            session.navigate(url, wait_load=wait_load)
            return {"url": url, "target": target["id"], "sessionTabId": session_manager.tab_id}
        except Exception as e:
            raise SmartToolError(
                tool="navigate",
                action="navigate",
                reason=str(e),
                suggestion="Check URL is valid and accessible",
            ) from e


def go_back(config: BrowserConfig) -> dict[str, Any]:
    """Navigate back in browser history."""
    with get_session(config) as (session, target):
        with suppress(Exception):  # Navigation might close connection
            session.eval_js("window.history.back(); true")

        time.sleep(0.3)

        try:
            url = session.eval_js("window.location.href")
            return {"url": url, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="go_back",
                action="navigate",
                reason=str(e),
                suggestion="Ensure there is history to go back to",
            ) from e


def go_forward(config: BrowserConfig) -> dict[str, Any]:
    """Navigate forward in browser history."""
    with get_session(config) as (session, target):
        with suppress(Exception):
            session.eval_js("window.history.forward(); true")

        time.sleep(0.3)

        try:
            url = session.eval_js("window.location.href")
            return {"url": url, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="go_forward",
                action="navigate",
                reason=str(e),
                suggestion="Ensure there is forward history",
            ) from e


def reload_page(config: BrowserConfig, ignore_cache: bool = False) -> dict[str, Any]:
    """Reload the current page."""
    with get_session(config) as (session, target):
        try:
            session.send("Page.reload", {"ignoreCache": ignore_cache})
            session.wait_load(timeout=10.0)
            url = session.eval_js("window.location.href")
            return {"url": url, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="reload",
                action="reload",
                reason=str(e),
                suggestion="Ensure page is responsive",
            ) from e
