"""
Page analysis and content extraction tools.

Provides:
- analyze_page: Primary tool for understanding page structure
- extract_content: Extract structured content with pagination
- wait_for: Wait for various conditions
- get_page_context: Quick access to cached page state
- get_page_info: Current page metadata
"""

from .analyze import analyze_page
from .auto_expand import auto_expand_page
from .auto_scroll import auto_scroll_page
from .audit import get_page_audit
from .ax import get_page_ax
from .diagnostics import get_page_diagnostics
from .extract import extract_content
from .frames import get_page_frames
from .graph import get_page_graph
from .info import get_page_context, get_page_info
from .locators import get_page_locators
from .map import get_page_map
from .performance import get_page_performance
from .resources import get_page_resources
from .triage import get_page_triage
from .wait import wait_for

__all__ = [
    "analyze_page",
    "auto_expand_page",
    "auto_scroll_page",
    "get_page_audit",
    "get_page_ax",
    "get_page_diagnostics",
    "get_page_frames",
    "get_page_graph",
    "get_page_locators",
    "get_page_map",
    "get_page_performance",
    "get_page_resources",
    "get_page_triage",
    "extract_content",
    "wait_for",
    "get_page_context",
    "get_page_info",
]
