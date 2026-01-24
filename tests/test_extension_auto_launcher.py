from __future__ import annotations


def test_extension_auto_launch_plan(monkeypatch, tmp_path) -> None:
    from mcp_servers.browser.extension_auto_launcher import build_extension_launch_plan

    monkeypatch.setenv("MCP_BROWSER_BINARY", "/bin/true")
    monkeypatch.setenv("MCP_EXTENSION_PROFILE", str(tmp_path / "profile"))

    plan = build_extension_launch_plan()

    assert plan.command[0] == "/bin/true"
    assert any(flag.startswith("--user-data-dir=") for flag in plan.command)
    assert any(flag.startswith("--load-extension=") for flag in plan.command)
    assert any(flag.startswith("--disable-extensions-except=") for flag in plan.command)
