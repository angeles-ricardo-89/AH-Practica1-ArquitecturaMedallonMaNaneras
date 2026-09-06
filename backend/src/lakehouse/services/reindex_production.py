from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, LiteralString, cast

import psycopg

from lakehouse.config import Settings
from lakehouse.db.connection import pg_conn_str_with_timeouts
from lakehouse.db.index_metadata import store_index_metadata
from lakehouse.log_config import get_logger
from lakehouse.schemas.index_metadata import IndexMetadata
from lakehouse.services.index_metadata import build_corpus_hash

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__, layer="service")


def _conn_str_with_timeouts(conn_str: str) -> str:
    settings = Settings()
    return pg_conn_str_with_timeouts(
        conn_str,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


def reindex_corpus(
    source_conn_str: str,
    target_conn_str: str,
    embed_documents: Callable[[list[str]], list[list[float]]],
    *,
    provider: str,
    model: str,
    dimension: int,
    task_type: str,
    format_version: str,
    source_table: str = "gold.rag_corpus",
    target_table: str = "gold.rag_corpus",
    batch_size: int = 16,
) -> dict[str, int]:
    select_sql: LiteralString = cast(
        "LiteralString",
        f"""
        SELECT chunk_key, conference_id, conference_date, participant,
               chunk_text, payload, url, pregunta_activa
        FROM {source_table}
        """,
    )
    with psycopg.connect(_conn_str_with_timeouts(source_conn_str)) as conn:
        rows = conn.execute(select_sql).fetchall()

    total = len(rows)
    corpus_hash = build_corpus_hash([r[0] for r in rows])

    insert_sql: LiteralString = cast(
        "LiteralString",
        f"""
        INSERT INTO {target_table}
            (chunk_key, conference_id, conference_date, participant,
             chunk_text, payload, url, pregunta_activa, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chunk_key) DO UPDATE SET
            conference_id = EXCLUDED.conference_id,
            conference_date = EXCLUDED.conference_date,
            participant = EXCLUDED.participant,
            chunk_text = EXCLUDED.chunk_text,
            payload = EXCLUDED.payload,
            url = EXCLUDED.url,
            pregunta_activa = EXCLUDED.pregunta_activa,
            embedding = EXCLUDED.embedding
        """,
    )
    with psycopg.connect(_conn_str_with_timeouts(target_conn_str)) as conn:
        cur = conn.cursor()
        embedded = 0
        for start in range(0, total, batch_size):
            batch = rows[start : start + batch_size]
            vectors = embed_documents([r[4] for r in batch])
            for row, vector in zip(batch, vectors):
                cur.execute(
                    insert_sql,
                    (
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        vector,
                    ),
                )
                embedded += 1
        conn.commit()

    metadata = IndexMetadata(
        provider=provider,
        model=model,
        dimension=dimension,
        task_type=task_type,
        format_version=format_version,
        built_at=datetime.now(UTC).isoformat(),
        corpus_hash=corpus_hash,
    )
    store_index_metadata(target_conn_str, metadata)

    logger.info("Reindexacion productiva completada", total=total, embedded=embedded)
    return {"total": total, "embedded": embedded}
