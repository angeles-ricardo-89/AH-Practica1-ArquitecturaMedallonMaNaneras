from __future__ import annotations

from urllib.parse import quote

import psycopg


def pg_connect(
    conn_str: str,
    *,
    connect_timeout: int,
    statement_timeout_ms: int,
) -> psycopg.Connection:
    return psycopg.connect(
        conn_str,
        connect_timeout=connect_timeout,
        options=f"-c statement_timeout={statement_timeout_ms}",
    )


def pg_conn_str_with_timeouts(
    conn_str: str,
    *,
    connect_timeout: int,
    statement_timeout_ms: int,
) -> str:
    options = quote(f"-c statement_timeout={statement_timeout_ms}")
    params = f"connect_timeout={connect_timeout}&options={options}"
    separator = "&" if "?" in conn_str else "?"
    return f"{conn_str}{separator}{params}"
