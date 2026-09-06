from __future__ import annotations

import logging

import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.main import app
from lakehouse.services.demo_users import ensure_demo_users

TEST_USERS = [("testuser1", "test-password-1"), ("testuser2", "test-password-2")]

pytestmark = [
    pytest.mark.security("A07"),
    pytest.mark.security("A04"),
    pytest.mark.security("CSRF"),
    pytest.mark.security("A09"),
]


def test_login_success_sets_cookie(real_auth, demo_users) -> None:
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": "testuser1", "password": "test-password-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["csrf_token"]
    assert client.cookies.get("access_token")


def test_login_invalid_same_message(real_auth, demo_users) -> None:
    client = TestClient(app)
    wrong_pass = client.post(
        "/auth/login", json={"username": "testuser1", "password": "incorrecta"}
    )
    missing_user = client.post(
        "/auth/login", json={"username": "no-existe", "password": "incorrecta"}
    )
    assert wrong_pass.status_code == 401
    assert missing_user.status_code == 401
    assert wrong_pass.json()["detail"] == missing_user.json()["detail"]


def test_protected_endpoint_requires_auth(real_auth) -> None:
    client = TestClient(app)
    assert client.get("/config").status_code == 401
    assert client.get("/clusters/latest").status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_me_returns_identity(real_auth, demo_users) -> None:
    client = TestClient(app)
    client.post("/auth/login", json={"username": "testuser1", "password": "test-password-1"})
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "testuser1"
    assert body["role"] == "demo"


def test_logout_with_csrf(real_auth, demo_users) -> None:
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"username": "testuser1", "password": "test-password-1"}
    )
    csrf = login.json()["csrf_token"]
    resp = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert client.cookies.get("access_token") is None


def test_logout_without_csrf_rejected(real_auth, demo_users) -> None:
    client = TestClient(app)
    client.post("/auth/login", json={"username": "testuser1", "password": "test-password-1"})
    resp = client.post("/auth/logout")
    assert resp.status_code == 403


def test_demo_users_idempotent(pg_conn_str: str) -> None:
    ensure_demo_users(pg_conn_str, TEST_USERS)
    ensure_demo_users(pg_conn_str, TEST_USERS)
    with psycopg.connect(pg_conn_str) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM app_user WHERE username IN ('testuser1', 'testuser2')"
        ).fetchone()[0]
    assert count == 2
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM app_user WHERE username IN ('testuser1', 'testuser2')")
        conn.commit()


def test_ensure_demo_users_empty_is_noop(pg_conn_str: str) -> None:
    ensure_demo_users(pg_conn_str, [])


def test_login_failure_does_not_leak_password(
    caplog: pytest.LogCaptureFixture, real_auth, demo_users
) -> None:
    client = TestClient(app)
    secret = "super-secret-password-xyz"
    with caplog.at_level(logging.DEBUG):
        resp = client.post("/auth/login", json={"username": "testuser1", "password": secret})
    assert resp.status_code == 401
    assert secret not in resp.text
    assert secret not in caplog.text
