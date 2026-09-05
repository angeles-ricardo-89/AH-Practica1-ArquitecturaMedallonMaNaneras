from __future__ import annotations

import jwt as pyjwt
import pytest

from lakehouse.config import Settings
from lakehouse.services.security import (
    create_access_token,
    create_csrf_token,
    decode_access_token,
    hash_password,
    resolve_csrf_secret,
    resolve_jwt_secret,
    verify_csrf_token,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secreto-123")
    assert hashed != "secreto-123"
    assert verify_password("secreto-123", hashed)
    assert not verify_password("otra-contrasena", hashed)


def test_access_token_roundtrip() -> None:
    settings = Settings()
    secret = resolve_jwt_secret(settings)
    token = create_access_token(
        7, "demo", "demo", secret, settings.jwt_issuer, settings.jwt_audience, 60
    )
    claims = decode_access_token(token, secret, settings.jwt_issuer, settings.jwt_audience)
    assert claims["sub"] == "7"
    assert claims["username"] == "demo"
    assert claims["role"] == "demo"
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience
    assert "iat" in claims
    assert "exp" in claims


def test_access_token_expiry() -> None:
    settings = Settings()
    secret = resolve_jwt_secret(settings)
    token = create_access_token(
        1, "demo", "demo", secret, settings.jwt_issuer, settings.jwt_audience, -1
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token, secret, settings.jwt_issuer, settings.jwt_audience)


def test_csrf_token_roundtrip() -> None:
    secret = resolve_csrf_secret(Settings())
    token = create_csrf_token("7", 12345, secret)
    assert verify_csrf_token(token, "7", 12345, secret)
    assert not verify_csrf_token(token, "8", 12345, secret)
    assert not verify_csrf_token(token, "7", 99999, secret)


def test_production_requires_secret() -> None:
    with pytest.raises(RuntimeError):
        resolve_jwt_secret(Settings(app_env="production", jwt_secret=""))
    with pytest.raises(RuntimeError):
        resolve_csrf_secret(Settings(app_env="production", csrf_secret="corto"))


def test_valid_secret_is_used() -> None:
    secret = "a" * 40
    settings = Settings(app_env="production", jwt_secret=secret, csrf_secret=secret)
    assert resolve_jwt_secret(settings) == secret
    assert resolve_csrf_secret(settings) == secret
