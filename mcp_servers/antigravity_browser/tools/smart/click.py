"""
Smart element clicking by natural language.

Uses text, role, and proximity instead of CSS selectors.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session, with_retry


@with_retry(max_attempts=3, delay=0.3)
def click_element(
    config: BrowserConfig,
    text: str | None = None,
    role: str | None = None,
    near_text: str | None = None,
    index: int = 0,
    wait_timeout: float = 3.0,
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
            suggestion="Provide at least one of: text, role, or near_text",
        )

    with get_session(config) as (session, target):
        js = _build_click_js(text, role, near_text, index, wait_timeout)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="click_element",
                action="evaluate",
                reason="Click evaluation returned null",
                suggestion="Page may have navigated or crashed",
            )

        if result.get("error"):
            raise SmartToolError(
                tool="click_element",
                action="find",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check element exists"),
                details=result.get("searchCriteria", {}),
            )

        return {"result": result, "target": target["id"]}


def _build_click_js(text: str | None, role: str | None, near_text: str | None, index: int, wait_timeout: float) -> str:
    """Build JavaScript for smart click operation."""
    return f"""
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
    """
