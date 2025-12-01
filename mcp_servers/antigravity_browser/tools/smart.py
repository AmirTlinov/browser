"""
Smart high-level browser interaction tools.

These tools provide AI-friendly abstractions using natural language descriptions
instead of CSS selectors. They handle element detection, waiting, scrolling,
and error recovery automatically.

Functions:
- click_element: Click by text/role/near_text instead of CSS selectors
- fill_form: Fill entire form by field names/labels in one operation
- search_page: Auto-find search input and submit query
- execute_workflow: Batch multiple actions in sequence
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session, with_retry

# ═══════════════════════════════════════════════════════════════════════════════
# click_element - Smart element clicking by natural language
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_attempts=3, delay=0.3)
def click_element(
    config: BrowserConfig,
    text: str | None = None,
    role: str | None = None,
    near_text: str | None = None,
    index: int = 0,
    wait_timeout: float = 3.0
) -> dict[str, Any]:
    """
    Click an element using natural language description instead of CSS selector.

    PREFERRED over browser_click. Automatically:
    - Waits for element to appear
    - Scrolls element into view
    - Handles visibility checks

    Args:
        text: Visible text of the element (button text, link text)
        role: Element role - "button", "link", "checkbox", "radio", "tab"
        near_text: Find element near this text (for unlabeled buttons)
        index: If multiple matches, which one (0 = first, -1 = last)
        wait_timeout: Max time to wait for element (default 3s)

    Examples:
        click_element(text="Sign In")
        click_element(text="Submit", role="button")
        click_element(near_text="Remember me", role="checkbox")
    """
    if not text and not role and not near_text:
        raise SmartToolError(
            tool="click_element",
            action="validate",
            reason="No search criteria provided",
            suggestion="Provide at least one of: text, role, or near_text"
        )

    with get_session(config) as (session, target):
        js = f'''
        (() => {{
            const searchText = {json.dumps(text)};
            const searchRole = {json.dumps(role)};
            const nearText = {json.dumps(near_text)};
            const targetIndex = {index};
            const timeout = {wait_timeout * 1000};

            // Helper: Check visibility
            const isVisible = (el) => {{
                if (!el) return false;
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                       style.visibility !== 'hidden' &&
                       style.opacity !== '0' &&
                       rect.width > 0 &&
                       rect.height > 0;
            }};

            // Helper: Get clean text
            const getCleanText = (el) => {{
                if (!el) return '';
                const clone = el.cloneNode(true);
                clone.querySelectorAll('script, style, svg').forEach(e => e.remove());
                return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
            }};

            // Helper: Find elements matching criteria
            const findMatches = () => {{
                let candidates = [];

                // Role-based selection
                const roleSelectors = {{
                    'button': 'button, input[type="button"], input[type="submit"], [role="button"]',
                    'link': 'a[href], [role="link"]',
                    'checkbox': 'input[type="checkbox"], [role="checkbox"]',
                    'radio': 'input[type="radio"], [role="radio"]',
                    'tab': '[role="tab"]',
                    'menuitem': '[role="menuitem"]'
                }};

                if (searchRole && roleSelectors[searchRole]) {{
                    candidates = Array.from(document.querySelectorAll(roleSelectors[searchRole]));
                }} else if (searchText) {{
                    // Search all clickable elements
                    const clickableSelector = 'a, button, input[type="button"], input[type="submit"], ' +
                        '[role="button"], [role="link"], [onclick], [tabindex]';
                    candidates = Array.from(document.querySelectorAll(clickableSelector));
                }}

                // Filter by visibility
                candidates = candidates.filter(isVisible);

                // Filter by text if provided
                if (searchText) {{
                    const searchLower = searchText.toLowerCase();
                    candidates = candidates.filter(el => {{
                        const elText = getCleanText(el).toLowerCase();
                        const value = (el.value || '').toLowerCase();
                        const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                        return elText.includes(searchLower) ||
                               value.includes(searchLower) ||
                               ariaLabel.includes(searchLower);
                    }});

                    // Sort by exact match first, then by text length (shorter = more specific)
                    candidates.sort((a, b) => {{
                        const aText = getCleanText(a).toLowerCase();
                        const bText = getCleanText(b).toLowerCase();
                        const aExact = aText === searchLower ? 0 : 1;
                        const bExact = bText === searchLower ? 0 : 1;
                        if (aExact !== bExact) return aExact - bExact;
                        return aText.length - bText.length;
                    }});
                }}

                // Filter by proximity to nearText
                if (nearText) {{
                    const nearLower = nearText.toLowerCase();
                    // Find elements containing the reference text
                    const refElements = Array.from(document.querySelectorAll('*')).filter(el => {{
                        const text = getCleanText(el);
                        return text.toLowerCase().includes(nearLower) && el.children.length < 3;
                    }});

                    if (refElements.length > 0) {{
                        const refEl = refElements[0];
                        const refRect = refEl.getBoundingClientRect();

                        // Find closest matching element
                        candidates = candidates.map(el => {{
                            const elRect = el.getBoundingClientRect();
                            const distance = Math.sqrt(
                                Math.pow(elRect.left - refRect.left, 2) +
                                Math.pow(elRect.top - refRect.top, 2)
                            );
                            return {{ el, distance }};
                        }})
                        .filter(item => item.distance < 300)  // Max 300px away
                        .sort((a, b) => a.distance - b.distance)
                        .map(item => item.el);
                    }}
                }}

                return candidates;
            }};

            // Wait and find
            const startTime = Date.now();
            let matches = [];

            while (Date.now() - startTime < timeout) {{
                matches = findMatches();
                if (matches.length > 0) break;
                // Synchronous wait (not ideal but works in eval context)
                const waitUntil = Date.now() + 100;
                while (Date.now() < waitUntil) {{}}
            }}

            if (matches.length === 0) {{
                return {{
                    error: true,
                    reason: 'Element not found',
                    searchCriteria: {{ text: searchText, role: searchRole, nearText: nearText }},
                    suggestion: 'Try analyze_page first to see available elements, or use different text/role'
                }};
            }}

            // Select element by index
            const idx = targetIndex < 0 ? matches.length + targetIndex : targetIndex;
            const element = matches[Math.min(idx, matches.length - 1)];

            if (!element) {{
                return {{
                    error: true,
                    reason: 'Index out of range',
                    found: matches.length,
                    suggestion: `Found ${{matches.length}} matches, use index 0-${{matches.length - 1}}`
                }};
            }}

            // Scroll into view
            element.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});

            // Small delay for scroll to complete
            const scrollWait = Date.now() + 100;
            while (Date.now() < scrollWait) {{}}

            // Click
            element.click();

            return {{
                success: true,
                tagName: element.tagName,
                text: getCleanText(element).substring(0, 60),
                href: element.href || null,
                type: element.type || null,
                matchesFound: matches.length
            }};
        }})()
        '''

        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="click_element",
                action="evaluate",
                reason="Click evaluation returned null",
                suggestion="Page may have navigated or crashed"
            )

        if result.get("error"):
            raise SmartToolError(
                tool="click_element",
                action="find",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check element exists"),
                details=result.get("searchCriteria", {})
            )

        return {
            "result": result,
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# fill_form - Smart form filling
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_attempts=2, delay=0.2)
def fill_form(
    config: BrowserConfig,
    data: dict[str, Any],
    form_index: int = 0,
    submit: bool = False
) -> dict[str, Any]:
    """
    Fill a form with provided data in one operation.

    PREFERRED over multiple browser_type calls. Intelligently matches fields by:
    1. Exact name/id match
    2. Label text match
    3. Placeholder match
    4. Aria-label match

    Args:
        data: Dict mapping field identifiers to values. Keys can be:
              - Field name/id: {"email": "user@example.com"}
              - Label text: {"Email Address": "user@example.com"}
              For checkboxes/radios: use true/false
        form_index: Which form on the page (0 = first)
        submit: Whether to submit after filling

    Returns dict with filled fields, errors, and submit status.
    """
    if not data:
        raise SmartToolError(
            tool="fill_form",
            action="validate",
            reason="No data provided",
            suggestion="Provide a dict with field names/values"
        )

    with get_session(config) as (session, target):
        js = f'''
        (() => {{
            const data = {json.dumps(data)};
            const formIndex = {form_index};
            const shouldSubmit = {json.dumps(submit)};

            const forms = document.querySelectorAll('form');
            const form = forms[formIndex] || null;
            const searchScope = form || document;

            // Helper: Check visibility
            const isVisible = (el) => {{
                if (!el) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }};

            // Helper: Find field by various strategies
            const findField = (key) => {{
                const keyLower = key.toLowerCase().trim();

                // Strategy 1: Exact name/id match
                let el = searchScope.querySelector(`[name="${{key}}"], #${{CSS.escape(key)}}`);
                if (el && isVisible(el)) return el;

                // Strategy 2: Case-insensitive name/id
                el = searchScope.querySelector(`[name="${{keyLower}}" i], [id="${{keyLower}}" i]`);
                if (el && isVisible(el)) return el;

                // Strategy 3: Partial name/id match
                const allInputs = searchScope.querySelectorAll('input, select, textarea');
                for (const input of allInputs) {{
                    if (!isVisible(input)) continue;
                    const name = (input.name || '').toLowerCase();
                    const id = (input.id || '').toLowerCase();
                    if (name.includes(keyLower) || id.includes(keyLower)) return input;
                }}

                // Strategy 4: Label text match
                const labels = searchScope.querySelectorAll('label');
                for (const label of labels) {{
                    const labelText = (label.textContent || '').toLowerCase().trim();
                    if (labelText.includes(keyLower)) {{
                        if (label.htmlFor) {{
                            el = document.getElementById(label.htmlFor);
                            if (el && isVisible(el)) return el;
                        }}
                        el = label.querySelector('input, select, textarea');
                        if (el && isVisible(el)) return el;
                    }}
                }}

                // Strategy 5: Placeholder match
                for (const input of allInputs) {{
                    if (!isVisible(input)) continue;
                    const placeholder = (input.placeholder || '').toLowerCase();
                    if (placeholder.includes(keyLower)) return input;
                }}

                // Strategy 6: Aria-label match
                for (const input of allInputs) {{
                    if (!isVisible(input)) continue;
                    const ariaLabel = (input.getAttribute('aria-label') || '').toLowerCase();
                    if (ariaLabel.includes(keyLower)) return input;
                }}

                return null;
            }};

            const results = {{
                success: true,
                filled: [],
                notFound: [],
                errors: [],
                submitted: false
            }};

            // Fill each field
            for (const [key, value] of Object.entries(data)) {{
                const field = findField(key);

                if (!field) {{
                    results.notFound.push(key);
                    results.success = false;
                    continue;
                }}

                try {{
                    const tagName = field.tagName.toLowerCase();
                    const type = (field.type || '').toLowerCase();

                    if (type === 'checkbox') {{
                        const shouldCheck = Boolean(value);
                        if (field.checked !== shouldCheck) {{
                            field.click();
                        }}
                        results.filled.push({{ key, type: 'checkbox', checked: field.checked }});
                    }} else if (type === 'radio') {{
                        field.checked = true;
                        field.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        results.filled.push({{ key, type: 'radio', value: field.value }});
                    }} else if (tagName === 'select') {{
                        // Try value first, then text
                        let found = false;
                        for (const opt of field.options) {{
                            if (opt.value === value || opt.textContent.trim() === value) {{
                                field.value = opt.value;
                                found = true;
                                break;
                            }}
                        }}
                        if (!found) field.value = value;
                        field.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        results.filled.push({{ key, type: 'select', value: field.value }});
                    }} else {{
                        // Text input, textarea, etc.
                        field.focus();
                        field.value = String(value);
                        field.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        field.dispatchEvent(new Event('change', {{ bubbles: true }}));

                        // Verify
                        if (field.value !== String(value)) {{
                            results.errors.push({{
                                key, error: 'Value not set correctly', expected: value, actual: field.value
                            }});
                        }} else {{
                            results.filled.push({{ key, type: type || 'text', valueLength: field.value.length }});
                        }}
                    }}
                }} catch (e) {{
                    results.errors.push({{ key, error: e.message }});
                    results.success = false;
                }}
            }}

            // Submit if requested
            if (shouldSubmit && results.filled.length > 0) {{
                const submitBtn = searchScope.querySelector(
                    'button[type="submit"], input[type="submit"], button:not([type="button"]):not([type="reset"])'
                );
                if (submitBtn && isVisible(submitBtn)) {{
                    submitBtn.click();
                    results.submitted = true;
                }} else if (form) {{
                    form.submit();
                    results.submitted = true;
                }} else {{
                    results.errors.push({{ error: 'No submit button found and no form to submit' }});
                }}
            }}

            return results;
        }})()
        '''

        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="fill_form",
                action="evaluate",
                reason="Form fill returned null",
                suggestion="Page may have navigated or form structure changed"
            )

        if result.get("notFound") and len(result["notFound"]) > 0:
            result["suggestion"] = f"Fields not found: {result['notFound']}. Use analyze_page to see available fields."

        return {
            "result": result,
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# search_page - Universal search functionality
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_attempts=3, delay=0.3)
def search_page(
    config: BrowserConfig,
    query: str,
    submit: bool = True
) -> dict[str, Any]:
    """
    Perform a search on the current page.

    Automatically finds the search input using multiple strategies and submits.
    Works on Google, Bing, e-commerce sites, documentation, etc.

    Args:
        query: Search text
        submit: Whether to submit the search (default: True)
    """
    if not query:
        raise SmartToolError(
            tool="search_page",
            action="validate",
            reason="Empty query",
            suggestion="Provide a search query"
        )

    with get_session(config) as (session, target):
        js = f'''
        (() => {{
            const query = {json.dumps(query)};
            const shouldSubmit = {json.dumps(submit)};

            // Helper: Check visibility
            const isVisible = (el) => {{
                if (!el) return false;
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                       style.visibility !== 'hidden' &&
                       rect.width > 0;
            }};

            // Search strategies in priority order
            const searchStrategies = [
                // Explicit search types
                () => document.querySelector('input[type="search"]:not([hidden])'),
                () => document.querySelector('textarea[type="search"]:not([hidden])'),

                // Common search field names
                () => document.querySelector('input[name="q"]:not([hidden])'),
                () => document.querySelector('textarea[name="q"]:not([hidden])'),
                () => document.querySelector('input[name="query"]:not([hidden])'),
                () => document.querySelector('input[name="search"]:not([hidden])'),
                () => document.querySelector('input[name="s"]:not([hidden])'),
                () => document.querySelector('input[name="keyword"]:not([hidden])'),
                () => document.querySelector('input[name="keywords"]:not([hidden])'),

                // ARIA roles
                () => document.querySelector('[role="searchbox"]:not([hidden])'),
                () => document.querySelector('[role="combobox"][aria-label*="search" i]:not([hidden])'),
                () => document.querySelector('[role="combobox"]:not([hidden])'),

                // Partial name matches
                () => document.querySelector('input[name*="search" i]:not([hidden])'),
                () => document.querySelector('input[name*="query" i]:not([hidden])'),
                () => document.querySelector('textarea[name*="search" i]:not([hidden])'),

                // Placeholder matches
                () => document.querySelector('input[placeholder*="search" i]:not([hidden])'),
                () => document.querySelector('input[placeholder*="поиск" i]:not([hidden])'),
                () => document.querySelector('textarea[placeholder*="search" i]:not([hidden])'),

                // Aria-label matches
                () => document.querySelector('input[aria-label*="search" i]:not([hidden])'),
                () => document.querySelector('textarea[aria-label*="search" i]:not([hidden])'),

                // Form-based search
                () => {{
                    const searchForm = document.querySelector('form[action*="search" i], form[role="search"]');
                    if (searchForm) {{
                        return searchForm.querySelector('input[type="text"], input:not([type]), textarea');
                    }}
                    return null;
                }},

                // Last resort: first visible text input in header/nav
                () => {{
                    const header = document.querySelector('header, nav, [role="banner"], [role="navigation"]');
                    if (header) {{
                        return header.querySelector('input[type="text"], input:not([type])');
                    }}
                    return null;
                }}
            ];

            // Find search input
            let searchInput = null;
            let strategyUsed = -1;

            for (let i = 0; i < searchStrategies.length; i++) {{
                const candidate = searchStrategies[i]();
                if (candidate && isVisible(candidate)) {{
                    searchInput = candidate;
                    strategyUsed = i;
                    break;
                }}
            }}

            if (!searchInput) {{
                return {{
                    error: true,
                    reason: 'No search input found',
                    suggestion: 'Use fill_form with specific field name, or analyze_page to find input fields',
                    tried: searchStrategies.length
                }};
            }}

            // Fill search input
            searchInput.focus();
            searchInput.value = query;
            searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            searchInput.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // Submit
            let submitted = false;
            let submitMethod = null;

            if (shouldSubmit) {{
                const form = searchInput.closest('form');

                if (form) {{
                    // Try submit button first
                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
                    if (submitBtn && isVisible(submitBtn)) {{
                        submitBtn.click();
                        submitted = true;
                        submitMethod = 'button';
                    }} else {{
                        // Try form.submit()
                        form.submit();
                        submitted = true;
                        submitMethod = 'form';
                    }}
                }} else {{
                    // No form, try Enter key
                    searchInput.dispatchEvent(new KeyboardEvent('keydown', {{
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    }}));
                    searchInput.dispatchEvent(new KeyboardEvent('keypress', {{
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    }}));
                    searchInput.dispatchEvent(new KeyboardEvent('keyup', {{
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        which: 13,
                        bubbles: true
                    }}));
                    submitted = true;
                    submitMethod = 'enter_key';
                }}
            }}

            return {{
                success: true,
                query: query,
                submitted: submitted,
                submitMethod: submitMethod,
                inputName: searchInput.name || searchInput.id || null,
                inputType: searchInput.tagName.toLowerCase(),
                strategyUsed: strategyUsed
            }};
        }})()
        '''

        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="search_page",
                action="evaluate",
                reason="Search evaluation returned null",
                suggestion="Page may have navigated or crashed"
            )

        if result.get("error"):
            raise SmartToolError(
                tool="search_page",
                action="find_input",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Try fill_form instead")
            )

        # Wait for navigation if submitted
        if submit and result.get("submitted"):
            time.sleep(0.5)

        return {
            "result": result,
            "target": target["id"]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# execute_workflow - Batch operations
# ═══════════════════════════════════════════════════════════════════════════════

def _execute_navigate_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute navigation step."""
    from .navigation import navigate_to

    url = step.get("url")
    if not url:
        raise SmartToolError("workflow", "navigate", "Missing url", "Provide url parameter")
    navigate_to(config, url, wait_load=step.get("wait_load", True))
    return {"success": True, "url": url}


