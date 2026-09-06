from __future__ import annotations

from urllib.parse import unquote

import jwt as pyjwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.config import Settings
from lakehouse.db.connection import pg_conn_str_with_timeouts, pg_connect
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

pytestmark = [
    pytest.mark.security("A04"),
    pytest.mark.security("LLM02"),
    pytest.mark.security("A02"),
    pytest.mark.security("A10"),
]


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


def test_cors_fail_closed_by_default() -> None:
    client = TestClient(create_app(Settings()))
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_preflight_exact_origin() -> None:
    client = TestClient(create_app(Settings(cors_allowed_origins=["https://app.example"])))
    allowed = client.options(
        "/health",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "https://app.example"
    denied = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


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


def test_runtime_error_does_not_leak_internals() -> None:
    app_ = create_app(Settings())

    @app_.get("/_boom")
    def _boom() -> None:
        raise RuntimeError("SECRET_INTERNAL_DETAIL")

    client = TestClient(app_, raise_server_exceptions=False)
    r = client.get("/_boom")
    assert r.status_code == 503
    assert "SECRET_INTERNAL_DETAIL" not in r.text
    assert r.json() == {"detail": "Internal server error"}
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_body_size_limit_returns_413() -> None:
    client = TestClient(create_app(Settings()))
    big = '{"question": "' + "a" * 70000 + '"}'
    r = client.post("/auth/login", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json() == {"detail": "Request body too large"}
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_body_size_at_limit_not_rejected() -> None:
    client = TestClient(create_app(Settings(max_request_body_bytes=10)))
    ok = client.post(
        "/auth/login", content='{"ab":"1"}', headers={"content-type": "application/json"}
    )
    assert ok.status_code != 413


def test_pg_connect_applies_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake(conn_str: str, **kwargs: object) -> object:
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(psycopg, "connect", fake)
    with pytest.raises(RuntimeError):
        pg_connect("x", connect_timeout=5, statement_timeout_ms=10000)
    assert captured.get("connect_timeout") == 5
    assert "statement_timeout=10000" in str(captured.get("options", ""))


def test_pg_conn_str_embeds_timeouts() -> None:
    conn_str = pg_conn_str_with_timeouts(
        "postgresql://u:p@localhost:5433/db",
        connect_timeout=5,
        statement_timeout_ms=10000,
    )
    assert "connect_timeout=5" in conn_str
    assert "statement_timeout=10000" in unquote(conn_str)
