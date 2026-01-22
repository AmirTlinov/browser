from __future__ import annotations


def test_diagnostics_insights_detects_cors() -> None:
    from mcp_servers.browser.tools.page import diagnostics as diag

    snapshot = {
        "console": [
            {
                "level": "error",
                "args": [
                    "Access to fetch at 'https://api.example.com/v1/cart' from origin 'https://app.example.com' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested resource."
                ],
            }
        ],
        "errors": [],
        "unhandledRejections": [],
        "network": [],
        "harLite": [],
        "dialogOpen": False,
    }

    insights = diag._derive_insights(snapshot)
    assert any(i.get("kind") == "cors" for i in insights)


def test_diagnostics_insights_detects_blocked_by_client() -> None:
    from mcp_servers.browser.tools.page import diagnostics as diag

    snapshot = {
        "console": [],
        "errors": [],
        "unhandledRejections": [],
        "network": [
            {
                "ts": 1,
                "url": "https://example.com/ads.js",
                "method": "GET",
                "status": None,
                "errorText": "net::ERR_BLOCKED_BY_CLIENT",
                "blockedReason": "blockedByClient",
            }
        ],
        "harLite": [],
        "dialogOpen": False,
    }

    insights = diag._derive_insights(snapshot)
    assert any(i.get("kind") == "blocked_by_client" for i in insights)


def test_diagnostics_insights_detects_auth_failures_from_harlite() -> None:
    from mcp_servers.browser.tools.page import diagnostics as diag

    snapshot = {
        "console": [],
        "errors": [],
        "unhandledRejections": [],
        "network": [],
        "harLite": [
            {
                "ts": 1,
                "url": "https://api.example.com/v1/cart",
                "method": "GET",
                "status": 401,
                "ok": False,
                "type": "XHR",
            }
        ],
        "dialogOpen": False,
    }

    insights = diag._derive_insights(snapshot)
    assert any(i.get("kind") == "auth" for i in insights)
