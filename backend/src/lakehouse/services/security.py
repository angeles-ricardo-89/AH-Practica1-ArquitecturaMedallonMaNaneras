from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
from pwdlib import PasswordHash

if TYPE_CHECKING:
    from lakehouse.config import Settings

_DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789abcdef0123456789abcdef"
_DEV_CSRF_SECRET = "dev-only-csrf-secret-change-me-0123456789abcdef0123456789abcd"

_password_hash = PasswordHash.recommended()


def resolve_jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret and len(settings.jwt_secret) >= 32:
        return settings.jwt_secret
    if settings.app_env == "production":
        raise RuntimeError("JWT secret must be set (>= 32 chars) in production")
    return _DEV_JWT_SECRET


def resolve_csrf_secret(settings: Settings) -> str:
    if settings.csrf_secret and len(settings.csrf_secret) >= 32:
        return settings.csrf_secret
    if settings.app_env == "production":
        raise RuntimeError("CSRF secret must be set (>= 32 chars) in production")
    return _DEV_CSRF_SECRET


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    secret: str,
    issuer: str,
    audience: str,
    expire_minutes: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
        "iss": issuer,
        "aud": audience,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str, issuer: str, audience: str) -> dict:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=issuer,
        audience=audience,
    )


def create_csrf_token(user_id: str, iat: int, secret: str) -> str:
    message = f"{user_id}:{iat}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_csrf_token(token: str, user_id: str, iat: int, secret: str) -> bool:
    expected = create_csrf_token(user_id, iat, secret)
    return hmac.compare_digest(token, expected)


def generate_public_id(secret: str, internal_id: int) -> str:
    message = f"conversation:{internal_id}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_digest(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
