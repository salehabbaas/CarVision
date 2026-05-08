"""
core/crypto.py — lightweight symmetric encryption for sensitive fields.

ONVIF passwords are stored encrypted in the database using Fernet (AES-128-CBC
+ HMAC-SHA256).

Set FIELD_ENCRYPTION_KEY in .env to a 32-byte base64url-encoded key.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

IMPORTANT: FIELD_ENCRYPTION_KEY is independent of JWT_SECRET. Rotating JWT_SECRET
(e.g. after a breach) does NOT break stored encrypted passwords. If you rotate
FIELD_ENCRYPTION_KEY you must re-encrypt all ONVIF passwords in the database.

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
        from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
    except ImportError:
        logger.warning(
            "cryptography package not installed — ONVIF passwords stored as plaintext. "
            "Run: pip install cryptography"
        )
        return None

    field_key = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if field_key:
        # Use the dedicated encryption key if provided.
        fernet_key = field_key.encode()
    else:
        # Fall back to deriving from JWT_SECRET for backwards-compatibility,
        # but warn loudly so operators know to set FIELD_ENCRYPTION_KEY.
        jwt_secret = os.getenv("JWT_SECRET", "carvision-dev-secret")
        logger.warning(
            "FIELD_ENCRYPTION_KEY is not set — deriving encryption key from JWT_SECRET. "
            "Set FIELD_ENCRYPTION_KEY to an independent key so rotating JWT_SECRET does not "
            "break stored ONVIF passwords. "
            "Generate one: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
        key_bytes = hashlib.sha256(jwt_secret.encode()).digest()
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
