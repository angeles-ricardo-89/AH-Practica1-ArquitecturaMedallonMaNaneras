from __future__ import annotations

import psycopg

from lakehouse.db.auth_memory import drop_auth_memory_tables, ensure_auth_memory_tables

EXPECTED_TABLES = {"app_user", "conversation", "message", "tool_execution"}


def _table_names(pg_conn_str: str) -> set[str]:
    with psycopg.connect(pg_conn_str) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def _cleanup_user(pg_conn_str: str, username: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM app_user WHERE username = %s", (username,))
        conn.commit()


def test_ensure_creates_tables(pg_conn_str: str) -> None:
    ensure_auth_memory_tables(pg_conn_str)
    assert EXPECTED_TABLES.issubset(_table_names(pg_conn_str))


def test_ensure_is_idempotent(pg_conn_str: str) -> None:
    ensure_auth_memory_tables(pg_conn_str)
    ensure_auth_memory_tables(pg_conn_str)
    assert EXPECTED_TABLES.issubset(_table_names(pg_conn_str))


def test_cascade_delete_conversation_removes_messages_and_tools(pg_conn_str: str) -> None:
    ensure_auth_memory_tables(pg_conn_str)
    username = "cascade_user"
    _cleanup_user(pg_conn_str, username)
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "INSERT INTO app_user (username, password_hash) VALUES (%s, %s)",
            (username, "hash"),
        )
        owner_id = conn.execute(
            "SELECT id FROM app_user WHERE username = %s", (username,)
        ).fetchone()[0]
        conv_row = conn.execute(
            "INSERT INTO conversation (owner_id, title, expires_at) "
            "VALUES (%s, %s, NOW() + INTERVAL '30 days') RETURNING id",
            (owner_id, "conv"),
        ).fetchone()
        conv_id = conv_row[0]
        conn.execute(
            "INSERT INTO message (conversation_id, owner_id, role, content) "
            "VALUES (%s, %s, %s, %s)",
            (conv_id, owner_id, "user", "hola"),
        )
        conn.execute(
            "INSERT INTO tool_execution (conversation_id, owner_id, turn_id,"
            " tool_name, arguments, result_count, duration_ms, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (conv_id, owner_id, 1, "buscar_declaraciones", "{}", 3, 10, "ok"),
        )
        conn.commit()

        conn.execute("DELETE FROM conversation WHERE id = %s", (conv_id,))
        conn.commit()

        messages = conn.execute(
            "SELECT COUNT(*) FROM message WHERE conversation_id = %s", (conv_id,)
        ).fetchone()[0]
        tools = conn.execute(
            "SELECT COUNT(*) FROM tool_execution WHERE conversation_id = %s", (conv_id,)
        ).fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM app_user").fetchone()[0]

    assert messages == 0
    assert tools == 0
    assert users >= 1
    _cleanup_user(pg_conn_str, username)


def test_drop_removes_tables(pg_conn_str: str) -> None:
    ensure_auth_memory_tables(pg_conn_str)
    drop_auth_memory_tables(pg_conn_str)
    assert EXPECTED_TABLES.isdisjoint(_table_names(pg_conn_str))
    ensure_auth_memory_tables(pg_conn_str)
