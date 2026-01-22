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
from ..shadow_dom import DEEP_QUERY_JS


def dom_action_click(
    config: BrowserConfig,
    selector: str,
    *,
    index: int = 0,
    button: str = "left",
    click_count: int = 1,
) -> dict[str, Any]:
    """Click an element via JavaScript (programmatic click).

    Args:
        config: Browser configuration
        selector: CSS selector for element to click

    Returns:
        Dict with selector, click metadata, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            if button not in {"left", "right", "middle"}:
                raise SmartToolError(
                    tool="dom_action_click",
                    action="validate",
                    reason=f"Invalid mouse button: {button}",
                    suggestion="Use one of: left, right, middle",
                )

            click_count = max(1, int(click_count))

            js = """
            (() => {
                __DEEP_QUERY__

                const selector = __SELECTOR__;
                const reqIndex = __INDEX__;
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const matchesFound = nodes.length;

                // Prefer visible elements
                const visible = nodes.filter(__mcpIsVisible);
                const pickFrom = visible.length ? visible : nodes;
                const idx = __mcpPickIndex(pickFrom.length, reqIndex);
                const el = idx == null ? null : pickFrom[idx];
                if (!el) return { error: true, reason: 'Element not found', selector, matchesFound };

                try {
                    el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
                } catch (e) {
                    // ignore
                }

                const r = el.getBoundingClientRect();
                const text = (el.textContent || el.value || el.getAttribute('aria-label') || '').trim();
                const href = el.href || el.getAttribute('href') || null;
                let inShadowDOM = false;
                try {
                    inShadowDOM = !!(el.getRootNode && el.getRootNode() !== document);
                } catch (e) {
                    inShadowDOM = false;
                }

                return {
                    success: true,
                    selector,
                    matchesFound,
                    index: idx,
                    tagName: el.tagName,
                    text: text.slice(0, 120),
                    href,
                    inShadowDOM,
                    bounds: { x: r.x, y: r.y, width: r.width, height: r.height },
                };
            })()
            """

            js = (
                js.replace("__DEEP_QUERY__", DEEP_QUERY_JS)
                .replace("__SELECTOR__", json.dumps(selector))
                .replace("__INDEX__", str(int(index)))
            )

            info = session.eval_js(js)
            if not info or info.get("error") or not info.get("success"):
                raise SmartToolError(
                    tool="dom_action_click",
                    action="find",
                    reason=(info or {}).get("reason", f"Element not found: {selector}"),
                    suggestion="Check selector or use page(detail='locators') to find stable selectors",
                    details={"selector": selector},
                )

            bounds = info.get("bounds") or {}
            x = float(bounds.get("x", 0.0)) + float(bounds.get("width", 0.0)) / 2
            y = float(bounds.get("y", 0.0)) + float(bounds.get("height", 0.0)) / 2

            session.click(x, y, button=button, click_count=click_count)

            return {
                "command": "click",
                "selector": selector,
                "index": int(info.get("index", 0)),
                "button": button,
                "clickCount": click_count,
                "clicked": {
                    "tagName": info.get("tagName"),
                    "text": info.get("text"),
                    "href": info.get("href"),
                    "bounds": info.get("bounds"),
                    "inShadowDOM": info.get("inShadowDOM", False),
                },
                "matchesFound": info.get("matchesFound"),
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


def dom_action_type(
    config: BrowserConfig,
    selector: str,
    text: str,
    clear: bool = True,
    *,
    index: int = 0,
) -> dict[str, Any]:
    """Type into an input element via JavaScript.

    Args:
        config: Browser configuration
        selector: CSS selector for input element
        text: Text to type
        clear: Whether to clear existing value first (default: True)

    Returns:
        Dict with selector, typed text, final value, target ID, and session tab ID
    """
    with get_session(config) as (session, target):
        try:
            js = """
            (() => {
                __DEEP_QUERY__

                const selector = __SELECTOR__;
                const reqIndex = __INDEX__;
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const matchesFound = nodes.length;

                const visible = nodes.filter(__mcpIsVisible);
                const pickFrom = visible.length ? visible : nodes;
                const idx = __mcpPickIndex(pickFrom.length, reqIndex);
                const el = idx == null ? null : pickFrom[idx];
                if (!el) return { error: true, reason: 'Element not found', selector, matchesFound };

                const tagName = String(el.tagName || '');
                const tagLower = tagName.toLowerCase();
                const inputType = String(
                    el.getAttribute && el.getAttribute('type') ? el.getAttribute('type') : (el.type || '')
                ).toLowerCase();
                const isEditable = !!(
                    el.isContentEditable ||
                    tagLower === 'textarea' ||
                    (tagLower === 'input' && inputType !== 'button' && inputType !== 'submit' && inputType !== 'reset')
                );

                if (tagLower === 'select') {
                    return {
                        error: true,
                        reason: 'Target is a <select>',
                        selector,
                        matchesFound,
                        suggestion: 'Use form(select={selector, value}) for dropdowns',
                    };
                }

                try {
                    el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
                } catch (e) {
                    // ignore
                }

                try {
                    el.focus();
                } catch (e) {
                    // ignore
                }

                if (!isEditable) {
                    return {
                        error: true,
                        reason: 'Element is not editable',
                        selector,
                        matchesFound,
                        tagName,
                        inputType,
                        suggestion: 'Use click() to activate or use form(fill=...) for forms',
                    };
                }

                if (__CLEAR__) {
                    try {
                        if (el.isContentEditable) {
                            el.textContent = '';
                        } else {
                            el.value = '';
                        }
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    } catch (e) {
                        // ignore
                    }
                }

                let inShadowDOM = false;
                try {
                    inShadowDOM = !!(el.getRootNode && el.getRootNode() !== document);
                } catch (e) {
                    inShadowDOM = false;
                }

                return {
                    success: true,
                    selector,
                    matchesFound,
                    index: idx,
                    tagName,
                    inputType,
                    inShadowDOM,
                };
            })()
            """

            js = (
                js.replace("__DEEP_QUERY__", DEEP_QUERY_JS)
                .replace("__SELECTOR__", json.dumps(selector))
                .replace("__INDEX__", str(int(index)))
                .replace("__CLEAR__", "true" if clear else "false")
            )

            info = session.eval_js(js)
            if not info or info.get("error") or not info.get("success"):
                raise SmartToolError(
                    tool="dom_action_type",
                    action="find",
                    reason=(info or {}).get("reason", f"Element not found: {selector}"),
                    suggestion=(info or {}).get(
                        "suggestion",
                        "Check selector or use page(detail='locators') to find stable selectors",
                    ),
                    details={"selector": selector},
                )

            session.type_text(text)

            verify_js = f"""
            (() => {{
                {DEEP_QUERY_JS}
                const selector = {json.dumps(selector)};
                const reqIndex = {int(info.get("index", 0))};
                const nodes = __mcpQueryAllDeep(selector, 1000);
                const visible = nodes.filter(__mcpIsVisible);
                const pickFrom = visible.length ? visible : nodes;
                const idx = __mcpPickIndex(pickFrom.length, reqIndex);
                const el = idx == null ? null : pickFrom[idx];
                if (!el) return null;
                if (el.isContentEditable) return String(el.textContent || '');
                return String(el.value != null ? el.value : '');
            }})()
            """
            final_value = session.eval_js(verify_js)

            return {
                "command": "type",
                "selector": selector,
                "text": text,
                "index": int(info.get("index", 0)),
                "cleared": bool(clear),
                "result": {
                    "typed": True,
                    "value": final_value,
                    "tagName": info.get("tagName"),
                    "inputType": info.get("inputType"),
                    "inShadowDOM": info.get("inShadowDOM", False),
                    "matchesFound": info.get("matchesFound"),
                },
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
