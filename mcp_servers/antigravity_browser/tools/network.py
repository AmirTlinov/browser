"""
Network operations for browser automation.

Provides:
- browser_fetch: Fetch URL from page context (subject to CORS)
- eval_js: Evaluate JavaScript expression in page context
- dump_dom_html: Navigate to URL and return full DOM HTML
"""
from __future__ import annotations

import json
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, ensure_allowed, ensure_allowed_navigation, get_session


def browser_fetch(
    config: BrowserConfig,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    credentials: str = "include",
    max_body_size: int = 1000000,
) -> dict[str, Any]:
    """
    Fetch URL from page context via Runtime.evaluate.

    Subject to CORS restrictions of the current page. The browser must be
    navigated to a page with the same origin or CORS must be configured.

    Args:
        config: Browser configuration
        url: Target URL to fetch
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        headers: Optional HTTP headers
        body: Request body (for POST/PUT/PATCH)
        credentials: Credentials mode (include, same-origin, omit)
        max_body_size: Maximum response body size in bytes

    Returns:
        Dict with status, statusText, headers, body, truncated, bodyLength, target

    Raises:
        SmartToolError: If URL validation fails or fetch fails
    """
    # Strict URL validation for fetch (only http/https)
    ensure_allowed(url, config)

    with get_session(config) as (session, target):
        try:
            fetch_options: dict[str, Any] = {
                "method": method,
                "credentials": credentials,
            }
            if headers:
                fetch_options["headers"] = headers
            if body and method not in ("GET", "HEAD"):
                fetch_options["body"] = body

            fetch_code = f"""
            (async () => {{
                try {{
                    const resp = await fetch({json.dumps(url)}, {json.dumps(fetch_options)});
                    const text = await resp.text();
                    const truncated = text.length > {max_body_size};
                    return {{
                        ok: resp.ok,
                        status: resp.status,
                        statusText: resp.statusText,
                        headers: Object.fromEntries(resp.headers.entries()),
                        body: text.substring(0, {max_body_size}),
                        truncated: truncated,
                        bodyLength: text.length
                    }};
                }} catch(e) {{
                    return {{ ok: false, error: e.message, errorType: e.name }};
                }}
            }})()
            """
            result = session.eval_js(fetch_code)

            if not result:
                raise SmartToolError(
                    tool="browser_fetch",
                    action="fetch",
                    reason="Fetch returned no result",
                    suggestion="Check URL and CORS settings",
                )
            if not result.get("ok", False) and result.get("error"):
                raise SmartToolError(
                    tool="browser_fetch",
                    action="fetch",
                    reason=f"Fetch failed: {result.get('error')}",
                    suggestion="Check URL, CORS, and network connectivity",
                )

            return {
                "status": result.get("status"),
                "statusText": result.get("statusText"),
                "headers": result.get("headers", {}),
                "body": result.get("body", ""),
                "truncated": result.get("truncated", False),
                "bodyLength": result.get("bodyLength", 0),
                "target": target["id"],
            }
        except SmartToolError:
            raise
        except Exception as e:
            raise SmartToolError(
                tool="browser_fetch",
                action="fetch",
                reason=str(e),
                suggestion="Check URL and page context",
            ) from e


def eval_js(config: BrowserConfig, expression: str) -> dict[str, Any]:
    """
    Evaluate JavaScript expression in the active page context.

    Args:
        config: Browser configuration
        expression: JavaScript expression to evaluate

    Returns:
        Dict with result and target ID

    Raises:
        SmartToolError: If expression is invalid or evaluation fails
    """
    if not expression or not isinstance(expression, str):
        raise SmartToolError(
            tool="eval_js",
            action="validate",
            reason="Expression must be a non-empty string",
            suggestion="Provide valid JavaScript expression",
        )

    with get_session(config) as (session, target):
        try:
            result = session.eval_js(expression)
            return {"result": result, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="eval_js",
                action="evaluate",
                reason=str(e),
                suggestion="Check JavaScript syntax and page context",
            ) from e


DEFAULT_DOM_MAX_CHARS = 50000  # 50KB default
MAX_DOM_CHARS_LIMIT = 200000  # 200KB max


def dump_dom_html(
    config: BrowserConfig,
    url: str,
    max_chars: int = DEFAULT_DOM_MAX_CHARS,
) -> dict[str, Any]:
    """
    Navigate to URL and return DOM HTML with size limiting.

    IMPORTANT: Consider using browser_navigate() + analyze_page() for
    structured data - they are more context-efficient.

    Args:
        config: Browser configuration
        url: URL to navigate to and dump
        max_chars: Maximum HTML characters to return (default: 50000, max: 200000)

    Returns:
        Dict with:
        - html: HTML content (truncated if exceeds max_chars)
        - targetId: Browser target ID
        - totalChars: Original HTML size
        - truncated: True if HTML was truncated
        - hint: Suggestion if truncated

    Raises:
        SmartToolError: If URL validation fails or navigation fails
    """
    # Validate URL against allowlist
    ensure_allowed_navigation(url, config)
    max_chars = min(max_chars, MAX_DOM_CHARS_LIMIT)

    with get_session(config) as (session, target):
        try:
            session.navigate(url, wait_load=True)
            html = session.get_dom()
            total_chars = len(html)
            truncated = total_chars > max_chars

            if truncated:
                html = html[:max_chars]

            result: dict[str, Any] = {
                "html": html,
                "targetId": target["id"],
                "totalChars": total_chars,
                "truncated": truncated,
            }

            if truncated:
                result["hint"] = (
                    f"HTML truncated ({total_chars} -> {max_chars} chars). "
                    f"Consider using browser_navigate(url) + analyze_page() for structured data, "
                    f"or increase max_chars (up to {MAX_DOM_CHARS_LIMIT})."
                )

            return result
        except Exception as e:
            raise SmartToolError(
                tool="dump_dom_html",
                action="navigate",
                reason=str(e),
                suggestion="Check URL and network connectivity. Consider using browser_navigate() + analyze_page() instead.",
            ) from e
