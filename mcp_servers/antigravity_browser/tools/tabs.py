"""
Tab management tools for browser automation.

Provides:
- list_tabs: List all open browser tabs
- switch_tab: Switch to a different browser tab
- new_tab: Open a new browser tab
- close_tab: Close a browser tab

These tools operate on the session level, managing multiple tabs
without requiring the get_session context manager.
"""
from __future__ import annotations

from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError


def list_tabs(config: BrowserConfig) -> dict[str, Any]:
    """List all open browser tabs.

    Args:
        config: Browser configuration

    Returns:
        Dict containing:
        - tabs: List of tab objects with id, url, title, and current flag
        - count: Total number of tabs
        - sessionTabId: ID of the current session's tab

    The current session's tab is marked with 'current': True.
    Use switch_tab() to change the active tab.
    """
    try:
        tabs = session_manager.list_tabs(config)
        return {
            "tabs": tabs,
            "count": len(tabs),
            "sessionTabId": session_manager.tab_id,
        }
    except Exception as e:
        raise SmartToolError(
            tool="list_tabs",
            action="list",
            reason=str(e),
            suggestion="Ensure Chrome is running with remote debugging enabled",
        ) from e


def _find_tab_by_url_pattern(config: BrowserConfig, url_pattern: str) -> str | None:
    """Find tab ID by URL pattern matching.

    Args:
        config: Browser configuration
        url_pattern: Substring to match against tab URLs (case-insensitive)

    Returns:
        Tab ID if found, None otherwise
    """
    tabs = session_manager.list_tabs(config)
    pattern_lower = url_pattern.lower()
    for tab in tabs:
        if pattern_lower in tab.get("url", "").lower():
            tab_id = tab.get("id")
            return str(tab_id) if tab_id is not None else None
    return None


def _get_tab_info(config: BrowserConfig, tab_id: str) -> dict[str, Any]:
    """Get information about a specific tab.

    Args:
        config: Browser configuration
        tab_id: Target tab ID

    Returns:
        Dict with tab information (id, url, title)
    """
    tabs = session_manager.list_tabs(config)
    tab_info: dict[str, Any] = next((t for t in tabs if t.get("id") == tab_id), {})
    return {
        "id": tab_id,
        "url": tab_info.get("url", ""),
        "title": tab_info.get("title", ""),
    }


def switch_tab(
    config: BrowserConfig,
    tab_id: str | None = None,
    url_pattern: str | None = None,
) -> dict[str, Any]:
    """Switch to a different browser tab.

    Args:
        config: Browser configuration
        tab_id: Target ID from list_tabs()
        url_pattern: Substring to match against tab URLs (alternative to tab_id)

    Returns:
        Dict with success status and tab information

    Switches this MCP session to use the specified tab for subsequent operations.
    Either tab_id or url_pattern must be provided.
    """
    if not tab_id and not url_pattern:
        raise SmartToolError(
            tool="switch_tab",
            action="validate",
            reason="Either tab_id or url_pattern must be provided",
            suggestion="Provide tab_id from list_tabs() or url_pattern to match",
        )

    try:
        target_id = tab_id or _find_tab_by_url_pattern(config, url_pattern or "")

        if not target_id:
            pattern_desc = f"id={tab_id}" if tab_id else f"url={url_pattern}"
            raise SmartToolError(
                tool="switch_tab",
                action="find_tab",
                reason=f"No tab found matching {pattern_desc}",
                suggestion="Use list_tabs() to see available tabs",
            )

        success = session_manager.switch_tab(config, target_id)
        if not success:
            raise SmartToolError(
                tool="switch_tab",
                action="switch",
                reason="Tab not found or unavailable",
                suggestion="Use list_tabs() to verify tab exists",
            )

        tab_info = _get_tab_info(config, target_id)
        return {"result": {"success": True, "tab": tab_info}}

    except SmartToolError:
        raise
    except Exception as e:
        raise SmartToolError(
            tool="switch_tab",
            action="switch",
            reason=str(e),
            suggestion="Verify tab_id is valid from list_tabs()",
        ) from e


def new_tab(config: BrowserConfig, url: str = "about:blank") -> dict[str, Any]:
    """Open a new browser tab and switch this session to it.

    Args:
        config: Browser configuration
        url: URL to open in the new tab (default: "about:blank")

    Returns:
        Dict containing:
        - success: True if tab was created
        - newTabId: ID of the newly created tab
        - url: URL opened in the new tab
        - sessionTabId: Current session's tab ID (same as newTabId)

    The new tab becomes the active tab for this MCP session.
    """
    try:
        new_tab_id = session_manager.new_tab(config, url)
        return {
            "result": {
                "success": True,
                "newTabId": new_tab_id,
                "url": url,
                "sessionTabId": session_manager.tab_id,
            }
        }
    except Exception as e:
        raise SmartToolError(
            tool="new_tab",
            action="create",
            reason=str(e),
            suggestion="Ensure Chrome allows new tabs",
        ) from e


def close_tab(
    config: BrowserConfig,
    tab_id: str | None = None,
) -> dict[str, Any]:
    """Close a browser tab.

    Args:
        config: Browser configuration
        tab_id: Target ID to close (closes current session tab if None)

    Returns:
        Dict with success status and closed tab ID

    Warning:
        Closing the current session's tab may require switching to another tab
        or creating a new one for continued operations.
    """
    try:
        success = session_manager.close_tab(config, tab_id)
        return {
            "result": {
                "success": success,
                "closedTabId": tab_id or session_manager.tab_id,
            }
        }
    except Exception as e:
        raise SmartToolError(
            tool="close_tab",
            action="close",
            reason=str(e),
            suggestion="Verify tab_id is valid",
        ) from e
