from __future__ import annotations

from contextlib import contextmanager

import pytest


def _install_hermetic_flow_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared mocks so flow/run tests don't require a real browser."""
    from mcp_servers.browser.session import session_manager

    session_manager.recover_reset()

    class DummySession:
        tab_id = "tab1"
        tab_url = "about:blank"

        def eval_js(self, expression: str, *, timeout: float | None = None):  # noqa: ANN001,ARG002
            if "Date.now" in expression:
                return 1_000_000
            return None

        def close(self) -> None:
            return

    @contextmanager
    def fake_shared_session(_cfg, timeout: float = 5.0):  # noqa: ANN001,ARG001
        yield DummySession(), {"id": "tab1", "webSocketDebuggerUrl": "ws://dummy", "url": "about:blank"}

    monkeypatch.setattr(session_manager, "shared_session", fake_shared_session)
    monkeypatch.setattr(session_manager, "ensure_telemetry", lambda _sess: {"enabled": True})
    monkeypatch.setattr(session_manager, "get_telemetry", lambda _tab_id: None)
    monkeypatch.setattr(
        session_manager,
        "tier0_snapshot",
        lambda *a, **k: {"cursor": 1_000_000, "summary": {}, "harLite": [], "network": [], "dialogOpen": False},
    )
    session_manager._session_tab_id = "tab1"


def test_flow_assert_url_contains_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/path", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"assert": {"url": "example.com"}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "assert"
    assert steps[0].get("ok") is True
    assert called == []


def test_flow_assert_url_contains_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/path", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {"assert": {"url": "not-present"}},
                {"click": {"text": "ShouldNotRun"}},
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "assert"
    assert steps[0].get("ok") is False
    assert "assertion failed" in str(steps[0].get("error", "")).lower()
    assert "click" not in called


def test_flow_when_then_branch_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/target", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name in {"click", "navigate", "wait"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "when": {
                        "if": {"url": "example.com/target"},
                        "then": [{"click": {"text": "Login"}}],
                        "else": [{"navigate": {"url": "https://example.com/login"}}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "when"
    assert steps[0].get("branch") == "then"
    assert "click" in called
    assert "navigate" not in called


def test_flow_when_else_branch_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/other", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name in {"click", "navigate", "wait"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "when": {
                        "if": {"url": "example.com/target"},
                        "then": [{"click": {"text": "Login"}}],
                        "else": [{"navigate": {"url": "https://example.com/login"}}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "when"
    assert steps[0].get("branch") == "else"
    assert "navigate" in called
    assert "click" not in called


def test_flow_timeout_profile_slow_sets_default_condition_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """timeout_profile should affect default internal wait timeouts (repeat/when)."""
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(tools, "get_page_info", lambda _cfg: {"pageInfo": {"url": "about:blank", "title": ""}})

    registry = create_default_registry()
    seen: list[dict] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "wait":
            seen.append({"name": name, "args": arguments})
            return ToolResult.json({"found": False})
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 1,
                        "until": {"selector": "#missing"},
                        "steps": [{"click": {"text": "noop"}, "optional": True}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 5.0,
            "timeout_profile": "slow",
        },
    )

    assert not res.is_error
    assert seen, "expected at least one wait() call"
    first = seen[0]["args"]
    assert first.get("timeout") == pytest.approx(0.8, rel=0.01)


def test_flow_timeout_profile_slow_sets_repeat_default_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """slow profile should default repeat backoff/jitter (deterministic; reduces flake)."""
    import time

    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(float(s)))

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"repeat": {"max_iters": 2, "steps": [{"click": {"text": "noop"}, "optional": True}]}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 5.0,
            "timeout_profile": "slow",
        },
    )

    assert not res.is_error
    assert slept, "expected a default backoff sleep in slow profile"
    # slow-profile default backoff: 0.2s with ±15% deterministic jitter
    assert 0.17 <= slept[0] <= 0.23


