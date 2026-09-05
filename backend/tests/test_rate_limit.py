from __future__ import annotations

from datetime import timedelta

import psycopg
from fastapi.testclient import TestClient

from lakehouse.api.deps import get_settings
from lakehouse.config import Settings
from lakehouse.db.rate_limit import ensure_rate_limit_tables
from lakehouse.main import app
from lakehouse.services.rate_limit import (
    cleanup_rate_limits,
    increment,
    is_allowed,
    minute_window_start,
)


def test_increment_within_limit(pg_conn_str: str) -> None:
    key = "test:key:1"
    assert is_allowed(pg_conn_str, key, minute_window_start(), 5) is True


def test_increment_over_limit(pg_conn_str: str) -> None:
    key = "test:key:2"
    window = minute_window_start()
    for _ in range(5):
        assert is_allowed(pg_conn_str, key, window, 5) is True
    assert is_allowed(pg_conn_str, key, window, 5) is False


def test_window_rollover_resets_counter(pg_conn_str: str) -> None:
    key = "test:key:3"
    window = minute_window_start()
    for _ in range(5):
        is_allowed(pg_conn_str, key, window, 5)
    assert is_allowed(pg_conn_str, key, window, 5) is False
    previous = window - timedelta(minutes=1)
    assert is_allowed(pg_conn_str, key, previous, 5) is True


def test_cleanup_removes_old_windows(pg_conn_str: str) -> None:
    key = "test:key:4"
    window = minute_window_start()
    increment(pg_conn_str, key, window)
    cleanup_rate_limits(pg_conn_str, window + timedelta(seconds=1))
    with psycopg.connect(pg_conn_str) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM rate_limit_counter WHERE key = %s", (key,)
        ).fetchone()[0]
    assert count == 0


def test_login_rate_limit_429(pg_conn_str: str) -> None:
    ensure_rate_limit_tables(pg_conn_str)
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("TRUNCATE rate_limit_counter")
        conn.commit()

    app.dependency_overrides[get_settings] = lambda: Settings(login_rate_limit=5)
    try:
        client = TestClient(app)
        statuses = []
        for _ in range(6):
            resp = client.post(
                "/auth/login", json={"username": "ratelimit_probe", "password": "wrong"}
            )
            statuses.append(resp.status_code)

        assert statuses[:5] == [401] * 5
        assert statuses[5] == 429
    finally:
        app.dependency_overrides.pop(get_settings, None)
