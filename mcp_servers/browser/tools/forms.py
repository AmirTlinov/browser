"""
Form interaction tools for browser automation.

Provides:
- select_option: Select option in dropdown
- focus_element: Focus an element
- clear_input: Clear input field value
- wait_for_element: Wait for element to appear in DOM
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session
from .shadow_dom import DEEP_QUERY_JS


def select_option(config: BrowserConfig, selector: str, value: str, by: str = "value") -> dict[str, Any]:
    """Select an option in a <select> dropdown element.

    Args:
        config: Browser configuration
        selector: CSS selector for the select element
        value: Value to select (interpretation depends on 'by' parameter)
        by: Selection method - 'value' (default), 'text', or 'index'

    Returns:
        Dict with selector, selected value, selection method, and target ID

    Raises:
        SmartToolError: If selector not found, option not found, or invalid 'by' parameter
    """
    with get_session(config) as (session, target):
        try:
            if by == "value":
                js = f"""
                (() => {{
                    {DEEP_QUERY_JS}
                    function __mcpSetSelectValue(sel, nextValue) {{
                        // Use the native setter when available (helps React/controlled inputs).
                        try {{
                            const proto = Object.getPrototypeOf(sel);
                            const desc = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                            if (desc && typeof desc.set === 'function') {{
                                desc.set.call(sel, String(nextValue));
                                return;
                            }}
                        }} catch (_e) {{}}
                        sel.value = String(nextValue);
                    }}
                    const selector = {json.dumps(selector)};
                    const nodes = __mcpQueryAllDeep(selector, 1000);
                    const pickFrom = nodes.filter(__mcpIsVisible);
                    const sel = (pickFrom.length ? pickFrom : nodes)[0] || null;
                    if (!sel) throw new Error('Select element not found');
                    if (String(sel.tagName || '').toLowerCase() !== 'select') throw new Error('Element is not a <select>');
                    const desired = {json.dumps(value)};
                    __mcpSetSelectValue(sel, desired);
                    sel.dispatchEvent(new Event('input', {{bubbles: true}}));
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    if (String(sel.value) !== String(desired)) throw new Error('Select value did not change');
                    return sel.value;
                }})()
                """
            elif by == "text":
                js = f"""
                (() => {{
                    {DEEP_QUERY_JS}
                    function __mcpSetSelectValue(sel, nextValue) {{
                        try {{
                            const proto = Object.getPrototypeOf(sel);
                            const desc = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                            if (desc && typeof desc.set === 'function') {{
                                desc.set.call(sel, String(nextValue));
                                return;
                            }}
                        }} catch (_e) {{}}
                        sel.value = String(nextValue);
                    }}
                    const selector = {json.dumps(selector)};
                    const nodes = __mcpQueryAllDeep(selector, 1000);
                    const pickFrom = nodes.filter(__mcpIsVisible);
                    const sel = (pickFrom.length ? pickFrom : nodes)[0] || null;
                    if (!sel) throw new Error('Select element not found');
                    if (String(sel.tagName || '').toLowerCase() !== 'select') throw new Error('Element is not a <select>');
                    const opts = Array.from(sel.options);
                    const opt = opts.find(o => o.text === {json.dumps(value)} || o.textContent.trim() === {json.dumps(value)});
                    if (!opt) throw new Error('Option not found');
                    __mcpSetSelectValue(sel, opt.value);
                    sel.dispatchEvent(new Event('input', {{bubbles: true}}));
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    if (String(sel.value) !== String(opt.value)) throw new Error('Select value did not change');
                    return sel.value;
                }})()
                """
            elif by == "index":
                js = f"""
                (() => {{
                    {DEEP_QUERY_JS}
                    const selector = {json.dumps(selector)};
                    const nodes = __mcpQueryAllDeep(selector, 1000);
                    const pickFrom = nodes.filter(__mcpIsVisible);
                    const sel = (pickFrom.length ? pickFrom : nodes)[0] || null;
                    if (!sel) throw new Error('Select element not found');
                    if (String(sel.tagName || '').toLowerCase() !== 'select') throw new Error('Element is not a <select>');
                    sel.selectedIndex = {int(value)};
                    sel.dispatchEvent(new Event('input', {{bubbles: true}}));
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return sel.value;
                }})()
                """
            else:
                raise SmartToolError(
                    tool="select_option",
                    action="select",
                    reason=f"Unknown 'by' type: {by}",
                    suggestion="Use 'value', 'text', or 'index'",
                )

            result = session.eval_js(js)
            return {"selector": selector, "value": result, "by": by, "target": target["id"]}

        except SmartToolError:
            raise
        except Exception as e:
            raise SmartToolError(
                tool="select_option",
                action="select",
                reason=str(e),
                suggestion="Check selector points to valid <select> element and option exists",
            ) from e


def focus_element(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Focus an element on the page.

    Args:
        config: Browser configuration
        selector: CSS selector for the element to focus

    Returns:
        Dict with selector, focus status, and target ID

    Raises:
        SmartToolError: If element not found
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                {DEEP_QUERY_JS}
                const selector = {json.dumps(selector)};
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const pickFrom = nodes.filter(__mcpIsVisible);
                const el = (pickFrom.length ? pickFrom : nodes)[0] || null;
                if (!el) throw new Error('Element not found');
                el.focus();
                return document.activeElement === el;
            }})()
            """
            result = session.eval_js(js)
            return {"selector": selector, "focused": result, "target": target["id"]}

        except Exception as e:
            raise SmartToolError(
                tool="focus_element",
                action="focus",
                reason=str(e),
                suggestion="Check selector points to valid focusable element",
            ) from e


