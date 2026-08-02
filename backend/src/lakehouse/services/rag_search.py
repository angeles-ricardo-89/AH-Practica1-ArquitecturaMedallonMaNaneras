from __future__ import annotations

import logging
import time
from typing import Any, LiteralString, cast

import httpx
import psycopg

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import MIN_CHUNK_LENGTH
from lakehouse.schemas.chat import SourceChunk

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = get_logger(__name__, layer="service")


def _get_pgvector_connection_string(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _call_ollama_embed(url: str, model: str, text: str) -> list[float]:
    with httpx.Client() as client:
        resp = client.post(
            url,
            json={"model": model, "input": text},
            timeout=30,
        )
    if resp.status_code != 200:
        raise httpx.HTTPStatusError(
            f"Ollama returned status {resp.status_code}",
            request=resp.request,
            response=resp,
        )
    data = resp.json()
    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise ValueError("Ollama returned empty embeddings")
    return embeddings[0]


def _embed_query(
    query: str,
    base_url: str,
    model: str,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> list[float]:
    url = f"{base_url}/api/embed"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return _call_ollama_embed(url, model, query)
        except ValueError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Ollama embedding attempt %d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    e,
                    delay,
                )
                time.sleep(delay)

    raise ConnectionError(f"Ollama embedding failed after {max_retries} retries") from last_error


def _rows_to_results(rows: list) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows:
        embedding_3d_raw = row[7] if len(row) > 7 else None
        if embedding_3d_raw:
            embedding_3d = (
                list(embedding_3d_raw) if isinstance(embedding_3d_raw, (list, tuple)) else None
            )
        else:
            embedding_3d = None
        results.append(
            {
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
                "embedding_3d": embedding_3d,
            }
        )
    return results


def search_gold_corpus_from_vector(
    query_vector: list[float],
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity,
                    embedding_3d
                FROM gold.rag_corpus
                WHERE LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(query_sql, (embedding_str, embedding_str, top_k))
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector")
        raise RuntimeError("Search unavailable: database query failed") from e

    results = _rows_to_results(rows)
    logger.info("Busqueda completada por vector", resultados=len(results))
    return results


def search_gold_corpus(
    query: str,
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    try:
        query_embedding = _embed_query(query, settings.ollama_base_url, settings.ollama_embed_model)
    except (ConnectionError, ValueError) as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("Search unavailable: embedding generation failed") from e

    results = search_gold_corpus_from_vector(query_embedding, top_k, settings)
    logger.info("Busqueda completada", query=query[:100], resultados=len(results))
    return results


def search_with_date_filter(
    query_vector: list[float],
    top_k: int,
    fecha_inicio: str,
    fecha_fin: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity,
                    embedding_3d
                FROM gold.rag_corpus
                WHERE conference_date BETWEEN %s::date AND %s::date
                  AND LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(
                query_sql,
                (embedding_str, fecha_inicio, fecha_fin, embedding_str, top_k),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector con filtro de fechas")
        raise RuntimeError("Search unavailable: database query failed") from e

    results = _rows_to_results(rows)

    logger.info(
        "Busqueda con filtro de fechas completada",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resultados=len(results),
    )
    return results


def search_sources(query: str, top_k: int) -> list[SourceChunk]:
    results = search_gold_corpus(query, top_k)
    logger.info("Busqueda de fuentes completada", query=query[:100], resultados=len(results))
    return [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
            embedding_3d=r.get("embedding_3d"),
        )
        for r in results
    ]
