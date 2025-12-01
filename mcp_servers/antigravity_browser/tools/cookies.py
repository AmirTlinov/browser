"""
Cookie management tools for browser automation.

Provides:
- set_cookie: Set a single cookie via CDP
- set_cookies_batch: Set multiple cookies at once
- get_all_cookies: Get all cookies or cookies for specific URLs
- delete_cookie: Delete a cookie by name/domain/path
"""

from __future__ import annotations

from typing import Any

from ..config import BrowserConfig
from .base import SmartToolError, get_session


def set_cookie(
    config: BrowserConfig,
    name: str,
    value: str,
    domain: str,
    path: str = "/",
    secure: bool = False,
    http_only: bool = False,
    same_site: str = "Lax",
    expires: float | None = None,
) -> dict[str, Any]:
    """Set a single cookie via CDP Network.setCookie.

    Args:
        config: Browser configuration
        name: Cookie name
        value: Cookie value
        domain: Cookie domain (e.g., '.example.com')
        path: Cookie path (default: '/')
        secure: HTTPS only (default: False)
        http_only: Not accessible via JavaScript (default: False)
        same_site: SameSite attribute: Strict, Lax, None (default: 'Lax')
        expires: Expiration timestamp in seconds since epoch (optional)

    Returns:
        Dict with success status, cookie info, and target ID
    """
    with get_session(config) as (session, target):
        try:
            session.send("Network.enable", {})
            params = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure,
                "httpOnly": http_only,
                "sameSite": same_site,
            }
            if expires is not None:
                params["expires"] = expires

            result = session.send("Network.setCookie", params)
            return {
                "success": result.get("success", False),
                "cookie": {"name": name, "domain": domain, "path": path},
                "target": target["id"],
            }
        except Exception as e:
            raise SmartToolError(
                tool="set_cookie",
                action="set",
                reason=str(e),
                suggestion="Check cookie parameters are valid (domain, path, same_site)",
            ) from e


def set_cookies_batch(config: BrowserConfig, cookies: list[dict[str, Any]]) -> dict[str, Any]:
    """Set multiple cookies at once via CDP.

    Args:
        config: Browser configuration
        cookies: List of cookie dicts with keys: name, value, domain, and optional:
                 path, secure, httpOnly, sameSite, expires

    Returns:
        Dict with results list, count, and target ID
    """
    with get_session(config) as (session, target):
        try:
            session.send("Network.enable", {})
            results = []

            for cookie in cookies:
                params = {
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie["domain"],
                    "path": cookie.get("path", "/"),
                    "secure": cookie.get("secure", False),
                    "httpOnly": cookie.get("httpOnly", False),
                    "sameSite": cookie.get("sameSite", "Lax"),
                }
                if cookie.get("expires") is not None:
                    params["expires"] = cookie["expires"]

                result = session.send("Network.setCookie", params)
                results.append({"name": cookie["name"], "success": result.get("success", False)})

            return {"results": results, "count": len(results), "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="set_cookies_batch",
                action="set_batch",
                reason=str(e),
                suggestion="Check all cookies have required fields: name, value, domain",
            ) from e


def get_all_cookies(
    config: BrowserConfig,
    urls: list[str] | None = None,
    offset: int = 0,
    limit: int = 20,
    name_filter: str | None = None,
) -> dict[str, Any]:
    """Get cookies with pagination and filtering.

    OVERVIEW MODE (default with small limit):
    Returns first N cookies with total count and navigation hints.

    Args:
        config: Browser configuration
        urls: Optional list of URLs to get cookies for. If None, returns all cookies.
        offset: Starting index for paginated results (default: 0)
        limit: Maximum cookies to return (default: 20, max: 100)
        name_filter: Filter cookies by name substring (optional)

    Returns:
        Dict with paginated cookies, total count, and navigation hints

    Examples:
        get_all_cookies()  # First 20 cookies
        get_all_cookies(offset=20, limit=20)  # Next 20 cookies
        get_all_cookies(name_filter="session")  # Filter by name
    """
    limit = min(limit, 100)  # Cap at 100

    with get_session(config) as (session, target):
        try:
            session.send("Network.enable", {})
            params: dict[str, Any] = {}
            if urls:
                params["urls"] = urls

            result = session.send("Network.getCookies", params)
            all_cookies = result.get("cookies", [])

            # Apply name filter if provided
            if name_filter:
                all_cookies = [c for c in all_cookies if name_filter.lower() in c.get("name", "").lower()]

            total = len(all_cookies)
            cookies = all_cookies[offset : offset + limit]

            response: dict[str, Any] = {
                "cookies": cookies,
                "total": total,
                "offset": offset,
                "limit": limit,
                "hasMore": offset + limit < total,
                "target": target["id"],
            }

            # Navigation hints
            if offset > 0 or offset + limit < total:
                response["navigation"] = {}
                if offset > 0:
                    response["navigation"]["prev"] = f"offset={max(0, offset - limit)} limit={limit}"
                if offset + limit < total:
                    response["navigation"]["next"] = f"offset={offset + limit} limit={limit}"

            return response
        except Exception as e:
            raise SmartToolError(
                tool="get_all_cookies",
                action="get",
                reason=str(e),
                suggestion="Ensure browser session is active",
            ) from e


def delete_cookie(
    config: BrowserConfig,
    name: str,
    domain: str | None = None,
    path: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Delete a cookie via CDP Network.deleteCookies.

    Args:
        config: Browser configuration
        name: Cookie name to delete
        domain: Cookie domain (optional)
        path: Cookie path (optional)
        url: URL to match cookie (optional)

    Returns:
        Dict with deleted cookie info and target ID
    """
    with get_session(config) as (session, target):
        try:
            session.send("Network.enable", {})
            params = {"name": name}
            if domain:
                params["domain"] = domain
            if path:
                params["path"] = path
            if url:
                params["url"] = url

            session.send("Network.deleteCookies", params)
            return {"deleted": name, "domain": domain, "path": path, "target": target["id"]}
        except Exception as e:
            raise SmartToolError(
                tool="delete_cookie",
                action="delete",
                reason=str(e),
                suggestion="Check cookie name and domain/path/url parameters",
            ) from e
