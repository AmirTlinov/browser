"""Session management facade.

Stable import surface:
- `session_manager`: global SessionManager instance
- `BrowserSession`, `CdpConnection`, `ExtensionCdpConnection`: exported types

Implementation lives in `session_manager.py` / `browser_session.py` / `session_cdp.py`.
"""

from __future__ import annotations

from .browser_session import BrowserSession
from .session_cdp import CdpConnection, ExtensionCdpConnection
from .session_manager import SessionManager

# Global session manager instance
session_manager = SessionManager()

__all__ = [
    "BrowserSession",
    "CdpConnection",
    "ExtensionCdpConnection",
    "SessionManager",
    "session_manager",
]
