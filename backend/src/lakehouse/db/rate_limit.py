from __future__ import annotations

import psycopg

from lakehouse.config import Settings
from lakehouse.db.connection import pg_conn_str_with_timeouts


def _conn_str_with_timeouts(conn_str: str) -> str:
    settings = Settings()
    return pg_conn_str_with_timeouts(
        conn_str,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


RATE_LIMIT_DDL = """
CREATE TABLE IF NOT EXISTS rate_limit_counter (
    key          TEXT PRIMARY KEY,
    window_start TIMESTAMPTZ NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0
);
"""

DROP_RATE_LIMIT_DDL = """
DROP TABLE IF EXISTS rate_limit_counter;
"""


def ensure_rate_limit_tables(pg_conn_str: str) -> None:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        conn.execute(RATE_LIMIT_DDL)
        conn.commit()


def drop_rate_limit_tables(pg_conn_str: str) -> None:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        conn.execute(DROP_RATE_LIMIT_DDL)
        conn.commit()
