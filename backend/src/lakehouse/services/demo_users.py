from __future__ import annotations

import psycopg

from lakehouse.db.auth_memory import ensure_auth_memory_tables
from lakehouse.services.security import hash_password


def ensure_demo_users(pg_conn_str: str, users: list[tuple[str, str]]) -> None:
    ensure_auth_memory_tables(pg_conn_str)
    if not users:
        return
    with psycopg.connect(pg_conn_str) as conn:
        for username, password in users:
            conn.execute(
                """
                INSERT INTO app_user (username, password_hash, role)
                VALUES (%s, %s, 'demo')
                ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
                """,
                (username, hash_password(password)),
            )
        conn.commit()