def test_flow_repeat_backoff_jitter_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    import copy
    import time

    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()

    args = {
        "steps": [
            {
                "repeat": {
                    "max_iters": 2,
                    "steps": [{"click": {"text": "noop"}, "optional": True}],
                    "backoff_s": 1.0,
                    "backoff_factor": 1.0,
                    "backoff_max_s": 2.0,
                    "backoff_jitter": 0.2,
                    "jitter_seed": 123,
                }
            }
        ],
        "final": "none",
        "stop_on_error": True,
        "auto_recover": False,
        "step_proof": False,
        "action_timeout": 10.0,
    }

    res1 = handler(cfg, launcher=None, args=copy.deepcopy(args))
    res2 = handler(cfg, launcher=None, args=copy.deepcopy(args))

    def pick_sleep(res: ToolResult) -> float:
        assert not res.is_error
        assert isinstance(res.data, dict)
        steps = res.data.get("steps")
        assert isinstance(steps, list)
        for st in steps:
            if isinstance(st, dict) and st.get("tool") == "repeat" and isinstance(st.get("sleep_s"), (int, float)):
                return float(st["sleep_s"])
        raise AssertionError("expected repeat sleep_s in step summaries")

    s1 = pick_sleep(res1)
    s2 = pick_sleep(res2)

    assert s1 == pytest.approx(s2, rel=0.0, abs=0.0)
    assert 0.8 <= s1 <= 1.2
    assert s1 != pytest.approx(1.0, rel=0.0, abs=0.0)


def test_flow_macro_dry_run_does_not_dispatch_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "login_basic",
                        "args": {"username": "user@example.com", "password": "pass"},
                        "dry_run": True,
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "macro"
    assert steps[0].get("dry_run") is True
    assert called == []


def test_flow_macro_include_memory_steps_expands_and_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    session_manager.set_policy("permissive")

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    cfg = BrowserConfig.from_env()

    browser_handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    res_set = browser_handler(
        cfg,
        launcher=None,
        args={
            "action": "memory",
            "memory_action": "set",
            "key": "runbook_login",
            "value": [
                {"navigate": {"url": "https://example.com/login"}},
                {"form": {"fill": {"email": "{{param:email}}", "password": "{{mem:pwd}}"}, "submit": True}},
            ],
        },
    )
    assert not res_set.is_error

    res_pwd = browser_handler(
        cfg,
        launcher=None,
        args={"action": "memory", "memory_action": "set", "key": "pwd", "value": "secret"},
    )
    assert not res_pwd.is_error

    called: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append((name, arguments))
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = flow_handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "include_memory_steps",
                        "args": {"memory_key": "runbook_login", "params": {"email": "user@example.com"}},
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert [c[0] for c in called] == ["navigate", "form"]
    assert called[1][1].get("fill", {}).get("email") == "user@example.com"
    assert called[1][1].get("fill", {}).get("password") == "secret"


def test_flow_macro_include_memory_steps_missing_param_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    session_manager.set_policy("permissive")

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    cfg = BrowserConfig.from_env()

    browser_handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    res_set = browser_handler(
        cfg,
        launcher=None,
        args={
            "action": "memory",
            "memory_action": "set",
            "key": "runbook_login",
            "value": [{"navigate": {"url": "https://example.com/{{param:path}}"}}],
        },
    )
    assert not res_set.is_error

    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = flow_handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "include_memory_steps", "args": {"memory_key": "runbook_login"}}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "macro"
    assert steps[0].get("ok") is False
    assert "param" in str(steps[0].get("error", "")).lower()


def test_flow_macro_include_memory_steps_refuses_sensitive_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    session_manager.set_policy("permissive")

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    cfg = BrowserConfig.from_env()

    browser_handler, _requires_browser = registry.get("browser")  # type: ignore[assignment]
    res_set = browser_handler(
        cfg,
        launcher=None,
        args={
            "action": "memory",
            "memory_action": "set",
            "key": "pwd",
            "value": [{"navigate": {"url": "https://example.com/login"}}],
        },
    )
    assert not res_set.is_error

    flow_handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    res = flow_handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "include_memory_steps", "args": {"memory_key": "pwd"}}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "macro"
    assert steps[0].get("ok") is False
    assert "sensitive" in str(steps[0].get("error", "")).lower()


