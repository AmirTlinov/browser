"""
Smart browser automation tools.

High-level AI-friendly interactions using natural language.
"""

from .ax import (
    click_accessibility,
    click_backend_node,
    drag_backend_node_to_xy,
    drag_backend_nodes,
    drag_xy_to_backend_node,
    hover_backend_node,
    query_ax,
    scroll_backend_node,
    type_backend_node,
)
from .click import click_element
from .form import fill_form, focus_field
from .search import search_page
from .workflow import execute_workflow

__all__ = [
    "click_accessibility",
    "click_backend_node",
    "hover_backend_node",
    "drag_backend_nodes",
    "drag_backend_node_to_xy",
    "drag_xy_to_backend_node",
    "scroll_backend_node",
    "click_element",
    "query_ax",
    "type_backend_node",
    "fill_form",
    "focus_field",
    "search_page",
    "execute_workflow",
]
