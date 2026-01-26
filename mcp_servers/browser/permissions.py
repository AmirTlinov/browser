from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


def _norm_perm(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    val = raw.strip().lower()
    return val or None


def _norm_setting(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in {"allow", "allowed", "grant", "granted"}:
        return "granted"
    if v in {"deny", "denied", "block", "blocked"}:
        return "denied"
    if v in {"prompt", "default", ""}:
        return "prompt"
    return "prompt"


def _parse_perm_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            perm = _norm_perm(str(item))
            if perm:
                out.append(perm)
        return out
    if isinstance(raw, str):
        return [p for p in (_norm_perm(s) for s in raw.split(",")) if p]
    return []


def _parse_rule_map(raw: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not isinstance(raw, str) or not raw.strip():
        return out
    for entry in raw.split(";"):
        if not entry.strip():
            continue
        if "=" not in entry:
            continue
        key, val = entry.split("=", 1)
        origin = key.strip()
        if not origin:
            continue
        perms = _parse_perm_list(val)
        if perms:
            out[origin] = perms
    return out


def _merge_rule_map(base: dict[str, list[str]], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {k: list(v) for k, v in (base or {}).items()}
    for origin, perms in (extra or {}).items():
        if not perms:
            continue
        prev = merged.get(origin, [])
        merged[origin] = list(dict.fromkeys([*prev, *perms]))
    return merged


def _origin_from_url(url: str) -> tuple[str | None, str | None]:
    if not isinstance(url, str) or not url.strip():
        return None, None
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return None, None
    if parts.scheme not in {"http", "https"}:
        return None, None
    if not parts.netloc:
        return None, None
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    host = parts.hostname.lower() if isinstance(parts.hostname, str) else None
    return origin, host


def _match_origin(origin: str, host: str, pattern: str) -> bool:
    pat = (pattern or "").strip().lower().rstrip("/")
    if not pat:
        return False
    if pat == "*":
        return True
    if "://" in pat:
        return origin == pat
    # Host-only pattern (suffix match).
    pat_host = pat.lstrip(".")
    return host == pat_host or host.endswith("." + pat_host)


@dataclass(frozen=True)
class PermissionPolicy:
    default: str = "prompt"
    default_permissions: list[str] = field(default_factory=list)
    allow: dict[str, list[str]] = field(default_factory=dict)
    deny: dict[str, list[str]] = field(default_factory=dict)

    def enabled(self) -> bool:
        if self.allow or self.deny:
            return True
        if _norm_setting(self.default) != "prompt" and self.default_permissions:
            return True
        return False

    def settings_for_origin(self, origin: str, host: str) -> dict[str, str]:
        default_setting = _norm_setting(self.default)
        settings: dict[str, str] = {}

        if default_setting != "prompt":
            for perm in self.default_permissions:
                p = _norm_perm(perm)
                if p:
                    settings[p] = default_setting

        for pat, perms in self.allow.items():
            if _match_origin(origin, host, pat):
                for perm in perms:
                    p = _norm_perm(perm)
                    if p:
                        settings[p] = "granted"

        for pat, perms in self.deny.items():
            if _match_origin(origin, host, pat):
                for perm in perms:
                    p = _norm_perm(perm)
                    if p:
                        settings[p] = "denied"

        return settings


def permission_policy_from_env() -> PermissionPolicy:
    raw_json = os.environ.get("MCP_PERMISSION_POLICY", "")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            data = json.loads(raw_json)
        except Exception:
            data = {}
        if isinstance(data, dict):
            default = _norm_setting(str(data.get("default", "prompt")))
            default_perms = _parse_perm_list(data.get("default_permissions"))
            allow = {}
            deny = {}
            if isinstance(data.get("allow"), dict):
                for k, v in data["allow"].items():
                    allow[str(k)] = _parse_perm_list(v)
            if isinstance(data.get("deny"), dict):
                for k, v in data["deny"].items():
                    deny[str(k)] = _parse_perm_list(v)
            return PermissionPolicy(
                default=default,
                default_permissions=default_perms,
                allow=allow,
                deny=deny,
            )

    allow_raw = os.environ.get("MCP_PERMISSION_ALLOW", "")
    deny_raw = os.environ.get("MCP_PERMISSION_DENY", "")
    default_raw = os.environ.get("MCP_PERMISSION_DEFAULT", "prompt")
    default_perms_raw = os.environ.get("MCP_PERMISSION_DEFAULT_PERMS", "")

    return PermissionPolicy(
        default=_norm_setting(default_raw),
        default_permissions=_parse_perm_list(default_perms_raw),
        allow=_parse_rule_map(allow_raw),
        deny=_parse_rule_map(deny_raw),
    )


def apply_permission_policy(session: Any, policy: PermissionPolicy, url: str) -> dict[str, Any]:
    origin, host = _origin_from_url(url)
    if not origin or not host:
        return {"ok": False, "reason": "unsupported_origin"}
    if not isinstance(policy, PermissionPolicy) or not policy.enabled():
        return {"ok": False, "reason": "policy_disabled"}

    settings = policy.settings_for_origin(origin, host)
    if not settings:
        return {"ok": False, "reason": "no_rules"}

    applied: list[dict[str, str]] = []
    for perm, setting in settings.items():
        if setting == "prompt":
            continue
        try:
            session.send(
                "Browser.setPermission",
                {"permission": {"name": perm}, "setting": setting, "origin": origin},
            )
            applied.append({"permission": perm, "setting": setting})
            continue
        except Exception:
            if setting == "granted":
                try:
                    session.send("Browser.grantPermissions", {"permissions": [perm], "origin": origin})
                    applied.append({"permission": perm, "setting": setting})
                except Exception:
                    pass

    return {"ok": bool(applied), "origin": origin, "applied": applied}