def clear_input(config: BrowserConfig, selector: str) -> dict[str, Any]:
    """Clear an input element's value.

    Args:
        config: Browser configuration
        selector: CSS selector for the input element

    Returns:
        Dict with selector, cleared status, and target ID

    Raises:
        SmartToolError: If element not found
    """
    with get_session(config) as (session, target):
        try:
            js = f"""
            (() => {{
                {DEEP_QUERY_JS}
                const selector = {json.dumps(selector)};
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const pickFrom = nodes.filter(__mcpIsVisible);
                const el = (pickFrom.length ? pickFrom : nodes)[0] || null;
                if (!el) throw new Error('Element not found');
                if (el.isContentEditable) {{
                    el.textContent = '';
                }} else {{
                    el.value = '';
                }}
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }})()
            """
            result = session.eval_js(js)
            return {"selector": selector, "cleared": result, "target": target["id"]}

        except Exception as e:
            raise SmartToolError(
                tool="clear_input",
                action="clear",
                reason=str(e),
                suggestion="Check selector points to valid input element",
            ) from e


def wait_for_element(config: BrowserConfig, selector: str, timeout: float = 10.0) -> dict[str, Any]:
    """Wait for an element to appear in the DOM.

    Args:
        config: Browser configuration
        selector: CSS selector for the element to wait for
        timeout: Maximum time to wait in seconds (default: 10.0)

    Returns:
        Dict with selector, found status, and target ID
        Note: found=False if element doesn't appear within timeout
    """
    with get_session(config) as (session, target):
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                js = f"(() => {{ {DEEP_QUERY_JS} const nodes = __mcpQueryAllDeep({json.dumps(selector)}, 5); return nodes.length > 0; }})()"
                if session.eval_js(js):
                    return {"selector": selector, "found": True, "target": target["id"]}
                time.sleep(0.2)

            return {"selector": selector, "found": False, "target": target["id"]}

        except Exception as e:
            raise SmartToolError(
                tool="wait_for_element",
                action="wait",
                reason=str(e),
                suggestion="Check selector is valid and page is responsive",
            ) from e
