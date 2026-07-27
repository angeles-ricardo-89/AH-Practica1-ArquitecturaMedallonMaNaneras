from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx
import psycopg

if TYPE_CHECKING:
    from lakehouse.schemas.silver import InterventionRecord

logger = logging.getLogger(__name__)


def build_embedding_payload(
    intervention: InterventionRecord,
    conference_date: str,
) -> str:
    return (
        f"Contexto: Conferencia del {conference_date}\n"
        f"Participante: {intervention.participant}\n"
        f"Pregunta activa: {intervention.pregunta_activa}\n"
        f"Respuesta: {intervention.text}"
    )


def get_pgvector_connection_string(
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


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


def embed_text(
    text: str,
    base_url: str,
    model: str,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> list[float]:
    url = f"{base_url}/api/embed"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return _call_ollama_embed(url, model, text)
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


def ensure_gold_tables(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS gold")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold.rag_corpus (
                chunk_key VARCHAR PRIMARY KEY,
                conference_date DATE NOT NULL,
                participant VARCHAR NOT NULL,
                chunk_text TEXT NOT NULL,
                payload TEXT NOT NULL,
                embedding vector(768),
                ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rag_corpus_conference_date
            ON gold.rag_corpus (conference_date)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rag_corpus_participant
            ON gold.rag_corpus (participant)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rag_corpus_embedding_hnsw
            ON gold.rag_corpus
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 200)
        """)
        conn.commit()


def enrich_interventions(
    interventions: list[InterventionRecord],
    conference_date: str,
    pg_conn_str: str,
    ollama_base_url: str,
    ollama_model: str,
) -> dict:
    total = len(interventions)
    embedded = 0
    failed = 0

    if not interventions:
        return {"total": 0, "embedded": 0, "failed": 0}

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        for intervention in interventions:
            payload = build_embedding_payload(intervention, conference_date)
            try:
                embedding = embed_text(payload, ollama_base_url, ollama_model)
            except (ConnectionError, ValueError):
                logger.exception(
                    "Failed to embed %s",
                    intervention.intervention_key,
                )
                failed += 1
                continue

            try:
                cur.execute(
                    """
                    INSERT INTO gold.rag_corpus
                        (chunk_key, conference_date, participant, chunk_text, payload, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_key) DO NOTHING
                    """,
                    (
                        intervention.intervention_key,
                        conference_date,
                        intervention.participant,
                        intervention.text,
                        payload,
                        embedding,
                    ),
                )
            except psycopg.errors.UniqueViolation:
                logger.warning(
                    "Duplicate chunk_key %s, skipping",
                    intervention.intervention_key,
                )
            embedded += 1
        conn.commit()

    return {"total": total, "embedded": embedded, "failed": failed}
