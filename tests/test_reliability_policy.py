from __future__ import annotations


def test_policy_lenient_coerce() -> None:
    from mcp_servers.browser.server.reliability import parse_policy_args

    policy, args, warnings, errors = parse_policy_args(
        {
            "heuristic_level": "2",
            "auto_tab": "true",
            "auto_dialog": "dismiss",
            "max_recoveries": "3",
        }
    )

    assert errors == []
    assert policy.level == 2
    assert args["auto_tab"] is True
    assert args["auto_dialog"] == "dismiss"
    assert args["max_recoveries"] == 3
    assert warnings == []


def test_policy_strict_rejects_invalid() -> None:
    from mcp_servers.browser.server.reliability import parse_policy_args

    _policy, _args, _warnings, errors = parse_policy_args(
        {"strict_params": True, "auto_dialog": "maybe"}
    )

    assert errors


def test_policy_applies_defaults() -> None:
    from mcp_servers.browser.server.reliability import parse_policy_args

    policy, args, warnings, errors = parse_policy_args({"heuristic_level": 0})

    assert errors == []
    assert policy.level == 0
    assert args["auto_dialog"] == "off"
    assert args["auto_recover"] is False
    assert args["max_recoveries"] == 0
    assert warnings == []
