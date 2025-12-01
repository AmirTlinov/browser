"""
Type definitions for MCP server responses and handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..config import BrowserConfig
    from ..launcher import BrowserLauncher


@dataclass(slots=True)
class ToolContent:
    """Single content item in tool response."""

    type: str  # "text" or "image"
    text: str | None = None
    data: str | None = None  # base64 for images
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to MCP content format."""
        if self.type == "image":
            return {"type": "image", "data": self.data, "mimeType": self.mime_type}
        return {"type": "text", "text": self.text}


@dataclass(slots=True)
class ToolResult:
    """Result of a tool execution."""

    content: list[ToolContent] = field(default_factory=list)

    @classmethod
    def text(cls, text: str) -> ToolResult:
        """Create result with single text content."""
        return cls(content=[ToolContent(type="text", text=text)])

    @classmethod
    def json(cls, data: Any) -> ToolResult:
        """Create result with JSON-serialized text content."""
        import json

        return cls.text(json.dumps(data, ensure_ascii=False))

    @classmethod
    def image(cls, data_b64: str, mime_type: str = "image/png") -> ToolResult:
        """Create result with single image content."""
        return cls(content=[ToolContent(type="image", data=data_b64, mime_type=mime_type)])

    @classmethod
    def with_image(cls, text: str, data_b64: str, mime_type: str = "image/png") -> ToolResult:
        """Create result with text and image content."""
        return cls(
            content=[
                ToolContent(type="text", text=text),
                ToolContent(type="image", data=data_b64, mime_type=mime_type),
            ]
        )

    def to_content_list(self) -> list[dict[str, Any]]:
        """Convert to MCP content list format."""
        return [c.to_dict() for c in self.content]


class ToolHandler(Protocol):
    """Protocol for tool handler functions."""

    def __call__(
        self,
        config: BrowserConfig,
        launcher: BrowserLauncher,
        arguments: dict[str, Any],
    ) -> ToolResult: ...


@dataclass(slots=True, frozen=True)
class ToolSpec:
    """Specification for a registered tool."""

    name: str
    handler: Callable[[BrowserConfig, BrowserLauncher, dict[str, Any]], ToolResult]
    requires_browser: bool = True  # Whether to call ensure_running before handler
