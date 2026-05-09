"""Persistent admin auth state stored in app_settings.

This module keeps admin credentials and recovery master password out of .env.
Both secrets are stored as PBKDF2 hashes with per-secret random salts.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from models import AppSetting

AUTH_ADMIN_USERNAME_KEY = "auth_admin_username"
AUTH_ADMIN_PASSWORD_HASH_KEY = "auth_admin_password_hash"
AUTH_ADMIN_PASSWORD_SALT_KEY = "auth_admin_password_salt"
AUTH_MASTER_PASSWORD_HASH_KEY = "auth_master_password_hash"
AUTH_MASTER_PASSWORD_SALT_KEY = "auth_master_password_salt"

_PBKDF2_ITERS = 210_000


def _get_setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    if not row or row.value is None:
        return ""
    return str(row.value).strip()


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if not row:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _norm_username(username: str) -> str:
    return str(username or "").strip()


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        _PBKDF2_ITERS,
    )
    return digest.hex()


def _build_hash(password: str) -> Tuple[str, str]:
    salt_hex = secrets.token_hex(16)
    return _hash_password(password, salt_hex), salt_hex


def get_admin_username(db: Session) -> Optional[str]:
    username = _get_setting(db, AUTH_ADMIN_USERNAME_KEY)
    return username or None


def is_admin_configured(db: Session) -> bool:
    return bool(
        _get_setting(db, AUTH_ADMIN_USERNAME_KEY)
        and _get_setting(db, AUTH_ADMIN_PASSWORD_HASH_KEY)
        and _get_setting(db, AUTH_ADMIN_PASSWORD_SALT_KEY)
    )


def is_master_configured(db: Session) -> bool:
    return bool(
        _get_setting(db, AUTH_MASTER_PASSWORD_HASH_KEY)
        and _get_setting(db, AUTH_MASTER_PASSWORD_SALT_KEY)
    )


def verify_admin_credentials(db: Session, username: str, password: str) -> bool:
    stored_user = _get_setting(db, AUTH_ADMIN_USERNAME_KEY)
    stored_hash = _get_setting(db, AUTH_ADMIN_PASSWORD_HASH_KEY)
    stored_salt = _get_setting(db, AUTH_ADMIN_PASSWORD_SALT_KEY)
    if not stored_user or not stored_hash or not stored_salt:
        return False
    if not hmac.compare_digest(_norm_username(username), stored_user):
        return False
    calc = _hash_password(password, stored_salt)
    return hmac.compare_digest(calc, stored_hash)


def verify_master_password(db: Session, master_password: str) -> bool:
    stored_hash = _get_setting(db, AUTH_MASTER_PASSWORD_HASH_KEY)
    stored_salt = _get_setting(db, AUTH_MASTER_PASSWORD_SALT_KEY)
    if not stored_hash or not stored_salt:
        return False
    calc = _hash_password(master_password, stored_salt)
    return hmac.compare_digest(calc, stored_hash)


def bootstrap_status(db: Session) -> dict:
    admin_ready = is_admin_configured(db)
    master_ready = is_master_configured(db)
    return {
        "setup_required": not admin_ready,
        "can_bootstrap": (not admin_ready) and (not master_ready),
        "recovery_required": (not admin_ready) and master_ready,
        "admin_configured": admin_ready,
        "master_configured": master_ready,
    }


def bootstrap_admin(db: Session, username: str, password: str) -> str:
    username = _norm_username(username)
    password = str(password or "")

    if is_admin_configured(db) or is_master_configured(db):
        raise ValueError("Bootstrap already completed")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    admin_hash, admin_salt = _build_hash(password)
    master_password = secrets.token_urlsafe(24)
    master_hash, master_salt = _build_hash(master_password)

    _set_setting(db, AUTH_ADMIN_USERNAME_KEY, username)
    _set_setting(db, AUTH_ADMIN_PASSWORD_HASH_KEY, admin_hash)
    _set_setting(db, AUTH_ADMIN_PASSWORD_SALT_KEY, admin_salt)
    _set_setting(db, AUTH_MASTER_PASSWORD_HASH_KEY, master_hash)
    _set_setting(db, AUTH_MASTER_PASSWORD_SALT_KEY, master_salt)
    db.commit()
    return master_password


def reset_admin_with_master(
    db: Session,
    master_password: str,
    *,
    new_username: Optional[str] = None,
    new_password: Optional[str] = None,
    remove_admin: bool = False,
) -> None:
    if not verify_master_password(db, master_password):
        raise ValueError("Invalid master password")

    if remove_admin:
        _set_setting(db, AUTH_ADMIN_USERNAME_KEY, "")
        _set_setting(db, AUTH_ADMIN_PASSWORD_HASH_KEY, "")
        _set_setting(db, AUTH_ADMIN_PASSWORD_SALT_KEY, "")
        db.commit()
        return

    username = _norm_username(new_username or "")
    password = str(new_password or "")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    admin_hash, admin_salt = _build_hash(password)
    _set_setting(db, AUTH_ADMIN_USERNAME_KEY, username)
    _set_setting(db, AUTH_ADMIN_PASSWORD_HASH_KEY, admin_hash)
    _set_setting(db, AUTH_ADMIN_PASSWORD_SALT_KEY, admin_salt)
    db.commit()

