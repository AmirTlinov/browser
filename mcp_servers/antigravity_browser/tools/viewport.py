"""
Viewport and window management tools.

Provides:
- resize_viewport: Resize browser viewport (content area)
- resize_window: Resize browser window
"""
from __future__ import annotations

from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session


def resize_viewport(config: BrowserConfig, width: int, height: int) -> dict[str, Any]:
    """Resize the browser viewport (content area).

    Args:
        config: Browser configuration
        width: Viewport width in pixels
        height: Viewport height in pixels

    Returns:
        Dict with width, height, and target ID
    """
    with get_session(config) as (session, target):
        try:
            session.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": 1.0, "mobile": False},
            )
            return {"width": width, "height": height, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="resize_viewport",
                action="resize",
                reason=str(e),
                suggestion="Check width and height are valid positive integers",
            ) from e


def resize_window(config: BrowserConfig, width: int, height: int) -> dict[str, Any]:
    """Resize the browser window (not just viewport).

    Args:
        config: Browser configuration
        width: Window width in pixels
        height: Window height in pixels

    Returns:
        Dict with width, height, windowId, and target ID
    """
    with get_session(config) as (session, target):
        try:
            window_info = session.send("Browser.getWindowForTarget", {"targetId": target["id"]})
            window_id = window_info.get("windowId")
            if window_id:
                session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"width": width, "height": height}})
            return {"width": width, "height": height, "windowId": window_id, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="resize_window",
                action="resize",
                reason=str(e),
                suggestion="Check browser supports window resizing",
            ) from e
