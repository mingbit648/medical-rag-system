import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from passlib.hash import pbkdf2_sha256

from app.core.config import settings


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    if password_hash.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False
    try:
        return pbkdf2_sha256.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def build_session_expiry(days: int | None = None) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days or settings.AUTH_SESSION_DAYS)


def auth_cookie_secure() -> bool:
    raw = settings.AUTH_COOKIE_SECURE
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
