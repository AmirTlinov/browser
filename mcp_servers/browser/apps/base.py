from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..config import BrowserConfig


class AppAdapterError(RuntimeError):
    """App adapter operation failed (AI-friendly error)."""

    def __init__(self, *, app: str, op: str, reason: str, suggestion: str, details: dict[str, Any] | None = None):
        super().__init__(reason)
        self.app = app
        self.op = op
        self.reason = reason
        self.suggestion = suggestion
        self.details = details or {}


class AppAdapter(ABC):
    """Base class for app adapters."""

    name: str

    @abstractmethod
    def match(self, *, url: str) -> bool:
        """Return True if the adapter can operate on the given URL."""

    @abstractmethod
    def invoke(self, *, config: BrowserConfig, op: str, params: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        """Invoke an adapter operation."""
