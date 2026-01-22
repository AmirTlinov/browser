"""Storage (localStorage / sessionStorage) utilities.

Design goals:
- Cognitive-cheap by default: list keys + counts, avoid dumping values.
- Safe-by-default: strict policy blocks mutation and sensitive value reveal.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import BrowserConfig
from ..session import session_manager
from .base import SmartToolError, get_session

_SENSITIVE_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "auth",
    "authorization",
    "cookie",
    "session",
    "jwt",
    "bearer",
    "api-key",
    "apikey",
)


def _is_sensitive_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    return any(s in k for s in _SENSITIVE_SUBSTRINGS)


def _policy_mode() -> str:
    try:
        pol = session_manager.get_policy()
        mode = pol.get("mode")
        return str(mode or "permissive").strip().lower()
    except Exception:
        return "permissive"


def storage_action(
    config: BrowserConfig,
    *,
    action: str = "list",
    storage: str = "local",
    key: str | None = None,
    value: Any | None = None,
    items: dict[str, Any] | None = None,
    offset: int = 0,
    limit: int = 20,
    max_chars: int = 2000,
    reveal: bool = False,
) -> dict[str, Any]:
    """Perform a storage operation in the current page context."""

    action = str(action or "list").strip().lower()
    storage = str(storage or "local").strip().lower()
    if storage not in {"local", "session"}:
        raise SmartToolError(
            tool="storage",
            action="validate",
            reason=f"Invalid storage: {storage}",
            suggestion="Use storage='local' or storage='session'",
        )

    mode = _policy_mode()
    if mode == "strict" and action in {"set", "set_many", "delete", "clear"}:
        raise SmartToolError(
            tool="storage",
            action=action,
            reason="Strict policy forbids storage mutation",
            suggestion='Switch to permissive via browser(action="policy", mode="permissive") if you have explicit user approval',
        )

    if mode == "strict" and action == "get" and reveal and key and _is_sensitive_key(key):
        raise SmartToolError(
            tool="storage",
            action="get",
            reason="Strict policy forbids revealing sensitive storage values",
            suggestion="Use reveal=false (default) or switch to permissive if explicitly approved",
            details={"key": key},
        )

    try:
        offset_i = int(offset)
    except Exception:
        offset_i = 0
    offset_i = max(0, offset_i)

    try:
        limit_i = int(limit)
    except Exception:
        limit_i = 20
    limit_i = max(0, min(limit_i, 200))

    try:
        max_chars_i = int(max_chars)
    except Exception:
        max_chars_i = 2000
    max_chars_i = max(200, min(max_chars_i, 20000))

    with get_session(config) as (session, target):
        # Best-effort identity for correlation.
        try:
            url = session.eval_js("window.location.href")
        except Exception:
            url = None
        try:
            origin = session.eval_js("window.location.origin")
        except Exception:
            origin = None

        if action == "list":
            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                "    const keys = [];"
                "    for (let i = 0; i < s.length; i++) {"
                "      try { const k = s.key(i); if (k != null) keys.push(String(k)); } catch (_e) {}"
                "    }"
                "    keys.sort();"
                f"    const offset = {offset_i};"
                f"    const limit = {limit_i};"
                "    const slice = limit ? keys.slice(offset, offset + limit) : [];"
                "    return { ok: true, storage: which, total: keys.length, offset, limit, keys: slice };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="list",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_list_failed"),
                    suggestion="Try a regular http(s) page; some pages block storage access",
                )

            keys = res.get("keys") if isinstance(res.get("keys"), list) else []
            keys_out: list[dict[str, Any]] = []
            for k in keys[: min(len(keys), 50)]:
                if not isinstance(k, str):
                    continue
                keys_out.append({"key": k, **({"sensitive": True} if _is_sensitive_key(k) else {})})

            return {
                "storage": {
                    "action": "list",
                    "storage": storage,
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                    **({"url": url} if isinstance(url, str) and url else {}),
                    "total": res.get("total"),
                    "offset": res.get("offset"),
                    "limit": res.get("limit"),
                    "keys": keys_out,
                    "next": [
                        "storage(action='get', key='...') for one value (redacted by default)",
                        "storage(action='set', key='...', value='...') to set",
                    ],
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        if action == "get":
            if not (isinstance(key, str) and key.strip()):
                raise SmartToolError(
                    tool="storage",
                    action="get",
                    reason="Missing key",
                    suggestion="Provide key='...'",
                )
            k = key.strip()

            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                f"    const key = {json.dumps(k)};"
                "    const v = s.getItem(key);"
                "    const totalChars = v == null ? 0 : String(v).length;"
                f"    const maxChars = {max_chars_i};"
                "    const text = v == null ? null : String(v).slice(0, maxChars);"
                "    const truncated = totalChars > maxChars;"
                "    return { ok: true, storage: which, key, found: v != null, totalChars, truncated, text };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="get",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_get_failed"),
                    suggestion="Try a regular http(s) page; some pages block storage access",
                )

            found = bool(res.get("found"))
            total_chars = res.get("totalChars") if isinstance(res.get("totalChars"), int) else None
            truncated = bool(res.get("truncated"))
            text = res.get("text") if isinstance(res.get("text"), str) else None
            sensitive = _is_sensitive_key(k)

            # Safe-by-default: don't reveal values unless explicitly requested.
            value_preview: str | None
            redacted = False
            if not found:
                value_preview = None
            elif not reveal:
                value_preview = None
                redacted = True
            elif sensitive:
                # In permissive mode, allow reveal if explicitly requested, but mark it.
                value_preview = text
            else:
                value_preview = text

            return {
                "storage": {
                    "action": "get",
                    "storage": storage,
                    "key": k,
                    "found": found,
                    **({"sensitive": True} if sensitive else {}),
                    **({"redacted": True} if redacted else {}),
                    **({"totalChars": total_chars} if isinstance(total_chars, int) else {}),
                    **({"truncated": True} if truncated else {}),
                    **({"valuePreview": value_preview} if isinstance(value_preview, str) else {}),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                    **({"url": url} if isinstance(url, str) and url else {}),
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        if action == "set":
            if not (isinstance(key, str) and key.strip()):
                raise SmartToolError(tool="storage", action="set", reason="Missing key", suggestion="Provide key='...'")

            # localStorage values are strings; encode non-strings deterministically.
            v = value
            if isinstance(v, str):
                v_str = v
            else:
                try:
                    v_str = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    v_str = str(v)

            k = key.strip()
            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                f"    const key = {json.dumps(k)};"
                f"    const val = {json.dumps(v_str)};"
                "    s.setItem(key, val);"
                "    const after = s.getItem(key);"
                "    return { ok: true, storage: which, key, stored: after != null, totalChars: after == null ? 0 : String(after).length };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="set",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_set_failed"),
                    suggestion="Some pages block storage access or are in a restricted context",
                )
            return {
                "storage": {
                    "action": "set",
                    "storage": storage,
                    "key": k,
                    "stored": bool(res.get("stored")),
                    **({"totalChars": res.get("totalChars")} if isinstance(res.get("totalChars"), int) else {}),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        if action == "set_many":
            if not isinstance(items, dict) or not items:
                raise SmartToolError(
                    tool="storage",
                    action="set_many",
                    reason="Missing items",
                    suggestion="Provide items={key: value, ...}",
                )
            # Encode values to strings.
            pairs: list[tuple[str, str]] = []
            for k, v in list(items.items())[:200]:
                if not isinstance(k, str) or not k.strip():
                    continue
                if isinstance(v, str):
                    v_str = v
                else:
                    try:
                        v_str = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                    except Exception:
                        v_str = str(v)
                pairs.append((k.strip(), v_str))

            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                f"    const pairs = {json.dumps(pairs)};"
                "    let stored = 0;"
                "    for (const p of pairs) {"
                "      if (!p || p.length < 2) continue;"
                "      try { s.setItem(String(p[0]), String(p[1])); stored += 1; } catch (_e) {}"
                "    }"
                "    return { ok: true, storage: which, stored };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="set_many",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_set_many_failed"),
                    suggestion="Some pages block storage access or are in a restricted context",
                )
            return {
                "storage": {
                    "action": "set_many",
                    "storage": storage,
                    "stored": res.get("stored"),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        if action == "delete":
            if not (isinstance(key, str) and key.strip()):
                raise SmartToolError(
                    tool="storage",
                    action="delete",
                    reason="Missing key",
                    suggestion="Provide key='...'",
                )
            k = key.strip()
            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                f"    const key = {json.dumps(k)};"
                "    const existed = s.getItem(key) != null;"
                "    s.removeItem(key);"
                "    return { ok: true, storage: which, key, existed };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="delete",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_delete_failed"),
                    suggestion="Some pages block storage access or are in a restricted context",
                )
            return {
                "storage": {
                    "action": "delete",
                    "storage": storage,
                    "key": k,
                    "existed": bool(res.get("existed")),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        if action == "clear":
            js = (
                "(() => {"
                "  try {"
                f"    const which = {json.dumps(storage)};"
                "    const s = which === 'session' ? globalThis.sessionStorage : globalThis.localStorage;"
                "    if (!s) return { ok: false, error: 'storage_unavailable' };"
                "    const before = s.length;"
                "    s.clear();"
                "    return { ok: true, storage: which, cleared: before };"
                "  } catch (e) {"
                "    return { ok: false, error: String(e && e.message ? e.message : e) };"
                "  }"
                "})()"
            )
            res = session.eval_js(js) or {}
            if not isinstance(res, dict) or res.get("ok") is not True:
                raise SmartToolError(
                    tool="storage",
                    action="clear",
                    reason=str(res.get("error") if isinstance(res, dict) else "storage_clear_failed"),
                    suggestion="Some pages block storage access or are in a restricted context",
                )
            return {
                "storage": {
                    "action": "clear",
                    "storage": storage,
                    "cleared": res.get("cleared"),
                    **({"origin": origin} if isinstance(origin, str) and origin else {}),
                },
                "target": target["id"],
                "sessionTabId": session_manager.tab_id,
            }

        raise SmartToolError(
            tool="storage",
            action="validate",
            reason=f"Unknown action: {action}",
            suggestion="Use action='list'|'get'|'set'|'set_many'|'delete'|'clear'",
        )
