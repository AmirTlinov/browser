"""
Universal page search functionality.

Auto-finds search input using multiple strategies.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session, with_retry


@with_retry(max_attempts=3, delay=0.3)
def search_page(config: BrowserConfig, query: str, submit: bool = True) -> dict[str, Any]:
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
            tool="search_page", action="validate", reason="Empty query", suggestion="Provide a search query"
        )

    with get_session(config) as (session, target):
        js = _build_search_js(query, submit)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="search_page",
                action="evaluate",
                reason="Search evaluation returned null",
                suggestion="Page may have navigated or crashed",
            )

        if result.get("error"):
            raise SmartToolError(
                tool="search_page",
                action="find_input",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Try fill_form instead"),
            )

        # Wait for navigation if submitted
        if submit and result.get("submitted"):
            time.sleep(0.5)

        return {"result": result, "target": target["id"]}


def _build_search_js(query: str, submit: bool) -> str:
    """Build JavaScript for search operation."""
    return f"""
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
    """
