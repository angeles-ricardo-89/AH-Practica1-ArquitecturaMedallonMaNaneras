from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import psycopg

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
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

    raise ConnectionError(
        f"Ollama embedding failed after {max_retries} retries"
    ) from last_error


def search_gold_corpus(
    query: str,
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)

    try:
        query_embedding = _embed_query(query, settings.ollama_base_url, settings.ollama_embed_model)
    except (ConnectionError, ValueError) as e:
        logger.error("No se pudo generar embedding para la consulta", error=str(e))
        raise RuntimeError("Search unavailable: embedding generation failed") from e

    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT conference_date, participant, chunk_text,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding_str, embedding_str, top_k),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.error("Error al consultar pgvector", error=str(e))
        raise RuntimeError("Search unavailable: database query failed") from e

    results = []
    for row in rows:
        results.append({
            "conference_date": str(row[0]),
            "participant": row[1],
            "chunk_text": row[2],
            "similarity": float(row[3]),
        })

    logger.info("Busqueda completada", query=query[:100], resultados=len(results))
    return results


def search_sources(query: str, top_k: int) -> list[SourceChunk]:
    results = search_gold_corpus(query, top_k)
    return [
        SourceChunk(
            conference_date=r["conference_date"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
        )
        for r in results
    ]