def test_flow_repeat_runs_fixed_times(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name in {"click"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"repeat": {"max_iters": 3, "steps": [{"click": {"text": "Next"}}]}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called == ["click", "click", "click"]


def test_flow_repeat_until_condition_stops_early(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    current_url = {"value": "https://example.com/start"}

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": current_url["value"], "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name == "navigate":
            url = arguments.get("url")
            if isinstance(url, str):
                current_url["value"] = url
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 5,
                        "until": {"url": "/done"},
                        "timeout_s": 0.1,
                        "steps": [{"navigate": {"url": "https://example.com/done"}}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called == ["navigate"]


def test_flow_repeat_until_exhausted_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/start", "title": "Example"}},
    )

    registry = create_default_registry()

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name in {"click"}:
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 2,
                        "until": {"url": "/done"},
                        "timeout_s": 0.1,
                        "steps": [{"click": {"text": "Try"}}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    steps = res.data.get("steps")
    assert isinstance(steps, list) and steps
    assert any(s.get("tool") == "repeat" and s.get("ok") is False for s in steps)


def test_flow_repeat_step_safe_mem_interpolation(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult
    from mcp_servers.browser.session import session_manager

    _install_hermetic_flow_mocks(monkeypatch)
    session_manager.set_policy("permissive")

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append((name, arguments))
        if name == "browser":
            # Minimal simulation of browser(action="memory", memory_action="set", ...).
            if arguments.get("action") == "memory" and arguments.get("memory_action") == "set":
                key = arguments.get("key")
                session_manager.memory_set(key=str(key), value=arguments.get("value"), max_bytes=20000, max_keys=200)
                return ToolResult.json({"ok": True})
            return ToolResult.error("unexpected browser action", tool="browser")
        if name == "type":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 1,
                        "steps": [
                            {"browser": {"action": "memory", "memory_action": "set", "key": "k", "value": "v"}},
                            {"type": {"text": "{{mem:k}}"}},
                        ],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert any(name == "type" and args.get("text") == "v" for name, args in called)


def test_flow_macro_scroll_until_visible_scrolls_until_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []
    wait_calls = {"count": 0}

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, arguments))
        if name == "wait":
            wait_calls["count"] += 1
            # First condition check fails, second succeeds.
            found = wait_calls["count"] >= 2
            return ToolResult.json({"found": found, "waited_for": "element", "duration_ms": 1})
        if name == "scroll":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "scroll_until_visible", "args": {"selector": "#target", "max_iters": 5}}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    # repeat checks condition, scrolls once, then checks condition again and stops.
    assert [c[0] for c in calls] == ["wait", "scroll", "wait"]


def test_flow_macro_scroll_until_visible_passes_backoff_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    sleeps: list[float] = []
    wait_calls = {"count": 0}

    def fake_sleep(s: float) -> None:
        sleeps.append(float(s))

    monkeypatch.setattr(time, "sleep", fake_sleep)

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        if name == "wait":
            wait_calls["count"] += 1
            # Force one retry so repeat sleeps once (iter_done>0).
            found = wait_calls["count"] >= 3
            return ToolResult.json({"found": found})
        if name == "scroll":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "scroll_until_visible",
                        "args": {
                            "selector": "#target",
                            "max_iters": 5,
                            "backoff_s": 1.0,
                            "backoff_factor": 1.0,
                            "backoff_max_s": 2.0,
                            "backoff_jitter": 0.2,
                            "jitter_seed": 123,
                        },
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 10.0,
        },
    )

    assert not res.is_error
    assert sleeps, "expected repeat sleep_s from macro-expanded repeat"
    assert 0.8 <= sleeps[0] <= 1.2
    assert sleeps[0] != pytest.approx(1.0, rel=0.0, abs=0.0)


def test_flow_repeat_condition_js_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, arguments))
        if name == "js":
            return ToolResult.json({"result": True})
        if name == "scroll":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"repeat": {"max_iters": 3, "until": {"js": "1"}, "steps": [{"scroll": {"direction": "down"}}]}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 2.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert [c[0] for c in calls] == ["js"]


def test_flow_macro_scroll_to_end_uses_js_condition(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []
    js_calls = {"count": 0}

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, arguments))
        if name == "js":
            js_calls["count"] += 1
            return ToolResult.json({"result": js_calls["count"] >= 2})
        if name == "scroll":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "scroll_to_end", "args": {"max_iters": 4}}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert [c[0] for c in calls] == ["js", "scroll", "js"]


