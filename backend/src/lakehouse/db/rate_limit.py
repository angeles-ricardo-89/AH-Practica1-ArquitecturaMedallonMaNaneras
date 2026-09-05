from __future__ import annotations

import psycopg

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
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(RATE_LIMIT_DDL)
        conn.commit()


def drop_rate_limit_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(DROP_RATE_LIMIT_DDL)
        conn.commit()
