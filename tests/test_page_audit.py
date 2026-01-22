from __future__ import annotations

import pytest


def test_page_audit_compacts_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.page import audit as audit_tool

    cfg = BrowserConfig.from_env()

    monkeypatch.setattr(
        audit_tool,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example", "readyState": "complete"}},
    )

    monkeypatch.setattr(
        audit_tool,
        "get_page_diagnostics",
        lambda _cfg, **k: {
            "diagnostics": {
                "cursor": 123,
                "summary": {"jsErrors": 2, "failedRequests": 1},
                "dialogOpen": False,
            },
            "insights": [{"severity": "error", "kind": "js_error", "message": "boom"}] * 20,
            "target": "tab1",
            "sessionTabId": "tab1",
        },
    )

    monkeypatch.setattr(
        audit_tool,
        "get_page_performance",
        lambda _cfg: {
            "performance": {
                "tier": "tier1",
                "vitals": {"lcp": 1.2, "cls": 0.01, "ttfb": 0.2},
                "timing": {"ttfb_ms": 120, "domContentLoaded_ms": 300, "load_ms": 600},
            }
        },
    )

    monkeypatch.setattr(
        audit_tool,
        "get_page_resources",
        lambda _cfg, **k: {
            "resources": {
                "tier": "tier0",
                "summary": {"total": 100, "failed": 3},
                "items": [{"url": f"https://example.com/r{i}.js", "status": 200, "durationMs": i} for i in range(50)],
            }
        },
    )

    monkeypatch.setattr(
        audit_tool,
        "get_page_locators",
        lambda _cfg, **k: {
            "locators": {
                "tier": "tier0",
                "total": 999,
                "items": [{"kind": "button", "label": f"b{i}", "ref": f"dom:{i}"} for i in range(50)],
            }
        },
    )

    res = audit_tool.get_page_audit(cfg, limit=30, clear=False)
    assert isinstance(res, dict)
    assert isinstance(res.get("audit"), dict)
    assert res.get("cursor") == 123

    audit = res["audit"]
    assert isinstance(audit.get("page"), dict)
    assert audit["page"].get("url") == "https://example.com/"
    assert isinstance(audit.get("summary"), dict)

    top = audit.get("top")
    assert isinstance(top, list)
    assert len(top) <= 5

    perf = audit.get("performance")
    assert isinstance(perf, dict)

    resources = audit.get("resources")
    assert isinstance(resources, dict)
    items = resources.get("items")
    assert isinstance(items, list)
    assert len(items) <= 8

    locs = audit.get("locators")
    assert isinstance(locs, dict)
    loc_items = locs.get("items")
    assert isinstance(loc_items, list)
    assert len(loc_items) <= 10


def test_page_audit_raises_when_snapshot_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.tools.base import SmartToolError
    from mcp_servers.browser.tools.page import audit as audit_tool

    cfg = BrowserConfig.from_env()

    def _boom(*_a, **_k):  # noqa: ANN001
        raise RuntimeError("nope")

    monkeypatch.setattr(audit_tool, "get_page_info", _boom)
    monkeypatch.setattr(audit_tool, "get_page_diagnostics", _boom)
    monkeypatch.setattr(audit_tool, "get_page_performance", _boom)
    monkeypatch.setattr(audit_tool, "get_page_resources", _boom)
    monkeypatch.setattr(audit_tool, "get_page_locators", _boom)

    with pytest.raises(SmartToolError):
        audit_tool.get_page_audit(cfg, limit=10, clear=False)
