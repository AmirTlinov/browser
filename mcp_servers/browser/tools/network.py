"""
Network operations for browser automation.

Provides:
- browser_fetch: Fetch URL from page context (subject to CORS)
- eval_js: Evaluate JavaScript expression in page context
- dump_dom_html: Navigate to URL and return full DOM HTML
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, ensure_allowed, ensure_allowed_navigation, get_session


def browser_fetch(
    config: BrowserConfig,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any | None = None,
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
    if not isinstance(url, str) or not url.strip():
        raise SmartToolError(
            tool="browser_fetch",
            action="validate",
            reason="url must be a non-empty string",
            suggestion='Provide url="https://..." or url="/api/..."',
        )

    method = str(method or "GET").upper()
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
        raise SmartToolError(
            tool="browser_fetch",
            action="validate",
            reason=f"Unsupported method: {method}",
            suggestion="Use one of: GET, POST, PUT, DELETE, PATCH",
        )

    credentials = str(credentials or "include").lower()
    if credentials not in {"include", "same-origin", "omit"}:
        raise SmartToolError(
            tool="browser_fetch",
            action="validate",
            reason=f"Unsupported credentials mode: {credentials}",
            suggestion="Use credentials='include' (default), 'same-origin', or 'omit'",
        )

    try:
        max_body_size_i = int(max_body_size)
    except Exception:
        max_body_size_i = 1_000_000
    max_body_size_i = max(0, min(max_body_size_i, 5_000_000))

    safe_headers: dict[str, str] | None = None
    if headers is None:
        safe_headers = None
    elif isinstance(headers, dict):
        safe_headers = {}
        for k, v in list(headers.items())[:50]:
            if k is None:
                continue
            key = str(k).strip()
            if not key:
                continue
            safe_headers[key] = "" if v is None else str(v)
    else:
        raise SmartToolError(
            tool="browser_fetch",
            action="validate",
            reason="headers must be an object/dict of string->string",
            suggestion='Provide headers={"Content-Type":"application/json"} or omit headers',
        )

    body_text: str | None = None
    if body is not None and method not in ("GET", "HEAD"):
        if isinstance(body, str):
            body_text = body
        else:
            # Best-effort: allow structured bodies (agents often pass dicts) but keep it explicit.
            try:
                body_text = json.dumps(body)
            except Exception:
                body_text = str(body)

        # If we auto-jsonified the body, ensure a reasonable content-type default.
        if safe_headers is not None and "Content-Type" not in safe_headers:
            safe_headers["Content-Type"] = "application/json"

    # Strict URL validation for fetch (only http/https).
    # Note: relative URLs ("/api") are allowed, but are resolved against the current page URL.
    parsed = urllib.parse.urlparse(url)
    url_is_absolute_http = parsed.scheme in ("http", "https")
    if url_is_absolute_http:
        ensure_allowed(url, config)

    with get_session(config) as (session, target):
        try:
            resolved_url = url
            if not url_is_absolute_http:
                # Resolve relative / protocol-relative URLs against the current page URL.
                # This keeps allowlist enforcement meaningful while supporting `fetch("/api")`.
                try:
                    resolved_url = session.eval_js(f"new URL({json.dumps(url)}, window.location.href).toString()")
                except Exception as exc:  # noqa: BLE001
                    raise SmartToolError(
                        tool="browser_fetch",
                        action="resolve_url",
                        reason=str(exc),
                        suggestion="Navigate to a http(s) page first, then use a relative URL",
                        details={"url": url},
                    ) from exc

                if not isinstance(resolved_url, str) or not resolved_url:
                    raise SmartToolError(
                        tool="browser_fetch",
                        action="resolve_url",
                        reason="Failed to resolve URL in page context",
                        suggestion="Navigate to a http(s) page first, then retry",
                        details={"url": url},
                    )

                ensure_allowed(resolved_url, config)

            fetch_options: dict[str, Any] = {
                "method": method,
                "credentials": credentials,
            }
            if safe_headers:
                fetch_options["headers"] = safe_headers
            if body_text is not None and method not in ("GET", "HEAD"):
                fetch_options["body"] = body_text

            # Default timeout: reuse HTTP timeout budget (seconds -> ms).
            # This avoids hanging forever on slow/stuck requests.
            try:
                timeout_ms = int(max(1.0, float(getattr(config, "http_timeout", 10.0))) * 1000)
            except Exception:
                timeout_ms = 10_000
            timeout_ms = max(250, min(timeout_ms, 120_000))

            fetch_code = f"""
            (async () => {{
                try {{
                    const options = {json.dumps(fetch_options)};
                    // Add mode for cross-origin requests
                    if (!options.mode) options.mode = 'cors';

                    // AbortController timeout to avoid infinite hangs.
                    const controller = new AbortController();
                    const timer = setTimeout(() => {{
                        try {{ controller.abort(); }} catch (_e) {{}}
                    }}, {timeout_ms});
                    options.signal = controller.signal;

                    let resp;
                    try {{
                        resp = await fetch({json.dumps(resolved_url)}, options);
                    }} finally {{
                        clearTimeout(timer);
                    }}
                    let text = '';
                    try {{
                        text = await resp.text();
                    }} catch (textErr) {{
                        text = '[Unable to read response body: ' + textErr.message + ']';
                    }}
                    const truncated = text.length > {max_body_size_i};
                    return {{
                        ok: resp.ok,
                        status: resp.status,
                        statusText: resp.statusText,
                        url: {json.dumps(resolved_url)},
                        headers: Object.fromEntries(resp.headers.entries()),
                        body: text.substring(0, {max_body_size_i}),
                        truncated: truncated,
                        bodyLength: text.length
                    }};
                }} catch(e) {{
                    // Provide more context for CORS errors
                    let suggestion = 'Check URL and network connectivity';
                    const msg = String(e && e.message ? e.message : e);
                    if (String(e && e.name) === 'AbortError') {{
                        suggestion = 'Request timed out (AbortController). Increase timeout or check network.';
                    }} else if (msg.includes('CORS') || msg.includes('cross-origin') || e.name === 'TypeError') {{
                        suggestion = 'CORS blocked. Navigate to the target domain first, or use http() tool for external requests';
                    }}
                    // Never return undefined fields (CDP returnByValue drops them).
                    const reason = msg || (e && e.name ? String(e.name) : 'fetch_failed');
                    const et = e && e.name ? String(e.name) : 'Error';
                    return {{ ok: false, error: reason, errorType: et, suggestion: suggestion }};
                }}
            }})()
            """
            result = session.eval_js(fetch_code)

            if not isinstance(result, dict) or not result:
                raise SmartToolError(
                    tool="browser_fetch",
                    action="fetch",
                    reason="Fetch returned no result",
                    suggestion="Check URL and CORS settings. Use http() tool for external requests.",
                )

            if result.get("error") or result.get("ok") is False:
                err_text = result.get("error") if isinstance(result.get("error"), str) else None
                if not err_text:
                    err_text = "Fetch failed"
                raise SmartToolError(
                    tool="browser_fetch",
                    action="fetch",
                    reason=f"Fetch failed: {err_text}",
                    suggestion=result.get(
                        "suggestion", "Check URL, CORS, and network connectivity. Use http() for external APIs."
                    ),
                    details={
                        "errorType": result.get("errorType"),
                        "url": result.get("url", resolved_url),
                        "method": method,
                    },
                )

            return {
                "status": result.get("status"),
                "statusText": result.get("statusText"),
                "url": result.get("url", resolved_url),
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
