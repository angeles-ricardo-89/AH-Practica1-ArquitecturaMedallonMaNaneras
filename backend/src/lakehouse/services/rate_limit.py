from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from lakehouse.db.rate_limit import ensure_rate_limit_tables


def minute_window_start() -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0)


def day_window_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def retry_after_seconds() -> int:
    now = datetime.now(UTC)
    return 60 - now.second


def increment(pg_conn_str: str, key: str, window_start: datetime) -> int:
    ensure_rate_limit_tables(pg_conn_str)
    with psycopg.connect(pg_conn_str) as conn:
        row = conn.execute(
            "INSERT INTO rate_limit_counter (key, window_start, count) "
            "VALUES (%s, %s, 1) "
            "ON CONFLICT (key) DO UPDATE SET "
            "count = CASE WHEN rate_limit_counter.window_start = %s "
            "THEN rate_limit_counter.count + 1 ELSE 1 END, "
            "window_start = %s RETURNING count",
            (key, window_start, window_start, window_start),
        ).fetchone()
    assert row is not None
    return row[0]


def is_allowed(pg_conn_str: str, key: str, window_start: datetime, limit: int) -> bool:
    return increment(pg_conn_str, key, window_start) <= limit


def cleanup_rate_limits(pg_conn_str: str, older_than: datetime) -> int:
    with psycopg.connect(pg_conn_str) as conn:
        row = conn.execute(
            "DELETE FROM rate_limit_counter WHERE window_start < %s RETURNING 1",
            (older_than,),
        ).fetchone()
    return 1 if row else 0


def cleanup_expired(pg_conn_str: str) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=1)
    cleanup_rate_limits(pg_conn_str, cutoff)
