"""
Page information and context access.

Provides get_page_info and get_page_context functions.
"""

from __future__ import annotations

import time
from typing import Any

from ...config import BrowserConfig
from ...session import session_manager
from ..base import PageContext, SmartToolError, get_session

# Global page context for caching
_page_context: PageContext | None = None


def set_page_context(context: PageContext) -> None:
    """Set the global page context (called by analyze_page)."""
    global _page_context
    _page_context = context


def get_page_context(config: BrowserConfig) -> dict[str, Any]:
    """
    Get cached page context or refresh if stale.

    Use for quick access to page information without re-analyzing.
    Returns the last analyzed page state if still fresh (< 5 seconds old).

    Args:
        config: Browser configuration

    Returns:
        Dictionary with cached or fresh page context
    """
    global _page_context

    if _page_context and not _page_context.is_stale():
        return {
            "cached": True,
            "url": _page_context.url,
            "title": _page_context.title,
            "age_seconds": round(time.time() - _page_context.timestamp, 1),
        }

    # Refresh context - import here to avoid circular dependency
    from .analyze import analyze_page

    result = analyze_page(config)
    return {"cached": False, "overview": result.get("overview"), "target": result.get("target")}


def get_page_info(config: BrowserConfig) -> dict[str, Any]:
    """
    Get current page information (URL, title, scroll position, viewport size).

    Args:
        config: Browser configuration

    Returns:
        Dictionary with pageInfo and target
    """
    # Page info is used for stabilization/proofs; keep it resilient when JS is blocked (dialogs).
    with get_session(config, ensure_diagnostics=False) as (session, target):
        # If a JS dialog is open, Runtime.evaluate is usually blocked until it's handled.
        # Fail over to the CDP-only path immediately to avoid timeouts.
        try:
            tab_id = session.tab_id
            t0 = session_manager.get_telemetry(tab_id) if isinstance(tab_id, str) and tab_id else None
            dialog_open = bool(getattr(t0, "dialog_open", False)) if t0 is not None else False
        except Exception:
            dialog_open = False

        try:
            if not dialog_open:
                js = (
                    "(() => ({"
                    "  url: window.location.href,"
                    "  title: document.title,"
                    "  scrollX: window.scrollX,"
                    "  scrollY: window.scrollY,"
                    "  innerWidth: window.innerWidth,"
                    "  innerHeight: window.innerHeight,"
                    "  documentWidth: document.documentElement.scrollWidth,"
                    "  documentHeight: document.documentElement.scrollHeight"
                    "}))()"
                )
                result = session.eval_js(js)
                if isinstance(result, dict):
                    return {"pageInfo": result, "target": target["id"]}
        except Exception:
            # Fall through to CDP-only fallback (no Runtime.evaluate).
            pass

        # CDP-only fallback (works even when alert/confirm/prompt blocks JS evaluation).
        try:
            nav = session.send("Page.getNavigationHistory")
            url = None
            title = None
            if isinstance(nav, dict):
                idx = nav.get("currentIndex")
                entries = nav.get("entries")
                if isinstance(idx, int) and isinstance(entries, list) and 0 <= idx < len(entries):
                    cur = entries[idx] if isinstance(entries[idx], dict) else None
                    if isinstance(cur, dict):
                        if isinstance(cur.get("url"), str) and cur.get("url"):
                            url = cur.get("url")
                        if isinstance(cur.get("title"), str) and cur.get("title"):
                            title = cur.get("title")
            return {
                "pageInfo": {**({"url": url} if url else {}), **({"title": title} if title else {}), "limited": True},
                "target": target["id"],
            }
        except (OSError, ValueError, KeyError) as e:
            raise SmartToolError(
                tool="get_page_info", action="get", reason=str(e), suggestion="Ensure the page is loaded and responsive"
            ) from e
