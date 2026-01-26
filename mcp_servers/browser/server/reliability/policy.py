"""Reliability policy parsing + defaults for run-level UX heuristics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReliabilityPolicy:
    level: int
    strict_params: bool
    applied: dict[str, Any]


_LEVEL_DEFAULTS: dict[int, dict[str, Any]] = {
    0: {
        "auto_dialog": "off",
        "auto_recover": False,
        "max_recoveries": 0,
        "auto_tab": False,
        "auto_affordances": False,
        "proof": False,
        "screenshot_on_ambiguity": False,
    },
    1: {},
    2: {
        "auto_dialog": "auto",
        "auto_recover": True,
        "max_recoveries": 2,
        "auto_tab": True,
        "auto_affordances": True,
        "proof": True,
        "screenshot_on_ambiguity": True,
    },
    3: {
        "auto_dialog": "auto",
        "auto_recover": True,
        "max_recoveries": 3,
        "auto_tab": True,
        "auto_affordances": True,
        "proof": True,
        "screenshot_on_ambiguity": True,
        "report": "diagnostics",
        "actions_output": "errors",
    },
}

_BOOLISH_KEYS = {
    "auto_recover",
    "auto_tab",
    "auto_affordances",
    "proof",
    "screenshot_on_ambiguity",
    "delta_report",
    "delta_final",
    "stop_on_error",
    "confirm_irreversible",
    "auto_download",
    "screenshot_on_error",
    "with_screenshot",
    "triage_on_error",
    "diagnostics_on_error",
    "step_proof",
}

_ENUM_KEYS: dict[str, set[str]] = {
    "auto_dialog": {"auto", "off", "dismiss", "accept"},
    "report": {"none", "observe", "audit", "triage", "diagnostics", "map", "graph"},
    "actions_output": {"compact", "errors", "none"},
    "proof_screenshot": {"none", "artifact"},
}

_INT_KEYS: dict[str, tuple[int, int]] = {
    "max_recoveries": (0, 5),
    "report_limit": (1, 200),
}

_FLOAT_KEYS: dict[str, tuple[float, float]] = {
    "action_timeout": (0.1, 300.0),
    "recover_timeout": (0.1, 60.0),
    "auto_download_timeout": (0.1, 30.0),
}


def _coerce_boolish(value: Any) -> tuple[bool | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, bool):
        return value, True
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value), True
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True, True
        if v in {"false", "0", "no", "n", "off"}:
            return False, True
    return None, False


def _coerce_int(value: Any, *, lo: int, hi: int) -> tuple[int | None, bool]:
    if value is None or isinstance(value, bool):
        return None, False
    try:
        num = int(value)
    except Exception:
        return None, False
    if num < lo or num > hi:
        return None, False
    return num, True


def _coerce_float(value: Any, *, lo: float, hi: float) -> tuple[float | None, bool]:
    if value is None or isinstance(value, bool):
        return None, False
    try:
        num = float(value)
    except Exception:
        return None, False
    if num < lo or num > hi:
        return None, False
    return num, True


def _handle_invalid(
    *,
    key: str,
    reason: str,
    strict: bool,
    errors: list[str],
    warnings: list[str],
    defaults: dict[str, Any],
    args: dict[str, Any],
) -> None:
    if strict:
        errors.append(f"{key}: {reason}")
        return
    if key in defaults:
        args[key] = defaults[key]
        warnings.append(f"{key}: {reason}; defaulted to policy value")
    else:
        args.pop(key, None)
        warnings.append(f"{key}: {reason}; using default")


def parse_policy_args(
    args: dict[str, Any],
) -> tuple[ReliabilityPolicy, dict[str, Any], list[str], list[str]]:
    src = dict(args or {})
    warnings: list[str] = []
    errors: list[str] = []

    strict = bool(src.get("strict_params", False))

    level_raw = src.get("heuristic_level", 1)
    level, ok = _coerce_int(level_raw, lo=0, hi=3)
    if not ok:
        if strict:
            errors.append("heuristic_level: expected integer 0-3")
            level = 1
        else:
            warnings.append("heuristic_level: invalid; defaulted to 1")
            level = 1

    defaults = _LEVEL_DEFAULTS.get(level, {})
    applied: dict[str, Any] = {}
    for key, value in defaults.items():
        if src.get(key) is None:
            src[key] = value
            applied[key] = value

    for key in list(_BOOLISH_KEYS):
        if key not in src:
            continue
        value = src.get(key)
        if value is None:
            src.pop(key, None)
            continue
        coerced, ok = _coerce_boolish(value)
        if ok and coerced is not None:
            src[key] = bool(coerced)
        elif ok and coerced is None:
            src.pop(key, None)
        else:
            _handle_invalid(
                key=key,
                reason="expected boolean",
                strict=strict,
                errors=errors,
                warnings=warnings,
                defaults=defaults,
                args=src,
            )

    for key, allowed in _ENUM_KEYS.items():
        if key not in src:
            continue
        value = src.get(key)
        if value is None:
            src.pop(key, None)
            continue
        if not isinstance(value, str):
            _handle_invalid(
                key=key,
                reason=f"expected one of {sorted(allowed)}",
                strict=strict,
                errors=errors,
                warnings=warnings,
                defaults=defaults,
                args=src,
            )
            continue
        normalized = value.strip().lower()
        if normalized in allowed:
            src[key] = normalized
        else:
            _handle_invalid(
                key=key,
                reason=f"expected one of {sorted(allowed)}",
                strict=strict,
                errors=errors,
                warnings=warnings,
                defaults=defaults,
                args=src,
            )

    for key, (lo, hi) in _INT_KEYS.items():
        if key not in src:
            continue
        value = src.get(key)
        if value is None:
            src.pop(key, None)
            continue
        coerced, ok = _coerce_int(value, lo=lo, hi=hi)
        if ok and coerced is not None:
            src[key] = coerced
        else:
            _handle_invalid(
                key=key,
                reason=f"expected integer {lo}-{hi}",
                strict=strict,
                errors=errors,
                warnings=warnings,
                defaults=defaults,
                args=src,
            )

    for key, (lo, hi) in _FLOAT_KEYS.items():
        if key not in src:
            continue
        value = src.get(key)
        if value is None:
            src.pop(key, None)
            continue
        coerced, ok = _coerce_float(value, lo=lo, hi=hi)
        if ok and coerced is not None:
            src[key] = coerced
        else:
            _handle_invalid(
                key=key,
                reason=f"expected number {lo}-{hi}",
                strict=strict,
                errors=errors,
                warnings=warnings,
                defaults=defaults,
                args=src,
            )

    policy = ReliabilityPolicy(level=level, strict_params=strict, applied=applied)
    return policy, src, warnings, errors


def policy_summary(policy: ReliabilityPolicy, warnings: list[str]) -> dict[str, Any] | None:
    if policy.level == 1 and not policy.strict_params and not policy.applied and not warnings:
        return None
    out: dict[str, Any] = {"heuristic_level": policy.level}
    if policy.strict_params:
        out["strict_params"] = True
    if policy.applied:
        out["applied"] = policy.applied
    if warnings:
        out["warnings"] = warnings[:8]
    return out


__all__ = ["ReliabilityPolicy", "parse_policy_args", "policy_summary"]
