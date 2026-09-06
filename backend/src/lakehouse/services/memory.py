from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from lakehouse.config import Settings
from lakehouse.db.connection import pg_conn_str_with_timeouts
from lakehouse.services.security import generate_public_id


def _conn_str_with_timeouts(conn_str: str) -> str:
    settings = Settings()
    return pg_conn_str_with_timeouts(
        conn_str,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


def create_conversation(
    pg_conn_str: str,
    owner_id: int,
    title: str,
    secret: str,
    retention_days: int = 30,
) -> str:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn, conn.transaction():
        row = conn.execute(
            "INSERT INTO conversation (owner_id, title, expires_at) "
            "VALUES (%s, %s, NOW() + (%s * INTERVAL '1 day')) RETURNING id",
            (owner_id, title, retention_days),
        ).fetchone()
        assert row is not None
        conv_id = row[0]
        public_id = generate_public_id(secret, conv_id)
        conn.execute(
            "UPDATE conversation SET public_id = %s WHERE id = %s",
            (public_id, conv_id),
        )
    return public_id


def list_conversations(pg_conn_str: str, owner_id: int) -> list[dict]:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        rows = conn.execute(
            "SELECT public_id, title, created_at, last_activity_at "
            "FROM conversation WHERE owner_id = %s AND expires_at > NOW() "
            "ORDER BY last_activity_at DESC",
            (owner_id,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "created_at": r[2],
            "last_activity_at": r[3],
        }
        for r in rows
    ]


def resolve_conversation_id(pg_conn_str: str, owner_id: int, public_id: str) -> int | None:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        row = conn.execute(
            "SELECT id FROM conversation WHERE public_id = %s AND owner_id = %s "
            "AND expires_at > NOW()",
            (public_id, owner_id),
        ).fetchone()
    return row[0] if row else None


def get_conversation(pg_conn_str: str, owner_id: int, public_id: str) -> dict | None:
    conv_id = resolve_conversation_id(pg_conn_str, owner_id, public_id)
    if conv_id is None:
        return None
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        title_row = conn.execute(
            "SELECT title FROM conversation WHERE id = %s", (conv_id,)
        ).fetchone()
        assert title_row is not None
        title = title_row[0]
        msgs = conn.execute(
            "SELECT role, content, created_at, model, total_tokens, latency_ms, sources "
            "FROM message "
            "WHERE conversation_id = %s ORDER BY created_at ASC, id ASC",
            (conv_id,),
        ).fetchall()
    return {
        "id": public_id,
        "title": title,
        "messages": [_message_dict(m) for m in msgs],
    }


def delete_conversation(pg_conn_str: str, owner_id: int, public_id: str) -> bool:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        row = conn.execute(
            "DELETE FROM conversation WHERE public_id = %s AND owner_id = %s RETURNING id",
            (public_id, owner_id),
        ).fetchone()
    return row is not None


def add_message(
    pg_conn_str: str,
    conversation_id: int,
    owner_id: int,
    role: str,
    content: str,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    sources: list[dict] | None = None,
    latency_ms: float | None = None,
) -> int:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        row = conn.execute(
            "INSERT INTO message (conversation_id, owner_id, role, content, model, "
            "prompt_tokens, completion_tokens, total_tokens, sources, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                conversation_id,
                owner_id,
                role,
                content,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                Jsonb(sources) if sources is not None else None,
                latency_ms,
            ),
        ).fetchone()
    assert row is not None
    return row[0]


def touch_conversation(pg_conn_str: str, conversation_id: int, retention_days: int = 30) -> None:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        conn.execute(
            "UPDATE conversation SET last_activity_at = NOW(), "
            "expires_at = NOW() + (%s * INTERVAL '1 day') WHERE id = %s",
            (retention_days, conversation_id),
        )


def _message_dict(row: tuple) -> dict:
    return {
        "role": row[0],
        "content": row[1],
        "created_at": row[2],
        "model": row[3],
        "total_tokens": row[4],
        "latency_ms": row[5],
        "sources": row[6] if row[6] is not None else [],
    }


def list_messages(pg_conn_str: str, conversation_id: int) -> list[dict]:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        rows = conn.execute(
            "SELECT role, content, created_at, model, total_tokens, latency_ms, sources "
            "FROM message "
            "WHERE conversation_id = %s ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
    return [_message_dict(r) for r in rows]


def add_tool_execution(
    pg_conn_str: str,
    conversation_id: int,
    owner_id: int,
    turn_id: int,
    tool_name: str,
    arguments: dict,
    result_count: int,
    duration_ms: int,
    status: str,
) -> None:
    with psycopg.connect(_conn_str_with_timeouts(pg_conn_str)) as conn:
        conn.execute(
            "INSERT INTO tool_execution (conversation_id, owner_id, turn_id, tool_name, "
            "arguments, result_count, duration_ms, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                conversation_id,
                owner_id,
                turn_id,
                tool_name,
                Jsonb(arguments),
                result_count,
                duration_ms,
                status,
            ),
        )