def _execute_click_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute click step."""
    from .input import dom_action_click

    if step.get("text") or step.get("role") or step.get("near_text"):
        click_result = click_element(
            config,
            text=step.get("text"),
            role=step.get("role"),
            near_text=step.get("near_text"),
            index=step.get("index", 0)
        )
        result = click_result.get("result", {})
        result["success"] = True
        return result
    elif step.get("selector"):
        dom_action_click(config, step["selector"])
        return {"success": True, "selector": step["selector"]}
    else:
        raise SmartToolError("workflow", "click", "No click target", "Provide text, role, or selector")


def _execute_type_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute type step."""
    from .input import dom_action_type

    selector = step.get("selector")
    text = step.get("text", "")
    if not selector:
        raise SmartToolError("workflow", "type", "Missing selector", "Provide selector parameter")
    dom_action_type(config, selector, text, step.get("clear", True))
    return {"success": True}


def _execute_fill_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute fill form step."""
    data = step.get("data", {})
    fill_result = fill_form(
        config,
        data=data,
        form_index=step.get("form_index", 0),
        submit=step.get("submit", False)
    )
    result = fill_result.get("result", {})
    result["success"] = result.get("success", True)
    return result


def _execute_search_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute search step."""
    query = step.get("query", "")
    search_result = search_page(config, query, submit=step.get("submit", True))
    result = search_result.get("result", {})
    result["success"] = result.get("success", True)
    return result


