"""
Dialog handling tools for JavaScript alerts, confirms, and prompts.

Provides:
- handle_dialog: Accept or dismiss JS dialogs
"""

from __future__ import annotations

from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session


def handle_dialog(config: BrowserConfig, accept: bool = True, prompt_text: str | None = None) -> dict[str, Any]:
    """Handle JavaScript alert/confirm/prompt dialogs.

    Call when a dialog is blocking the page.

    Args:
        config: Browser configuration
        accept: True to accept/OK, False to dismiss/cancel
        prompt_text: Text to enter for prompt() dialogs

    Returns:
        Dict with accept status, prompt_text if provided, and target ID
    """
    with get_session(config) as (session, target):
        try:
            params: dict[str, Any] = {"accept": accept}
            if prompt_text is not None:
                params["promptText"] = prompt_text

            session.send("Page.handleJavaScriptDialog", params)

            result: dict[str, Any] = {"accepted": accept, "target": target["id"]}
            if prompt_text is not None:
                result["promptText"] = prompt_text
            return result
        except Exception as e:
            raise SmartToolError(
                tool="handle_dialog",
                action="handle",
                reason=str(e),
                suggestion="Ensure there is an active JavaScript dialog to handle",
            ) from e
