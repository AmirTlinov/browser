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
    "authorization",
    "cookie",
    "session",
    "jwt",
    "bearer",
    "api-key",
    "api_key",
    "apikey",
)

_SENSITIVE_EXACT = {
    # Avoid false-positives like "author"/"authorship" while still protecting obvious keys.
    "auth",
}


def is_sensitive_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    if k in _SENSITIVE_EXACT:
        return True
    return any(s in k for s in _SENSITIVE_SUBSTRINGS)
