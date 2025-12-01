"""
Tool handlers organized by domain.

Each handler module provides functions that handle specific tool calls.
All handlers follow the signature: (config, launcher, arguments) -> ToolResult
"""

from .captcha import CAPTCHA_HANDLERS
from .cookies import COOKIE_HANDLERS
from .dom import DOM_HANDLERS
from .input import INPUT_HANDLERS
from .navigation import NAVIGATION_HANDLERS
from .network import NETWORK_HANDLERS
from .smart import SMART_HANDLERS
from .tabs import TAB_HANDLERS

# Aggregate all handlers
ALL_HANDLERS: dict[str, tuple] = {
    **SMART_HANDLERS,
    **CAPTCHA_HANDLERS,
    **NETWORK_HANDLERS,
    **NAVIGATION_HANDLERS,
    **DOM_HANDLERS,
    **INPUT_HANDLERS,
    **COOKIE_HANDLERS,
    **TAB_HANDLERS,
}

__all__ = [
    "ALL_HANDLERS",
    "SMART_HANDLERS",
    "CAPTCHA_HANDLERS",
    "NETWORK_HANDLERS",
    "NAVIGATION_HANDLERS",
    "DOM_HANDLERS",
    "INPUT_HANDLERS",
    "COOKIE_HANDLERS",
    "TAB_HANDLERS",
]
