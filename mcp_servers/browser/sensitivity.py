"""Small helpers for identifying potentially sensitive keys.

Used by multiple tools to avoid leaking secrets (safe-by-default).
"""

from __future__ import annotations


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


def is_sensitive_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    return any(s in k for s in _SENSITIVE_SUBSTRINGS)
