from __future__ import annotations

from dataclasses import dataclass

from .base import AppAdapter


@dataclass
class AppSelection:
    adapter: AppAdapter
    matched_by: str  # "name" | "url"


class AppRegistry:
    """Registry of app adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, AppAdapter] = {}

    def register(self, adapter: AppAdapter) -> None:
        self._adapters[str(adapter.name)] = adapter

    def available(self) -> list[str]:
        return sorted(self._adapters.keys())

    def select(self, *, app: str, url: str) -> AppSelection | None:
        name = str(app or "").strip().lower()
        if name and name != "auto":
            ad = self._adapters.get(name)
            return AppSelection(adapter=ad, matched_by="name") if ad is not None else None

        u = str(url or "").strip()
        if not u:
            # If URL is unavailable (rare: dialog-brick / telemetry gap),
            # fall back to a universal adapter if present.
            ad = self._adapters.get("universal")
            return AppSelection(adapter=ad, matched_by="url") if ad is not None else None
        for ad in self._adapters.values():
            try:
                if ad.match(url=u):
                    return AppSelection(adapter=ad, matched_by="url")
            except Exception:
                continue
        return None


app_registry = AppRegistry()

# Register built-in adapters.
try:
    from .miro import MiroAdapter

    app_registry.register(MiroAdapter())
except Exception:
    # Fail-closed: adapter errors must never break server import.
    pass

try:
    from .universal import UniversalAdapter

    app_registry.register(UniversalAdapter())
except Exception:
    pass