def test_flow_macro_paginate_next_clicks_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []
    js_calls = {"count": 0}

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, arguments))
        if name == "js":
            js_calls["count"] += 1
            return ToolResult.json({"result": js_calls["count"] >= 2})
        if name == "click":
            return ToolResult.json({"success": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "paginate_next",
                        "args": {"next_selector": "#next", "dismiss_overlays": False, "max_iters": 3},
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert [c[0] for c in calls] == ["js", "click", "js"]


def test_flow_macro_auto_expand_clicks_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    calls: list[tuple[str, dict]] = []
    js_calls = {"count": 0}

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        calls.append((name, arguments))
        if name == "js":
            js_calls["count"] += 1
            # 1) repeat condition: false, 2) click batch, 3) condition: true
            if js_calls["count"] == 1:
                return ToolResult.json({"result": False})
            if js_calls["count"] == 2:
                return ToolResult.json({"result": {"clicked": 2, "total": 3}})
            return ToolResult.json({"result": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [{"macro": {"name": "auto_expand", "args": {"max_iters": 3}}}],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert [c[0] for c in calls] == ["js", "js", "js"]


def test_flow_macro_retry_click_retries_until_url_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    current_url = {"value": "https://example.com/start"}

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": current_url["value"], "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name == "click":
            current_url["value"] = "https://example.com/done"
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "retry_click",
                        "args": {
                            "dismiss_overlays": False,
                            "max_iters": 5,
                            "click": {"text": "Continue"},
                            "until": {"url": "/done"},
                        },
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called == ["click"]


def test_flow_repeat_backoff_sleeps_between_iters(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import time

    sleeps: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(float(s)))

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 3,
                        "steps": [{"click": {"text": "Next"}}],
                        "backoff_s": 0.1,
                        "backoff_factor": 2.0,
                        "backoff_max_s": 0.25,
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called == ["click", "click", "click"]
    assert sleeps == [pytest.approx(0.1), pytest.approx(0.2)]


def test_flow_repeat_max_time_s_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import time

    t = {"i": 0}

    def fake_monotonic() -> float:
        t["i"] += 1
        # First call sets t0; second call produces elapsed > max_time_s.
        return 0.0 if t["i"] == 1 else 2.0

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "repeat": {
                        "max_iters": 3,
                        "max_time_s": 1.0,
                        "steps": [{"click": {"text": "ShouldNotRun"}}],
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 3.0,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is False
    assert called == []


def test_flow_macro_goto_if_needed_skips_when_already_on_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/target", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        return ToolResult.json({"ok": True})

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "goto_if_needed",
                        "args": {"url_contains": "example.com/target", "url": "https://example.com/target"},
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert "navigate" not in called


def test_flow_macro_goto_if_needed_navigates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/other", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[tuple[str, dict]] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append((name, dict(arguments or {})))
        if name == "navigate":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "goto_if_needed",
                        "args": {"url_contains": "example.com/target", "url": "https://example.com/target"},
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called and called[0][0] == "navigate"
    assert called[0][1].get("url") == "https://example.com/target"


def test_flow_macro_assert_then_runs_then_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_servers.browser.config import BrowserConfig
    from mcp_servers.browser.server.registry import create_default_registry
    from mcp_servers.browser.server.types import ToolResult

    _install_hermetic_flow_mocks(monkeypatch)

    import mcp_servers.browser.tools as tools

    monkeypatch.setattr(
        tools,
        "get_page_info",
        lambda _cfg: {"pageInfo": {"url": "https://example.com/ok", "title": "Example"}},
    )

    registry = create_default_registry()
    called: list[str] = []

    def fake_dispatch(name: str, cfg: BrowserConfig, launcher, arguments):  # noqa: ANN001,ARG001
        called.append(name)
        if name == "click":
            return ToolResult.json({"ok": True})
        return ToolResult.error(f"unexpected dispatch: {name}", tool=name)

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    handler, _requires_browser = registry.get("flow")  # type: ignore[assignment]
    cfg = BrowserConfig.from_env()
    res = handler(
        cfg,
        launcher=None,
        args={
            "steps": [
                {
                    "macro": {
                        "name": "assert_then",
                        "args": {"assert": {"url": "example.com/ok"}, "then": [{"click": {"text": "Continue"}}]},
                    }
                }
            ],
            "final": "none",
            "stop_on_error": True,
            "auto_recover": False,
            "step_proof": False,
            "action_timeout": 0.5,
        },
    )

    assert not res.is_error
    assert isinstance(res.data, dict)
    assert res.data.get("ok") is True
    assert called == ["click"]
