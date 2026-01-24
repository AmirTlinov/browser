from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_auto_expand_page_clicks_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import auto_expand as auto_expand_mod

    cfg = BrowserConfig.from_env()
    calls = {"js": 0}

    class DummySession:
        def eval_js(self, _expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            calls["js"] += 1
            if calls["js"] == 1:
                return {"clicked": 2, "total": 2}
            return {"clicked": 0, "total": 0}

    @contextmanager
    def fake_get_session(_cfg):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(auto_expand_mod, "get_session", fake_get_session)
    monkeypatch.setattr(auto_expand_mod.time, "sleep", lambda *_a, **_k: None)

    result = auto_expand_mod.auto_expand_page(cfg, {"max_iters": 3, "settle_ms": 0})
    assert result["ok"] is True
    assert result["clicked"] == 2
    assert calls["js"] == 2


def test_auto_expand_page_rejects_non_object() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import auto_expand as auto_expand_mod

    cfg = BrowserConfig.from_env()
    result = auto_expand_mod.auto_expand_page(cfg, "nope")  # type: ignore[arg-type]
    assert result["ok"] is False
