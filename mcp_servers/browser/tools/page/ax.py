"""Accessibility (AX) query for the current page.

Exposes stable "role" + "name" handles for complex UIs (Miro/Figma/SPA).
"""

from __future__ import annotations

from typing import Any

from ...config import BrowserConfig
from ..smart.ax import query_ax


def get_page_ax(
    config: BrowserConfig,
    *,
    role: str | None = None,
    name: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """Query the accessibility tree by role/name (summary-first)."""
    return query_ax(config, role=role, name=name, offset=offset, limit=limit)
