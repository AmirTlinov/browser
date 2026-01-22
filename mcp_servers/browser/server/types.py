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
    is_error: bool = False
    # Optional raw payload for internal orchestration (e.g., flow exports).
    # Not part of the MCP wire format; only used inside the server process.
    data: Any | None = None

    @classmethod
    def text(cls, text: str) -> ToolResult:
        """Create result with single text content (context-format by default)."""
        from .ai_format import render_ctx_text

        raw = text or ""
        first_non_empty = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        wrapped = raw if first_non_empty in {"[LEGEND]", "[CONTENT]"} else render_ctx_text(raw)
        return cls(content=[ToolContent(type="text", text=wrapped)])

    @classmethod
    def error(
        cls,
        message: str,
        *,
        tool: str | None = None,
        suggestion: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Create error result (AI-first text, not JSON)."""
        from .ai_format import render_ctx_markdown

        payload: dict[str, Any] = {"ok": False, "error": message}
        if tool:
            payload["tool"] = tool
        if suggestion:
            payload["suggestion"] = suggestion
        if details:
            payload["details"] = details
        return cls(content=[ToolContent(type="text", text=render_ctx_markdown(payload))], is_error=True, data=payload)

    @classmethod
    def json(cls, data: Any) -> ToolResult:
        """Create result with AI-first context-format text content (not JSON)."""
        from .ai_format import render_ctx_markdown

        return cls(content=[ToolContent(type="text", text=render_ctx_markdown(data))], data=data)

    @classmethod
    def image(cls, data_b64: str, mime_type: str = "image/png") -> ToolResult:
        """Create result with single image content. Falls back to text if data is empty."""
        if not data_b64:
            return cls.error("Screenshot data is empty")
        return cls(content=[ToolContent(type="image", data=data_b64, mime_type=mime_type)])

    @classmethod
    def with_image(cls, text: str, data_b64: str, mime_type: str = "image/png", data: Any | None = None) -> ToolResult:
        """Create result with text and image content. Omits image if data is empty."""
        if not data_b64:
            raw = text or ""
            first_non_empty = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
            if first_non_empty not in {"[LEGEND]", "[CONTENT]"}:
                from .ai_format import render_ctx_text

                raw = render_ctx_text(raw)
            return cls(content=[ToolContent(type="text", text=raw)], data=data)
        raw = text or ""
        first_non_empty = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        if first_non_empty not in {"[LEGEND]", "[CONTENT]"}:
            from .ai_format import render_ctx_text

            raw = render_ctx_text(raw)
        return cls(
            content=[
                ToolContent(type="text", text=raw),
                ToolContent(type="image", data=data_b64, mime_type=mime_type),
            ],
            data=data,
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
