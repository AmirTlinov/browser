from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _DummyGateway:
    connected: bool = False
    role: str = "leader"

    def is_connected(self) -> bool:
        return self.connected

    def status(self) -> dict:
        return {"connected": self.connected, "role": self.role}


def test_extension_auto_heal_disabled_by_env(monkeypatch) -> None:
    from mcp_servers.browser.extension_auto_heal import ExtensionAutoHealer

    monkeypatch.setenv("MCP_EXTENSION_AUTO_HEAL", "0")
    healer = ExtensionAutoHealer(_DummyGateway())
    assert healer.start() is False


def test_extension_auto_heal_disabled_by_legacy_watch_env(monkeypatch) -> None:
    from mcp_servers.browser.extension_auto_heal import ExtensionAutoHealer

    monkeypatch.delenv("MCP_EXTENSION_AUTO_HEAL", raising=False)
    monkeypatch.setenv("MCP_EXTENSION_HEALTH_WATCH", "0")
    healer = ExtensionAutoHealer(_DummyGateway())
    assert healer.start() is False


def test_extension_auto_heal_should_attempt_install() -> None:
    from mcp_servers.browser.extension_auto_heal import ExtensionAutoHealer

    assert ExtensionAutoHealer.should_attempt_install(status="native_host_missing") is True
    assert ExtensionAutoHealer.should_attempt_install(status="native_host_misconfigured") is True
    assert ExtensionAutoHealer.should_attempt_install(status="waiting_for_extension") is False
