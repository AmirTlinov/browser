"""
Page analysis tool with Overview + Detail pattern.

Primary tool for understanding page structure.
"""

from __future__ import annotations

import time
from typing import Any

from ...config import BrowserConfig
from ..base import PageContext, SmartToolError, get_session
from .info import set_page_context
from .js_analyze import build_analyze_js

# Default pagination limits
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def analyze_page(
    config: BrowserConfig,
    detail: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    form_index: int | None = None,
    include_content: bool = False,
) -> dict[str, Any]:
    """
    Analyze the current page with Overview + Detail pattern.

    OVERVIEW MODE (detail=None, default):
    Returns compact summary optimized for AI context:
    - Page metadata (URL, title, pageType)
    - Counts of all elements (forms, links, buttons, inputs)
    - Preview samples (first few items of each type)
    - Suggested actions based on page type
    - Hints showing how to get more details

    DETAIL MODES:
    - detail="forms": List all forms with field counts
    - detail="forms" + form_index=N: Full details of form N with all fields
    - detail="links": Paginated list of links (use offset/limit)
    - detail="buttons": All buttons on page
    - detail="inputs": Standalone inputs (not in forms)
    - detail="content": Main page content (paginated)

    Args:
        config: Browser configuration
        detail: Section to get details for (None for overview)
        offset: Starting index for paginated results
        limit: Maximum items to return (default 10, max 50)
        form_index: Specific form index when detail="forms"
        include_content: Include content preview in overview (default False)

    Returns:
        Dictionary with overview or detail data, plus navigation hints

    Examples:
        # Get page overview
        analyze_page()

        # Get details of first form
        analyze_page(detail="forms", form_index=0)

        # Get links 20-30
        analyze_page(detail="links", offset=20, limit=10)
    """
    # Validate parameters
    valid_details = [None, "forms", "links", "buttons", "inputs", "content"]
    if detail not in valid_details:
        raise SmartToolError(
            tool="analyze_page",
            action="validate",
            reason=f"Invalid detail: {detail}",
            suggestion=f"Use one of: {', '.join(str(d) for d in valid_details)}",
        )

    limit = min(limit, MAX_LIMIT)

    with get_session(config) as (session, target):
        js = build_analyze_js(detail, offset, limit, form_index, include_content)
        result = session.eval_js(js)

        if not result:
            raise SmartToolError(
                tool="analyze_page",
                action="evaluate",
                reason="Page analysis returned null",
                suggestion="Page may still be loading. Try wait_for(condition='load') first",
            )

        if result.get("error"):
            raise SmartToolError(
                tool="analyze_page",
                action="analyze",
                reason=result.get("reason", "Unknown error"),
                suggestion=result.get("suggestion", "Check page state"),
            )

        # Cache context for overview mode
        if detail is None and "overview" in result:
            overview = result["overview"]
            set_page_context(
                PageContext(
                    url=overview.get("url", ""),
                    title=overview.get("title", ""),
                    forms=[],
                    links=[],
                    buttons=[],
                    inputs=[],
                    text_content="",
                    timestamp=time.time(),
                )
            )

        result["target"] = target["id"]
        return result
