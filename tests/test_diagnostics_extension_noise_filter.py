from __future__ import annotations


def test_diagnostics_filters_extension_noise() -> None:
    from mcp_servers.browser.tools.page import diagnostics as diag

    snapshot = {
        "console": [
            {"level": "error", "args": ["Cannot redefine property: ethereum"]},
            {"level": "warn", "args": ["chrome-extension://abc/script.js"]},
            {"level": "error", "args": ["Legit app error"]},
        ],
        "errors": [
            {"type": "error", "message": "Cannot redefine property: ethereum", "filename": "https://app.example.com"},
            {"type": "error", "message": "Boom", "filename": "chrome-extension://abc/contentscript.js"},
            {"type": "error", "message": "Real error", "filename": "https://app.example.com/app.js"},
        ],
        "unhandledRejections": [
            {"message": "Cannot redefine property: ethereum", "stack": "chrome-extension://abc/bg.js"},
            {"message": "Real rejection", "stack": "https://app.example.com/app.js"},
        ],
        "network": [],
        "harLite": [],
        "dialogOpen": False,
    }

    cleaned = diag._filter_diagnostics_noise(snapshot)
    assert isinstance(cleaned, dict)
    assert len(cleaned.get("console", [])) == 1
    assert cleaned["console"][0]["args"][0] == "Legit app error"
    assert len(cleaned.get("errors", [])) == 1
    assert cleaned["errors"][0]["message"] == "Real error"
    assert len(cleaned.get("unhandledRejections", [])) == 1
    assert cleaned["unhandledRejections"][0]["message"] == "Real rejection"
