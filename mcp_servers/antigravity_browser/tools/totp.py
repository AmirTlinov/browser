"""
TOTP (Time-based One-Time Password) generation for 2FA.

Provides:
- generate_totp: Generate TOTP code from secret
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Any

from .base import SmartToolError


def generate_totp(secret: str, digits: int = 6, interval: int = 30) -> dict[str, Any]:
    """Generate TOTP code for two-factor authentication.

    Implements RFC 6238 TOTP algorithm.

    Args:
        secret: Base32-encoded TOTP secret from authenticator app setup
        digits: Number of digits in code (default: 6)
        interval: Time interval in seconds (default: 30)

    Returns:
        Dict with code, valid_for seconds, and timestamp

    Example:
        result = generate_totp(secret="JBSWY3DPEHPK3PXP")
        print(result["code"])  # "123456"
    """
    try:
        # Normalize secret: remove spaces, uppercase
        secret_clean = secret.replace(" ", "").upper()

        # Add padding if needed for base32
        padding = 8 - (len(secret_clean) % 8)
        if padding != 8:
            secret_clean += "=" * padding

        # Decode base32 secret
        try:
            key = base64.b32decode(secret_clean)
        except Exception as e:
            raise SmartToolError(
                tool="generate_totp",
                action="decode_secret",
                reason=f"Invalid base32 secret: {e}",
                suggestion="Provide a valid base32-encoded secret from your authenticator app setup",
            ) from e

        # Calculate time counter
        current_time = int(time.time())
        counter = current_time // interval
        time_remaining = interval - (current_time % interval)

        # Pack counter as 8-byte big-endian
        counter_bytes = struct.pack(">Q", counter)

        # HMAC-SHA1
        hmac_hash = hmac.new(key, counter_bytes, hashlib.sha1).digest()

        # Dynamic truncation (RFC 4226)
        offset = hmac_hash[-1] & 0x0F
        truncated = struct.unpack(">I", hmac_hash[offset : offset + 4])[0] & 0x7FFFFFFF

        # Generate code with specified digits
        code = str(truncated % (10**digits)).zfill(digits)

        return {
            "code": code,
            "valid_for": time_remaining,
            "timestamp": current_time,
            "interval": interval,
            "digits": digits,
        }

    except SmartToolError:
        raise
    except Exception as e:
        raise SmartToolError(
            tool="generate_totp",
            action="generate",
            reason=str(e),
            suggestion="Check the secret format and parameters",
        ) from e
