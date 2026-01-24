from __future__ import annotations


def test_redact_url_keeps_normal_query() -> None:
    from mcp_servers.browser.server.redaction import redact_url

    url = "https://example.com/search?q=hello&sort=asc"
    assert redact_url(url) == url


def test_redact_url_redacts_sensitive_query_param_but_keeps_others() -> None:
    from mcp_servers.browser.server.redaction import redact_url

    url = "https://example.com/?token=abc&q=hello"
    out = redact_url(url)
    assert "q=hello" in out
    assert "token=abc" not in out
    assert "token=" in out and "redacted" in out


def test_redact_url_redacts_oauth_fragment_like_query_string() -> None:
    from mcp_servers.browser.server.redaction import redact_url

    url = "https://example.com/callback#access_token=abc&state=1"
    out = redact_url(url)
    assert "state=1" in out
    assert "access_token=abc" not in out
    assert "redacted" in out


def test_runbook_sanitizes_sensitive_url_params_but_not_normal_queries() -> None:
    from mcp_servers.browser.runbook import sanitize_runbook_steps

    safe_steps = [{"navigate": {"url": "https://example.com/search?q=hello&sort=asc"}}]
    safe_out, safe_redacted = sanitize_runbook_steps(safe_steps)
    assert safe_redacted == 0
    assert safe_out[0]["navigate"]["url"] == safe_steps[0]["navigate"]["url"]

    unsafe_steps = [{"navigate": {"url": "https://example.com/?token=abc&q=hello"}}]
    unsafe_out, unsafe_redacted = sanitize_runbook_steps(unsafe_steps)
    assert unsafe_redacted >= 1
    red_url = unsafe_out[0]["navigate"]["url"]
    assert "q=hello" in red_url
    assert "token=abc" not in red_url
    assert "redacted" in red_url


def test_redact_url_does_not_redact_author_like_keys() -> None:
    from mcp_servers.browser.server.redaction import redact_url

    url = "https://example.com/?author=John&auth=abc&q=hello"
    out = redact_url(url)
    assert "author=John" in out
    assert "q=hello" in out
    assert "auth=abc" not in out
    assert "auth=" in out and "redacted" in out