def _execute_wait_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute wait step."""
    try:
        from .analysis import wait_for
        wait_result = wait_for(
            config,
            condition=step.get("condition", "load"),
            timeout=step.get("timeout", 10),
            text=step.get("text"),
            selector=step.get("selector")
        )
        wait_result["success"] = True
        return wait_result
    except ImportError:
        return {"error": "wait_for not yet implemented in modular structure"}


def _execute_screenshot_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute screenshot step."""
    with get_session(config) as (session, target):
        data_b64 = session.capture_screenshot()
        return {
            "success": True,
            "bytes": len(data_b64) * 3 // 4,
            "screenshot_b64": data_b64
        }


def _execute_extract_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute extract content step."""
    try:
        from .analysis import extract_content
        extract_result = extract_content(
            config,
            content_type=step.get("content_type", "main"),
            selector=step.get("selector")
        )
        return {"success": True, "content": extract_result.get("content")}
    except ImportError:
        return {"error": "extract_content not yet implemented in modular structure"}


def _execute_workflow_step(config: BrowserConfig, step: dict[str, Any]) -> dict[str, Any]:
    """Execute a single workflow step based on action type."""
    action = step.get("action")

    action_handlers = {
        "navigate": _execute_navigate_step,
        "click": _execute_click_step,
        "type": _execute_type_step,
        "fill": _execute_fill_step,
        "search": _execute_search_step,
        "wait": _execute_wait_step,
        "screenshot": _execute_screenshot_step,
        "extract": _execute_extract_step,
    }

    handler = action_handlers.get(action)
    if handler:
        return handler(config, step)
    else:
        return {
            "error": f"Unknown action: {action}",
            "suggestion": "Use: navigate, click, type, fill, search, wait, screenshot, extract"
        }


def execute_workflow(
    config: BrowserConfig,
    steps: list[dict[str, Any]],
    include_screenshots: bool = False,
    compact_results: bool = True,
) -> dict[str, Any]:
    """
    Execute a sequence of browser actions as a workflow.

    Allows batching multiple operations for efficiency.
    Each step is a dict with "action" and action-specific params.

    Supported actions:
    - navigate: {"action": "navigate", "url": "https://..."}
    - click: {"action": "click", "text": "Button Text"} or {"action": "click", "selector": "..."}
    - type: {"action": "type", "selector": "...", "text": "..."}
    - fill: {"action": "fill", "data": {...}, "submit": bool}
    - search: {"action": "search", "query": "..."}
    - wait: {"action": "wait", "condition": "...", "timeout": 5}
    - screenshot: {"action": "screenshot"}
    - extract: {"action": "extract", "content_type": "..."}

    Each step can have "continue_on_error": true to continue despite errors.

    Args:
        config: Browser configuration
        steps: List of action steps to execute
        include_screenshots: Include screenshot data in results (default: False to save context)
        compact_results: Return compact results without redundant fields (default: True)

    Returns:
        Summary with workflow status and step results.
        If include_screenshots=False, screenshot steps return only metadata (bytes, success).
    """
    if not steps:
        raise SmartToolError(
            tool="execute_workflow",
            action="validate",
            reason="No steps provided",
            suggestion="Provide a list of action steps"
        )

    results = []

    for i, step in enumerate(steps):
        action = step.get("action")
        step_result: dict[str, Any] = {
            "step": i,
            "action": action,
            "success": False
        }

        try:
            result = _execute_workflow_step(config, step)

            # Remove screenshot data if not requested
            if not include_screenshots and "screenshot_b64" in result:
                del result["screenshot_b64"]

            step_result.update(result)
        except SmartToolError as e:
            step_result["error"] = str(e)
            step_result["suggestion"] = e.suggestion
        except Exception as e:
            step_result["error"] = str(e)

        # Compact results - remove success=True (implied by lack of error)
        # Keep success=False for failed steps
        if compact_results and step_result.get("success") is True:
            step_result.pop("success", None)

        results.append(step_result)

        # Stop on error unless continue_on_error specified
        if step_result.get("error") and not step.get("continue_on_error"):
            break

    succeeded = sum(1 for r in results if not r.get("error"))
    completed = len(results) == len(steps) and succeeded == len(steps)

    return {
        "completed": completed,
        "total": len(steps),
        "executed": len(results),
        "succeeded": succeeded,
        "results": results
    }
