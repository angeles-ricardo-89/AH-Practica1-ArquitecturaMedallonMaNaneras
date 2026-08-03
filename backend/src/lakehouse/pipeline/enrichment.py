from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, cast

import httpx
import psycopg

from lakehouse.log_config import ProgressReporter, get_logger
from lakehouse.pipeline.interrupt import interrupt_state
from lakehouse.services.token_estimator import estimate_tokens

logging.getLogger("httpx").setLevel(logging.WARNING)


if TYPE_CHECKING:
    from lakehouse.schemas.gold import WindowRecord
    from lakehouse.schemas.silver import InterventionRecord

logger = get_logger(__name__, layer="gold")

WINDOW_MAX_TOKENS = 1600
WINDOW_OVERLAP_TOKENS = 200
MIN_CHUNK_LENGTH = 50


def build_embedding_payload(
    record: WindowRecord,
    conference_date: str,
) -> str:
    return (
        f"Contexto: Conferencia del {conference_date}\n"
        f"Participante: {record.participant}\n"
        f"Pregunta activa: {record.pregunta_activa}\n"
        f"Respuesta: {record.text}"
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
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be < max_tokens")

    max_single = max((estimate_tokens(iv.text) for iv in interventions), default=0)
    if max_single > max_tokens:
        logger.warning(
            "Intervención supera max_tokens, se alojará en ventana propia",
            tokens=max_single,
            max_tokens=max_tokens,
        )

    windows: list[list[InterventionRecord]] = []
    current: list[InterventionRecord] = []
    current_tokens = 0
    overlap_buf: list[InterventionRecord] = []

    for iv in interventions:
        t = estimate_tokens(iv.text)
        if t > max_tokens and current:
            windows.append(current)
            current, current_tokens = [], 0
        elif current and current_tokens + t > max_tokens:
            windows.append(current)
            overlap_buf, acc = [], 0
            for it in reversed(current):
                it_tokens = estimate_tokens(it.text)
                if it_tokens > max_tokens:
                    continue
                acc += it_tokens
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
    record: WindowRecord,
    ollama_base_url: str,
    ollama_model: str,
) -> list[float] | None:
    try:
        return embed_text(record.text, ollama_base_url, ollama_model)
    except (ConnectionError, ValueError) as e:
        logger.warning(
            "embed_text falló",
            error=str(e),
            chunk_key=record.chunk_key,
        )
        return None


