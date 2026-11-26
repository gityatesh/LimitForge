"""Password hashing (Argon2id) and JWT login tokens (NFR-04)."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()  # Argon2id, a new random salt for every hash


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,                       # who
        "role": role,                         # informational only; the DB role is re-checked every request
        "iat": now,                           # issued at
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),  # expires
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """Returns the payload, or None if the token is forged, tampered or expired."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def new_secret_token() -> tuple[str, str]:
    """For password-reset links: returns (raw token for the email, SHA-256 hash for the DB).
    If the database leaks, the hashes are useless to an attacker."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()