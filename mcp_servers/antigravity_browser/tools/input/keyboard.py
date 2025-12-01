"""
Keyboard input operations for browser automation.

Provides key press and text typing operations.
"""
from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def press_key(config: BrowserConfig, key: str, modifiers: int = 0) -> dict[str, Any]:
    """Press a keyboard key with optional modifiers.

    Args:
        config: Browser configuration
        key: Key to press (e.g., "Enter", "Tab", "a", "A")
        modifiers: Modifier bitmask (1=Alt, 2=Ctrl, 4=Meta, 8=Shift)

    Returns:
        Dict with key, modifiers, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.press_key(key, modifiers)
            return {
                "key": key,
                "modifiers": modifiers,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="press_key",
                action="press",
                reason=str(e),
                suggestion="Ensure key name is valid (e.g., 'Enter', 'Tab', 'Escape')",
            ) from e


def type_text(config: BrowserConfig, text: str) -> dict[str, Any]:
    """Type text using keyboard events for currently focused element.

    Args:
        config: Browser configuration
        text: Text to type

    Returns:
        Dict with text, length, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            session.type_text(text)
            return {
                "text": text,
                "length": len(text),
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="type_text",
                action="type",
                reason=str(e),
                suggestion="Ensure an input element is focused before typing",
            ) from e