def _store_gold(
    cur: Any,
    record: WindowRecord,
    effective_date: str,
    embedding: list[float],
) -> None:
    payload = build_embedding_payload(record, effective_date)
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
            record.chunk_key,
            record.conference_id,
            effective_date,
            record.participant,
            record.text,
            payload,
            record.url,
            record.pregunta_activa,
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
    windows: list[WindowRecord],
    conference_date: str | None,
    pg_conn_str: str,
    ollama_base_url: str,
    ollama_model: str,
    workers: int = 1,
) -> dict:
    total = len(windows)
    embedded = 0
    failed = 0

    if not windows:
        logger.info("No hay intervenciones para enriquecer")
        return {"total": 0, "embedded": 0, "failed_to_embed": 0}

    logger.info("Iniciando enriquecimiento Gold", total_intervenciones=total, modelo=ollama_model)

    workers = max(1, workers)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        reporter = ProgressReporter(total=total, label="gold")
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures: dict[Future, tuple[WindowRecord, str]] = {}
                for record in windows:
                    if interrupt_state.requested():
                        break
                    effective_date = conference_date or record.conference_date
                    if not effective_date:
                        logger.error(
                            "Intervención sin fecha de conferencia, omitida",
                            chunk_key=record.chunk_key,
                        )
                        failed += 1
                        reporter.tick()
                        continue
                    future = pool.submit(
                        _embed_one,
                        record,
                        ollama_base_url,
                        ollama_model,
                    )
                    futures[future] = (record, effective_date)

                for future in as_completed(futures):
                    record, effective_date = futures[future]
                    embedding = future.result()
                    if embedding is None:
                        logger.error(
                            "Error al generar embedding",
                            chunk_key=record.chunk_key,
                        )
                        failed += 1
                    else:
                        logger.info(
                            "Embedding generado para chunk",
                            chunk_key=record.chunk_key,
                            participant=record.participant,
                            dim=len(embedding),
                        )
                        try:
                            _store_gold(cur, record, effective_date, embedding)
                        except psycopg.errors.UniqueViolation:
                            logger.warning(
                                "Chunk duplicado en Gold, omitido",
                                chunk_key=record.chunk_key,
                            )
                        embedded += 1
                    reporter.tick()
        else:
            for record in windows:
                if interrupt_state.requested():
                    break
                effective_date = conference_date or record.conference_date
                if not effective_date:
                    logger.error(
                        "Intervención sin fecha de conferencia, omitida",
                        chunk_key=record.chunk_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                embedding = _embed_one(record, ollama_base_url, ollama_model)
                if embedding is None:
                    logger.error(
                        "Error al generar embedding",
                        chunk_key=record.chunk_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                logger.info(
                    "Embedding generado para chunk",
                    chunk_key=record.chunk_key,
                    participant=record.participant,
                    dim=len(embedding),
                )
                try:
                    _store_gold(cur, record, effective_date, embedding)
                except psycopg.errors.UniqueViolation:
                    logger.warning(
                        "Chunk duplicado en Gold, omitido",
                        chunk_key=record.chunk_key,
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

    return {"total": total, "embedded": embedded, "failed_to_embed": failed}


def _parse_pgvector_to_list(value: object) -> list[float]:
    """Convierte un embedding a lista de floats.

    pgvector no esta registrado en psycopg, asi que la columna ``vector`` llega como
    string de la forma ``[0.1,0.2,...]``. Si ya viene como lista/tuple (tests), se
    devuelve tal cual.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if not (stripped.startswith("[") and stripped.endswith("]")):
            raise ValueError(f"Formato de embedding invalido: {value!r}")
        return [float(x) for x in stripped[1:-1].split(",")]
    if isinstance(value, (list, tuple)):
        seq = cast("list[float] | tuple[float, ...]", value)
        return [float(x) for x in seq]
    raise ValueError(f"Tipo de embedding no soportado: {type(value).__name__}")


def _compute_umap_3d(pg_conn_str: str) -> int:  # noqa: PLR0911
    try:
        import numpy as np  # noqa: PLC0415
        from umap import UMAP  # noqa: PLC0415
    except ImportError:
        logger.warning("umap-learn no disponible, omitiendo reduccion 3D")
        return 0

    try:
        from lakehouse.db.observability_conn import add_embedding_3d_column  # noqa: PLC0415

        add_embedding_3d_column(pg_conn_str)
    except Exception:
        logger.exception("No se pudo asegurar columna embedding_3d, omitiendo UMAP")
        return 0

    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute("SELECT chunk_key, embedding FROM gold.rag_corpus")
            rows = cur.fetchall()
    except Exception:
        logger.exception("Error leyendo embeddings para UMAP")
        return 0

    if len(rows) < 4:
        logger.warning("Muy pocos chunks para UMAP (< 4), omitiendo")
        return 0

    clean_rows = [r for r in rows if r[1] is not None]
    if len(clean_rows) != len(rows):
        logger.warning(
            "Se omitieron chunks con embedding nulo",
            omitidos=len(rows) - len(clean_rows),
        )
    if len(clean_rows) < 4:
        logger.warning("Muy pocos chunks validos para UMAP (< 4), omitiendo")
        return 0

    chunk_keys = [r[0] for r in clean_rows]
    try:
        vectors = np.array([_parse_pgvector_to_list(r[1]) for r in clean_rows], dtype=np.float64)
    except (ValueError, TypeError):
        logger.exception("Error convirtiendo embeddings a matriz numpy")
        return 0

    try:
        n_neighbors = min(15, len(clean_rows) - 1)
        reducer = UMAP(n_components=3, random_state=42, n_neighbors=n_neighbors)
        coords = np.asarray(reducer.fit_transform(vectors))
    except Exception:
        logger.exception("UMAP fallo")
        return 0

    updated = 0
    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            for key, coord in zip(chunk_keys, coords):
                cur.execute(
                    "UPDATE gold.rag_corpus SET embedding_3d = ARRAY[%s, %s, %s] WHERE chunk_key = %s",
                    (float(coord[0]), float(coord[1]), float(coord[2]), key),
                )
                updated += 1
            conn.commit()
    except Exception:
        logger.exception("Error guardando coordenadas UMAP")
        return 0

    logger.info("UMAP 3D completado", chunks=updated)
    return updated
