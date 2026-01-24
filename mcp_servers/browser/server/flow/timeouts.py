from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import os


@dataclass(frozen=True)
class RepeatDefaults:
    backoff_s: float
    backoff_factor: float
    backoff_max_s: float
    backoff_jitter: float
    jitter_seed: int


@dataclass(frozen=True)
class TimeoutDefaults:
    action_timeout_s: float
    recover_timeout_s: float
    auto_download_timeout_s: float
    condition_timeout_s: float
    repeat: RepeatDefaults


_PROFILE_DEFAULTS: dict[str, TimeoutDefaults] = {
    "fast": TimeoutDefaults(
        action_timeout_s=20.0,
        recover_timeout_s=4.0,
        auto_download_timeout_s=2.0,
        condition_timeout_s=0.2,
        repeat=RepeatDefaults(
            backoff_s=0.0,
            backoff_factor=1.0,
            backoff_max_s=0.0,
            backoff_jitter=0.0,
            jitter_seed=0,
        ),
    ),
    "default": TimeoutDefaults(
        action_timeout_s=30.0,
        recover_timeout_s=5.0,
        auto_download_timeout_s=3.0,
        condition_timeout_s=0.3,
        repeat=RepeatDefaults(
            backoff_s=0.0,
            backoff_factor=1.0,
            backoff_max_s=0.0,
            backoff_jitter=0.0,
            jitter_seed=0,
        ),
    ),
    "slow": TimeoutDefaults(
        action_timeout_s=60.0,
        recover_timeout_s=8.0,
        auto_download_timeout_s=6.0,
        condition_timeout_s=0.8,
        repeat=RepeatDefaults(
            # Default to a small deterministic backoff for long/slow sites.
            # Repeat is an explicit loop; a little spacing reduces flake and CPU churn.
            backoff_s=0.2,
            backoff_factor=1.5,
            backoff_max_s=2.0,
            backoff_jitter=0.15,
            jitter_seed=0,
        ),
    ),
}


def _coerce_profile(raw: str | None) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "default"
    value = raw.strip().lower()
    return value if value in _PROFILE_DEFAULTS else "default"


def _env_float(env: Mapping[str, str], *keys: str, fallback: float) -> float:
    for key in keys:
        raw = env.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except Exception:
            continue
    return float(fallback)


def _env_int(env: Mapping[str, str], *keys: str, fallback: int) -> int:
    for key in keys:
        raw = env.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    return int(fallback)


def resolve_timeout_profile(*, args_profile: str | None, scope: str, env: Mapping[str, str] | None = None) -> str:
    env_map = env or os.environ
    if isinstance(args_profile, str) and args_profile.strip():
        return _coerce_profile(args_profile)
    scoped_key = f"MCP_{scope.upper()}_TIMEOUT_PROFILE"
    if scoped_key in env_map:
        return _coerce_profile(env_map.get(scoped_key))
    return _coerce_profile(env_map.get("MCP_TIMEOUT_PROFILE"))


def resolve_timeout_defaults(*, profile: str, scope: str, env: Mapping[str, str] | None = None) -> TimeoutDefaults:
    env_map = env or os.environ
    base = _PROFILE_DEFAULTS.get(profile, _PROFILE_DEFAULTS["default"])
    prefix = f"MCP_{scope.upper()}_"

    return TimeoutDefaults(
        action_timeout_s=_env_float(
            env_map,
            f"{prefix}ACTION_TIMEOUT",
            "MCP_ACTION_TIMEOUT",
            fallback=base.action_timeout_s,
        ),
        recover_timeout_s=_env_float(
            env_map,
            f"{prefix}RECOVER_TIMEOUT",
            "MCP_RECOVER_TIMEOUT",
            fallback=base.recover_timeout_s,
        ),
        auto_download_timeout_s=_env_float(
            env_map,
            f"{prefix}AUTO_DOWNLOAD_TIMEOUT",
            "MCP_AUTO_DOWNLOAD_TIMEOUT",
            fallback=base.auto_download_timeout_s,
        ),
        condition_timeout_s=_env_float(
            env_map,
            f"{prefix}CONDITION_TIMEOUT",
            "MCP_CONDITION_TIMEOUT",
            fallback=base.condition_timeout_s,
        ),
        repeat=RepeatDefaults(
            backoff_s=_env_float(
                env_map,
                f"{prefix}REPEAT_BACKOFF_S",
                "MCP_REPEAT_BACKOFF_S",
                fallback=base.repeat.backoff_s,
            ),
            backoff_factor=_env_float(
                env_map,
                f"{prefix}REPEAT_BACKOFF_FACTOR",
                "MCP_REPEAT_BACKOFF_FACTOR",
                fallback=base.repeat.backoff_factor,
            ),
            backoff_max_s=_env_float(
                env_map,
                f"{prefix}REPEAT_BACKOFF_MAX_S",
                "MCP_REPEAT_BACKOFF_MAX_S",
                fallback=base.repeat.backoff_max_s,
            ),
            backoff_jitter=_env_float(
                env_map,
                f"{prefix}REPEAT_BACKOFF_JITTER",
                "MCP_REPEAT_BACKOFF_JITTER",
                fallback=base.repeat.backoff_jitter,
            ),
            jitter_seed=_env_int(
                env_map,
                f"{prefix}REPEAT_JITTER_SEED",
                "MCP_REPEAT_JITTER_SEED",
                fallback=base.repeat.jitter_seed,
            ),
        ),
    )
