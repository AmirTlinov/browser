"""
Content extraction tool with pagination support.

Extract structured content like paragraphs, tables, links, headings, images.
"""

from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..base import SmartToolError, get_session
from .js_extract import build_extract_js

# Default pagination limits
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def extract_content(
    config: BrowserConfig,
    content_type: str = "overview",
    selector: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    table_index: int | None = None,
) -> dict[str, Any]:
    """
    Extract structured content from the page with pagination.

    OVERVIEW MODE (content_type="overview", default):
    Returns content structure summary:
    - Counts of paragraphs, tables, links, headings, images
    - Preview of title and first paragraph
    - Hints for getting detailed content

    DETAIL MODES with pagination:
    - content_type="main": Main text paragraphs (offset/limit)
    - content_type="table": List of tables with metadata
    - content_type="table" + table_index=N: Rows of table N (offset/limit)
    - content_type="links": All links (offset/limit)
    - content_type="headings": Document outline
    - content_type="images": Images with metadata (offset/limit)

    Args:
        config: Browser configuration
        content_type: What to extract
        selector: Optional CSS selector to limit scope
        offset: Starting index for paginated results
        limit: Maximum items (default 10, max 50)
        table_index: Specific table when content_type="table"

    Returns:
        Dictionary with content data and navigation hints

    Examples:
        # Get content overview
        extract_content()

        # Get paragraphs 10-20
        extract_content(content_type="main", offset=10, limit=10)

        # Get rows from first table
        extract_content(content_type="table", table_index=0, offset=0, limit=20)
    """
    valid_types = ["overview", "main", "table", "links", "headings", "images"]
    if content_type not in valid_types:
        raise SmartToolError(
            tool="extract_content",
            action="validate",
            reason=f"Invalid content_type: {content_type}",
            suggestion=f"Use one of: {', '.join(valid_types)}",
        )

    limit = min(limit, MAX_LIMIT)

    with get_session(config) as (session, target):
        js = build_extract_js(content_type, selector, offset, limit, table_index)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="extract_content",
                action="evaluate",
                reason="Extraction returned null",
                suggestion="Check page has loaded completely",
            )

        if result.get("error"):
            raise SmartToolError(
                tool="extract_content",
                action="extract",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check parameters"),
            )

        result["target"] = target["id"]
        return result
