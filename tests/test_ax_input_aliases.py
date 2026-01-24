from __future__ import annotations

from contextlib import contextmanager


def test_ax_input_alias_matches_textfield(monkeypatch) -> None:  # noqa: ANN001
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.smart import ax as ax_tool

    class DummySession:
        tab_id = "tab1"

    @contextmanager
    def fake_get_session(_cfg: BrowserConfig, timeout: float = 5.0, **kwargs):  # noqa: ARG001
        yield DummySession(), {"id": "tab1"}

    nodes = [
        {
            "ignored": False,
            "role": {"value": "textField"},
            "name": {"value": "Search"},
            "backendDOMNodeId": 42,
            "properties": [{"name": "focusable", "value": {"value": True}}],
        }
    ]

    monkeypatch.setattr(ax_tool, "get_session", fake_get_session)
    monkeypatch.setattr(ax_tool, "_query_ax_tree", lambda *_a, **_k: None)
    monkeypatch.setattr(ax_tool, "_get_ax_nodes", lambda *_a, **_k: nodes)

    cfg = BrowserConfig.from_env()
    res = ax_tool.query_ax(cfg, role="input", name="Search")
    items = res.get("ax", {}).get("items")
    assert isinstance(items, list) and items
    assert items[0].get("backendDOMNodeId") == 42
