from __future__ import annotations

import pytest


def test_page_map_bounded_and_actions_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import map as map_tool

    cfg = BrowserConfig.from_env()

    monkeypatch.setattr(
        map_tool,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example", "readyState": "complete"}},
    )

    monkeypatch.setattr(
        map_tool,
        "get_page_diagnostics",
        lambda _cfg, **k: {
            "diagnostics": {"cursor": 123, "summary": {"jsErrors": 2}, "dialogOpen": False},
            "insights": [{"severity": "error", "kind": "js_error", "message": "boom"}] * 20,
            "target": "tab1",
            "sessionTabId": "tab1",
            "cursor": 123,
        },
    )

    monkeypatch.setattr(
        map_tool,
        "get_page_frames",
        lambda _cfg, **k: {"frames": {"summary": {"total": 3, "crossOrigin": 1, "sameOrigin": 2}, "items": []}},
    )

    loc_items = [
        {"kind": "button", "text": "Save", "ref": "aff:111", "actionHint": "click(text=Save)"},
        {
            "kind": "link",
            "text": "Docs",
            "ref": "aff:222",
            "href": "https://example.com/docs?token=abc#frag",
        },
        {"kind": "input", "fillKey": "Email", "ref": "aff:333", "inputType": "email", "formIndex": 0},
    ] + [{"kind": "button", "text": f"B{i}", "ref": f"aff:x{i}"} for i in range(50)]

    monkeypatch.setattr(
        map_tool,
        "get_page_locators",
        lambda _cfg, **k: {"locators": {"tier": "tier1", "total": len(loc_items), "items": loc_items}},
    )

    res = map_tool.get_page_map(cfg, limit=10, clear=False)
    assert isinstance(res, dict)
    assert isinstance(res.get("map"), dict)

    m = res["map"]
    assert m.get("page", {}).get("url") == "https://example.com/"

    actions = m.get("actions")
    assert isinstance(actions, dict)
    items = actions.get("items")
    assert isinstance(items, list)
    assert len(items) <= 10

    assert items[0].get("ref") == "aff:111"
    assert items[0].get("actionHint") == 'act(ref="aff:111")'

    link = next((it for it in items if it.get("kind") == "link"), None)
    assert isinstance(link, dict)
    assert link.get("href") == "https://example.com/docs"

    graph = m.get("graph")
    assert isinstance(graph, dict)
    edges = graph.get("edges")
    assert isinstance(edges, list) and edges
    assert edges[0].get("to") == "https://example.com/docs"
