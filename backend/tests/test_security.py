from __future__ import annotations

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from lakehouse.config import Settings
from lakehouse.main import create_app
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

pytestmark = pytest.mark.security("HDRS")


def test_security_headers_always_present() -> None:
    client = TestClient(create_app(Settings()))
    r = client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("x-frame-options") == "DENY"


def test_hsts_and_csp_only_in_production() -> None:
    client = TestClient(create_app(Settings(app_env="production")))
    r = client.get("/health")
    assert "strict-transport-security" in r.headers
    assert "content-security-policy" in r.headers


def test_no_hsts_csp_in_local() -> None:
    client = TestClient(create_app(Settings()))
    r = client.get("/health")
    assert "strict-transport-security" not in r.headers
    assert "content-security-policy" not in r.headers


def test_docs_disabled_in_production() -> None:
    client = TestClient(create_app(Settings(app_env="production")))
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_available_in_local() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/docs").status_code == 200


def test_cors_exact_origin() -> None:
    client = TestClient(create_app(Settings(cors_allowed_origins=["https://app.example"])))
    ok = client.get("/health", headers={"Origin": "https://app.example"})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example"
    bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


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
