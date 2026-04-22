"""
core/crypto.py — lightweight symmetric encryption for sensitive fields.

ONVIF passwords are stored encrypted in the database using Fernet (AES-128-CBC
+ HMAC-SHA256).  The encryption key is derived from JWT_SECRET so no extra
secret needs to be configured; just set a strong JWT_SECRET in .env.

Usage:
    from core.crypto import encrypt_field, decrypt_field

    # Before saving to DB:
    cam.onvif_password = encrypt_field(raw_password)

    # Before using the value:
    raw = decrypt_field(cam.onvif_password)
"""

import base64
import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger("carvision.crypto")

# Lazily imported so startup doesn't fail if cryptography isn't installed yet.
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning(
            "cryptography package not installed — ONVIF passwords stored as plaintext. "
            "Run: pip install cryptography"
        )
        return None

    secret = os.getenv("JWT_SECRET", "carvision-dev-secret")
    # Derive a 32-byte key from the JWT secret using SHA-256, then base64url-encode
    # it to produce a valid Fernet key.
    key_bytes = hashlib.sha256(secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    _fernet = Fernet(fernet_key)
    return _fernet


_PREFIX = "enc:"


def encrypt_field(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a sensitive string for database storage.

    Returns the plaintext unchanged (with a warning) if cryptography is not
    available or the value is already encrypted.  Returns None for None input.
    """
    if plaintext is None:
        return None
    if plaintext.startswith(_PREFIX):
        return plaintext  # Already encrypted
    f = _get_fernet()
    if f is None:
        return plaintext  # Fallback: store plaintext with warning already logged
    try:
        token = f.encrypt(plaintext.encode()).decode()
        return f"{_PREFIX}{token}"
    except Exception:
        logger.exception("encrypt_field failed; storing plaintext")
        return plaintext


def decrypt_field(value: Optional[str]) -> Optional[str]:
    """Decrypt a field that was encrypted with encrypt_field.

    Returns the value unchanged if it was not encrypted (backward-compatible
    with existing plaintext rows).  Returns None for None input.
    """
    if value is None:
        return None
    if not value.startswith(_PREFIX):
        return value  # Legacy plaintext row — return as-is
    f = _get_fernet()
    if f is None:
        # Can't decrypt; return the raw token rather than crashing
        logger.warning("cryptography not available — cannot decrypt field")
        return value
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except Exception:
        logger.exception("decrypt_field failed; returning raw value")
        return value
