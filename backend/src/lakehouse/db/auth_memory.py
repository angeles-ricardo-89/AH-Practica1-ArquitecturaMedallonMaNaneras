from __future__ import annotations

import psycopg

AUTH_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'demo',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation (
    id               BIGSERIAL PRIMARY KEY,
    public_id        TEXT UNIQUE,
    owner_id         BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    title            TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_owner
    ON conversation (owner_id, expires_at);

CREATE TABLE IF NOT EXISTS message (
    id                BIGSERIAL PRIMARY KEY,
    conversation_id   BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    owner_id          BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content           TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    model             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_conversation
    ON message (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tool_execution (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    owner_id        BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    turn_id         BIGINT NOT NULL,
    tool_name       TEXT NOT NULL,
    arguments       JSONB NOT NULL,
    result_count    INTEGER NOT NULL,
    duration_ms     INTEGER NOT NULL,
    status          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_execution_conversation
    ON tool_execution (conversation_id, created_at);
"""

DROP_AUTH_MEMORY_DDL = """
DROP TABLE IF EXISTS tool_execution;
DROP TABLE IF EXISTS message;
DROP TABLE IF EXISTS conversation;
DROP TABLE IF EXISTS app_user;
"""


def ensure_auth_memory_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(AUTH_MEMORY_DDL)
        conn.commit()


def drop_auth_memory_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(DROP_AUTH_MEMORY_DDL)
        conn.commit()
