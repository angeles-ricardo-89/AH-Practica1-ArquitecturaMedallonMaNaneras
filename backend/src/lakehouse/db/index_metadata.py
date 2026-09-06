from __future__ import annotations

from datetime import datetime

import psycopg

from lakehouse.config import Settings
from lakehouse.db.connection import pg_conn_str_with_timeouts
from lakehouse.schemas.index_metadata import IndexMetadata

INDEX_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS index_metadata (
    provider       TEXT PRIMARY KEY,
    model          TEXT NOT NULL,
    dimension      INTEGER NOT NULL,
    task_type      TEXT NOT NULL,
    format_version TEXT NOT NULL,
    built_at       TIMESTAMPTZ NOT NULL,
    corpus_hash    TEXT NOT NULL
);
"""

DROP_INDEX_METADATA_DDL = """
DROP TABLE IF EXISTS index_metadata;
"""


def _conn_str_with_timeouts(conn_str: str) -> str:
    settings = Settings()
    return pg_conn_str_with_timeouts(
        conn_str,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


def ensure_index_metadata_tables(conn_str: str) -> None:
    with psycopg.connect(_conn_str_with_timeouts(conn_str)) as conn:
        conn.execute(INDEX_METADATA_DDL)
        conn.commit()


def drop_index_metadata_tables(conn_str: str) -> None:
    with psycopg.connect(_conn_str_with_timeouts(conn_str)) as conn:
        conn.execute(DROP_INDEX_METADATA_DDL)
        conn.commit()


def store_index_metadata(conn_str: str, metadata: IndexMetadata) -> None:
    ensure_index_metadata_tables(conn_str)
    with psycopg.connect(_conn_str_with_timeouts(conn_str)) as conn:
        conn.execute(
            """
            INSERT INTO index_metadata
                (provider, model, dimension, task_type, format_version, built_at, corpus_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider) DO UPDATE SET
                model = EXCLUDED.model,
                dimension = EXCLUDED.dimension,
                task_type = EXCLUDED.task_type,
                format_version = EXCLUDED.format_version,
                built_at = EXCLUDED.built_at,
                corpus_hash = EXCLUDED.corpus_hash
            """,
            (
                metadata.provider,
                metadata.model,
                metadata.dimension,
                metadata.task_type,
                metadata.format_version,
                metadata.built_at,
                metadata.corpus_hash,
            ),
        )
        conn.commit()


def read_index_metadata(conn_str: str) -> IndexMetadata | None:
    ensure_index_metadata_tables(conn_str)
    with psycopg.connect(_conn_str_with_timeouts(conn_str)) as conn:
        row = conn.execute(
            """
            SELECT provider, model, dimension, task_type, format_version, built_at, corpus_hash
            FROM index_metadata
            ORDER BY provider
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    built_at = row[5].isoformat() if isinstance(row[5], datetime) else str(row[5])
    return IndexMetadata(
        provider=row[0],
        model=row[1],
        dimension=row[2],
        task_type=row[3],
        format_version=row[4],
        built_at=built_at,
        corpus_hash=row[6],
    )
