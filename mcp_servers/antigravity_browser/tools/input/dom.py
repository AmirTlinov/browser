"""
DOM-based input actions for browser automation.

Provides programmatic click and type operations via JavaScript.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import SmartToolError, get_session


def dom_action_click(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Click an element via JavaScript (programmatic click).

    Args:
        config: Browser configuration
        selector: CSS selector for element to click

    Returns:
        Dict with selector, element tag, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found: ' + {json.dumps(selector)});
                el.click();
                return {{clicked: true, tagName: el.tagName}};
            }})()
            """
            result = session.eval_js(js)
            return {
                "command": "click",
                "selector": selector,
                "result": result,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="dom_action_click",
                action="click",
                reason=str(e),
                suggestion="Check selector is correct and element is clickable",
            ) from e


def dom_action_type(config: BrowserConfig, selector: str, text: str, clear: bool = True) -> dict[str, Any]:
    """Type into an input element via JavaScript.

    Args:
        config: Browser configuration
        selector: CSS selector for input element
        text: Text to type
        clear: Whether to clear existing value first (default: True)

    Returns:
        Dict with selector, text, final value, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            clear_js = "el.value = '';" if clear else ""
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('Element not found: ' + {json.dumps(selector)});
                el.focus();
                {clear_js}
                el.value += {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return {{typed: true, value: el.value}};
            }})()
            """
            result = session.eval_js(js)
            return {
                "command": "type",
                "selector": selector,
                "text": text,
                "result": result,
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="dom_action_type",
                action="type",
                reason=str(e),
                suggestion="Check selector is correct and element is an input/textarea",
            ) from e
