from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_auto_scroll_page_scrolls_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import auto_scroll as auto_scroll_mod

    cfg = BrowserConfig.from_env()
    calls = {"scroll": 0, "js": 0}

    class DummySession:
        def eval_js(self, _expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            calls["js"] += 1
            return calls["js"] >= 2

        def scroll(self, *_args, **_kwargs):  # noqa: ANN001,ARG002
            calls["scroll"] += 1

    @contextmanager
    def fake_get_session(_cfg):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(auto_scroll_mod, "get_session", fake_get_session)
    monkeypatch.setattr(auto_scroll_mod.time, "sleep", lambda *_a, **_k: None)

    result = auto_scroll_mod.auto_scroll_page(cfg, {"max_iters": 3, "settle_ms": 0})
    assert result["ok"] is True
    assert calls["scroll"] == 1


def test_auto_scroll_page_rejects_bad_direction() -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import auto_scroll as auto_scroll_mod

    cfg = BrowserConfig.from_env()
    result = auto_scroll_mod.auto_scroll_page(cfg, {"direction": "diagonal"})
    assert result["ok"] is False


def test_auto_scroll_page_scrolls_container(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import auto_scroll as auto_scroll_mod

    cfg = BrowserConfig.from_env()
    calls = {"scroll_js": 0, "check_js": 0}

    class DummySession:
        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "scrollBy" in expression:
                calls["scroll_js"] += 1
                return {"scrollTop": 100, "scrollHeight": 200, "clientHeight": 100}
            calls["check_js"] += 1
            return calls["check_js"] >= 2

        def scroll(self, *_args, **_kwargs):  # noqa: ANN001,ARG002
            raise AssertionError("page scroll should not be used when container_selector is set")

    @contextmanager
    def fake_get_session(_cfg):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1"}

    monkeypatch.setattr(auto_scroll_mod, "get_session", fake_get_session)
    monkeypatch.setattr(auto_scroll_mod.time, "sleep", lambda *_a, **_k: None)

    result = auto_scroll_mod.auto_scroll_page(cfg, {"max_iters": 3, "settle_ms": 0, "container_selector": ".feed"})
    assert result["ok"] is True
    assert calls["scroll_js"] >= 1
