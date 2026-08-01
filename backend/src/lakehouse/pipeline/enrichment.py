from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

import httpx
import psycopg

from lakehouse.log_config import ProgressReporter, get_logger
from lakehouse.services.token_estimator import estimate_tokens

logging.getLogger("httpx").setLevel(logging.WARNING)


if TYPE_CHECKING:
    from lakehouse.schemas.gold import WindowRecord  # noqa: F401
    from lakehouse.schemas.silver import InterventionRecord

logger = get_logger(__name__, layer="gold")

WINDOW_MAX_TOKENS = 1600
WINDOW_OVERLAP_TOKENS = 200
MIN_CHUNK_LENGTH = 50


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


def build_embedding_text(intervention: InterventionRecord) -> str:
    pregunta = intervention.pregunta_activa
    if pregunta:
        return f"P: {pregunta}\nR: {intervention.text}"
    return f"R: {intervention.text}"


def build_window_text(interventions: list[InterventionRecord]) -> str:
    blocks = []
    for iv in interventions:
        if iv.pregunta_activa:
            blocks.append(f"P: {iv.pregunta_activa}\n{iv.participant}: {iv.text}")
        else:
            blocks.append(f"{iv.participant}: {iv.text}")
    return "\n\n".join(blocks)


def build_window_key(conference_id: str, window_index: int, window_text: str) -> str:
    h = hashlib.sha256(window_text.encode()).hexdigest()[:6]
    return f"{conference_id}_w{window_index:03d}_{h}"


def build_windows(
    interventions: list[InterventionRecord],
    max_tokens: int = WINDOW_MAX_TOKENS,
    overlap_tokens: int = WINDOW_OVERLAP_TOKENS,
) -> list[list[InterventionRecord]]:
    windows: list[list[InterventionRecord]] = []
    current: list[InterventionRecord] = []
    current_tokens = 0
    overlap_buf: list[InterventionRecord] = []

    for iv in interventions:
        t = estimate_tokens(iv.text)
        if current and current_tokens + t > max_tokens:
            windows.append(current)
            overlap_buf, acc = [], 0
            for it in reversed(current):
                acc += estimate_tokens(it.text)
                overlap_buf.insert(0, it)
                if acc >= overlap_tokens:
                    break
            current, current_tokens = list(overlap_buf), acc
        current.append(iv)
        current_tokens += t
    if current:
        windows.append(current)
    return windows


def _embed_one(
    intervention: InterventionRecord,
    effective_date: str,
    ollama_base_url: str,
    ollama_model: str,
) -> tuple[str, list[float] | None]:
    payload = build_embedding_payload(intervention, effective_date)
    embedding_text = build_embedding_text(intervention)
    try:
        embedding = embed_text(embedding_text, ollama_base_url, ollama_model)
    except (ConnectionError, ValueError) as e:
        logger.warning(
            "embed_text falló",
            error=str(e),
            intervention_key=intervention.intervention_key,
        )
        return payload, None
    return payload, embedding


