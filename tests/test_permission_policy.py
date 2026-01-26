from __future__ import annotations

from mcp_servers.browser.permissions import PermissionPolicy, apply_permission_policy


class _DummySession:
    def __init__(self, *, fail_set: bool = False) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self._fail_set = fail_set

    def send(self, method: str, params: dict | None = None) -> dict:
        if self._fail_set and method == "Browser.setPermission":
            raise RuntimeError("setPermission not supported")
        self.calls.append((method, params))
        return {}


def test_permission_policy_settings_match_and_precedence() -> None:
    policy = PermissionPolicy(
        default="deny",
        default_permissions=["notifications", "geolocation"],
        allow={"example.com": ["notifications"]},
        deny={"https://example.com": ["geolocation"]},
    )
    settings = policy.settings_for_origin("https://example.com", "example.com")
    assert settings["notifications"] == "granted"
    assert settings["geolocation"] == "denied"

    sub_settings = policy.settings_for_origin("https://sub.example.com", "sub.example.com")
    assert sub_settings["notifications"] == "granted"


def test_permission_policy_apply_sets_permissions() -> None:
    session = _DummySession()
    policy = PermissionPolicy(
        default="deny",
        default_permissions=["notifications"],
        allow={"https://example.com": ["geolocation"]},
    )
    result = apply_permission_policy(session, policy, "https://example.com/path")
    assert result.get("ok") is True
    methods = [m for m, _ in session.calls]
    assert "Browser.setPermission" in methods


def test_permission_policy_apply_fallback_grant() -> None:
    session = _DummySession(fail_set=True)
    policy = PermissionPolicy(
        default="prompt",
        default_permissions=[],
        allow={"https://example.com": ["notifications"]},
    )
    result = apply_permission_policy(session, policy, "https://example.com")
    assert result.get("ok") is True
    methods = [m for m, _ in session.calls]
    assert "Browser.grantPermissions" in methods
