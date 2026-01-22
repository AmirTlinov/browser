"""
App-level macros/adapters for complex web apps (canvas-heavy, non-DOM-driven UIs).

Why:
- Some apps (Miro/Figma/etc.) are effectively "graphics editors in the browser".
- Low-level DOM automation becomes chatty and flaky (hundreds of tiny clicks/drags).
- App adapters move the loop into the server: one MCP call can perform many trusted CDP actions.
"""

from __future__ import annotations

from .registry import app_registry

__all__ = ["app_registry"]