def _store_gold(
    cur: Any,
    intervention: InterventionRecord,
    effective_date: str,
    payload: str,
    embedding: list[float],
) -> None:
    cur.execute(
        """
            INSERT INTO gold.rag_corpus
                (chunk_key, conference_id, conference_date, participant, chunk_text, payload, url, pregunta_activa, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_key) DO UPDATE SET
                conference_id = EXCLUDED.conference_id,
                conference_date = EXCLUDED.conference_date,
                payload = EXCLUDED.payload,
                url = EXCLUDED.url,
                pregunta_activa = EXCLUDED.pregunta_activa
            """,
        (
            intervention.intervention_key,
            intervention.conference_id,
            effective_date,
            intervention.participant,
            intervention.text,
            payload,
            intervention.url,
            intervention.pregunta_activa,
            embedding,
        ),
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
    return [float(x) for x in embeddings[0]]


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


def drop_gold_tables(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS gold.rag_corpus")
        conn.commit()


def ensure_gold_tables(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS gold")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold.rag_corpus (
                chunk_key VARCHAR PRIMARY KEY,
                conference_id VARCHAR NOT NULL,
                conference_date DATE NOT NULL,
                participant VARCHAR NOT NULL,
                chunk_text TEXT NOT NULL,
                payload TEXT NOT NULL,
                url VARCHAR DEFAULT '',
                embedding vector(768),
                ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            ALTER TABLE gold.rag_corpus
            ADD COLUMN IF NOT EXISTS conference_id VARCHAR
        """)
        cur.execute("""
            ALTER TABLE gold.rag_corpus
            ADD COLUMN IF NOT EXISTS url VARCHAR DEFAULT ''
        """)
        cur.execute("""
            ALTER TABLE gold.rag_corpus
            ADD COLUMN IF NOT EXISTS pregunta_activa VARCHAR DEFAULT ''
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
    conference_date: str | None,
    pg_conn_str: str,
    ollama_base_url: str,
    ollama_model: str,
    workers: int = 1,
) -> dict:
    total = len(interventions)
    embedded = 0
    failed = 0

    if not interventions:
        logger.info("No hay intervenciones para enriquecer")
        return {"total": 0, "embedded": 0, "failed": 0}

    logger.info("Iniciando enriquecimiento Gold", total_intervenciones=total, modelo=ollama_model)

    workers = max(1, workers)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        reporter = ProgressReporter(total=total, label="gold")
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures: dict[Future, tuple[InterventionRecord, str]] = {}
                for intervention in interventions:
                    effective_date = conference_date or intervention.conference_date
                    if not effective_date:
                        logger.error(
                            "Intervención sin fecha de conferencia, omitida",
                            intervention_key=intervention.intervention_key,
                        )
                        failed += 1
                        reporter.tick()
                        continue
                    future = pool.submit(
                        _embed_one,
                        intervention,
                        effective_date,
                        ollama_base_url,
                        ollama_model,
                    )
                    futures[future] = (intervention, effective_date)

                for future in as_completed(futures):
                    intervention, effective_date = futures[future]
                    payload, embedding = future.result()
                    if embedding is None:
                        logger.error(
                            "Error al generar embedding",
                            intervention_key=intervention.intervention_key,
                        )
                        failed += 1
                    else:
                        logger.info(
                            "Embedding generado para intervención",
                            intervention_key=intervention.intervention_key,
                            participant=intervention.participant,
                            dim=len(embedding),
                        )
                        try:
                            _store_gold(cur, intervention, effective_date, payload, embedding)
                        except psycopg.errors.UniqueViolation:
                            logger.warning(
                                "Chunk duplicado en Gold, omitido",
                                chunk_key=intervention.intervention_key,
                            )
                        embedded += 1
                    reporter.tick()
        else:
            for intervention in interventions:
                effective_date = conference_date or intervention.conference_date
                if not effective_date:
                    logger.error(
                        "Intervención sin fecha de conferencia, omitida",
                        intervention_key=intervention.intervention_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                payload, embedding = _embed_one(
                    intervention, effective_date, ollama_base_url, ollama_model
                )
                if embedding is None:
                    logger.error(
                        "Error al generar embedding",
                        intervention_key=intervention.intervention_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                logger.info(
                    "Embedding generado para intervención",
                    intervention_key=intervention.intervention_key,
                    participant=intervention.participant,
                    dim=len(embedding),
                )
                try:
                    _store_gold(cur, intervention, effective_date, payload, embedding)
                except psycopg.errors.UniqueViolation:
                    logger.warning(
                        "Chunk duplicado en Gold, omitido",
                        chunk_key=intervention.intervention_key,
                    )
                embedded += 1
                reporter.tick()
        reporter.finish()
        conn.commit()
        logger.info(
            "Enriquecimiento Gold completado",
            embedded=embedded,
            failed=failed,
            total=total,
        )

    return {"total": total, "embedded": embedded, "failed": failed}
