"""
Server package for MCP browser automation.

Provides modular tool handling via registry pattern.
"""

from .registry import ToolRegistry, create_default_registry

__all__ = ["ToolRegistry", "create_default_registry"]
