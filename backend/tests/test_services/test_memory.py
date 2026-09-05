from __future__ import annotations

import psycopg
import pytest

from lakehouse.services.memory import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    resolve_conversation_id,
)

SECRET = "a" * 40


@pytest.fixture
def owner(pg_conn_str: str):
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "INSERT INTO app_user (username, password_hash) VALUES ('mem_user', 'x')"
        )
        conn.commit()
        oid = conn.execute(
            "SELECT id FROM app_user WHERE username = 'mem_user'"
        ).fetchone()[0]
    yield oid
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM app_user WHERE username = 'mem_user'")
        conn.commit()


def test_create_and_list(owner, pg_conn_str: str) -> None:
    pid = create_conversation(pg_conn_str, owner, "titulo", SECRET)
    assert pid
    items = list_conversations(pg_conn_str, owner)
    assert [i["id"] for i in items] == [pid]
    assert items[0]["title"] == "titulo"


def test_history_isolation(owner, pg_conn_str: str) -> None:
    a = create_conversation(pg_conn_str, owner, "A", SECRET)
    b = create_conversation(pg_conn_str, owner, "B", SECRET)
    conv_a_id = resolve_conversation_id(pg_conn_str, owner, a)
    add_message(pg_conn_str, conv_a_id, owner, "user", "secreto de A")
    detail_a = get_conversation(pg_conn_str, owner, a)
    detail_b = get_conversation(pg_conn_str, owner, b)
    assert [m["content"] for m in detail_a["messages"]] == ["secreto de A"]
    assert detail_b["messages"] == []


def test_delete_cascade(owner, pg_conn_str: str) -> None:
    pid = create_conversation(pg_conn_str, owner, "A", SECRET)
    conv_id = resolve_conversation_id(pg_conn_str, owner, pid)
    add_message(pg_conn_str, conv_id, owner, "user", "hola")
    assert delete_conversation(pg_conn_str, owner, pid) is True
    assert get_conversation(pg_conn_str, owner, pid) is None
    assert delete_conversation(pg_conn_str, owner, pid) is False


def test_cross_user_returns_none(owner, pg_conn_str: str) -> None:
    pid = create_conversation(pg_conn_str, owner, "A", SECRET)
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "INSERT INTO app_user (username, password_hash) VALUES ('other', 'x')"
        )
        conn.commit()
        other_id = conn.execute(
            "SELECT id FROM app_user WHERE username = 'other'"
        ).fetchone()[0]
    assert get_conversation(pg_conn_str, other_id, pid) is None
    assert resolve_conversation_id(pg_conn_str, other_id, pid) is None
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM app_user WHERE username = 'other'")
        conn.commit()


def test_retention_excludes_expired(owner, pg_conn_str: str) -> None:
    pid = create_conversation(pg_conn_str, owner, "A", SECRET)
    conv_id = resolve_conversation_id(pg_conn_str, owner, pid)
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "UPDATE conversation SET expires_at = NOW() - INTERVAL '1 day' WHERE id = %s",
            (conv_id,),
        )
        conn.commit()
    assert list_conversations(pg_conn_str, owner) == []
