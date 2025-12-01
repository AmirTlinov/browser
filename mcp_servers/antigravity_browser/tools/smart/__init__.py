"""
Smart browser automation tools.

High-level AI-friendly interactions using natural language.
"""
from .click import click_element
from .form import fill_form
from .search import search_page
from .workflow import execute_workflow

__all__ = [
    "click_element",
    "fill_form",
    "search_page",
    "execute_workflow",
]
