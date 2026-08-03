from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
import numpy as np
import psycopg
import umap
from hdbscan import HDBSCAN
from sklearn.preprocessing import normalize

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="gold")


def _build_pg_conn_str(settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def ensure_clustering_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_id INTEGER NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_pertenencia REAL NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS clustering_run_id UUID NULL
    """)
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_cluster_pertenencia_range'
            ) THEN
                ALTER TABLE gold.rag_corpus
                ADD CONSTRAINT chk_cluster_pertenencia_range
                CHECK (cluster_pertenencia IS NULL OR (cluster_pertenencia >= 0.0 AND cluster_pertenencia <= 1.0));
            END IF;
        END $$;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.clustering_runs (
            run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            status              VARCHAR NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running','completed','failed','partial')),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at         TIMESTAMPTZ,
            input_count         INTEGER NOT NULL DEFAULT 0,
            valid_count         INTEGER NOT NULL DEFAULT 0,
            rejected_count      INTEGER NOT NULL DEFAULT 0,
            cluster_count       INTEGER NOT NULL DEFAULT 0,
            noise_count         INTEGER NOT NULL DEFAULT 0,
            labeled_cluster_count INTEGER NOT NULL DEFAULT 0,
            failed_label_count  INTEGER NOT NULL DEFAULT 0,
            corpus_fingerprint  VARCHAR NOT NULL DEFAULT '',
            parameters_hash     VARCHAR NOT NULL DEFAULT '',
            embedding_model     VARCHAR NOT NULL DEFAULT '',
            umap_parameters     JSONB NOT NULL DEFAULT '{}',
            hdbscan_parameters  JSONB NOT NULL DEFAULT '{}',
            labeling_parameters JSONB NOT NULL DEFAULT '{}',
            error_message       TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.cluster_labels (
            clustering_run_id   UUID NOT NULL REFERENCES gold.clustering_runs(run_id),
            cluster_id          INTEGER NOT NULL CHECK (cluster_id >= 0),
            cluster_label       VARCHAR,
            label_status        VARCHAR NOT NULL DEFAULT 'pending'
                                CHECK (label_status IN ('pending','completed','failed')),
            sample_size         INTEGER NOT NULL DEFAULT 0,
            sample_chunk_keys   TEXT[] NOT NULL DEFAULT '{}',
            model_name          VARCHAR DEFAULT '',
            prompt_version      VARCHAR DEFAULT '',
            attempt_count       INTEGER NOT NULL DEFAULT 0,
            error_message       TEXT DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (clustering_run_id, cluster_id)
        )
    """)
    conn.commit()


def validate_embeddings(
    keys: list[str],
    embeddings: list[np.ndarray | None],
    expected_dim: int,
) -> tuple[list[str], np.ndarray, list[tuple[str, str]]]:
    valid_keys: list[str] = []
    valid_vecs: list[np.ndarray] = []
    rejected: list[tuple[str, str]] = []

    for key, embedding in zip(keys, embeddings):
        if embedding is None:
            rejected.append((key, "null"))
            continue
        if not isinstance(embedding, np.ndarray):
            vec = np.array(embedding, dtype=np.float64)
        else:
            vec = embedding
        if vec.shape[0] != expected_dim:
            rejected.append((key, f"dimension:{vec.shape[0]}"))
            continue
        if not np.isfinite(vec).all():
            rejected.append((key, "non_finite"))
            continue
        if np.linalg.norm(vec) == 0:
            rejected.append((key, "zero_norm"))
            continue
        if np.all(vec == 0):
            rejected.append((key, "zero_vector"))
            continue
        valid_keys.append(key)
        valid_vecs.append(vec)

    arr = (
        np.array(valid_vecs, dtype=np.float64)
        if valid_vecs
        else np.empty((0, expected_dim), dtype=np.float64)
    )
    return valid_keys, arr, rejected


def compute_corpus_fingerprint(
    chunk_keys: list[str],
    embeddings: np.ndarray,
    model: str,
) -> str:
    data = json.dumps(
        {
            "keys": sorted(chunk_keys),
            "embedding_hash": hashlib.sha256(embeddings.tobytes()).hexdigest(),
            "model": model,
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def compute_parameters_hash(params: dict) -> str:
    data = json.dumps(params, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


_EMBEDDING_RE = re.compile(r"\[([-\d., eE+]+)\]")


def _parse_pgvector_to_list(pg_str: str | None) -> list[float] | None:
    if pg_str is None:
        return None
    match = _EMBEDDING_RE.search(str(pg_str))
    if not match:
        return None
    try:
        raw = match.group(1)
        if not raw.strip():
            return None
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    except (ValueError, OverflowError):
        return None


def load_embeddings(pg_conn_str: str) -> tuple[list[str], np.ndarray, list[str]]:
    raw_keys: list[str] = []
    raw_vecs: list[np.ndarray] = []
    null_keys: list[str] = []

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute("SELECT chunk_key, embedding::text FROM gold.rag_corpus")
        for row in cur:
            vec = _parse_pgvector_to_list(row[1])
            if vec is None:
                null_keys.append(row[0])
                continue
            raw_keys.append(row[0])
            raw_vecs.append(np.array(vec, dtype=np.float64))

    if raw_vecs:
        embeddings = np.array(raw_vecs, dtype=np.float64)
    else:
        embeddings = np.empty((0, 0), dtype=np.float64)
    return raw_keys, embeddings, null_keys


def run_umap_clustering(embeddings: np.ndarray, settings) -> np.ndarray:
    reducer = umap.UMAP(
        n_components=settings.umap_clustering_n_components,
        n_neighbors=min(settings.umap_clustering_n_neighbors, len(embeddings) - 1),
        min_dist=settings.umap_clustering_min_dist,
        metric=settings.umap_clustering_metric,
        random_state=settings.umap_clustering_random_state,
    )
    return reducer.fit_transform(embeddings)


def run_hdbscan(
    umap_vectors: np.ndarray,
    settings,
) -> tuple[np.ndarray, np.ndarray]:
    clusterer = HDBSCAN(
        min_cluster_size=min(settings.hdbscan_min_cluster_size, len(umap_vectors) // 2),
        min_samples=min(settings.hdbscan_min_samples, len(umap_vectors) - 1),
        metric=settings.hdbscan_metric,
        algorithm=settings.hdbscan_algorithm,
        cluster_selection_method=settings.hdbscan_cluster_selection_method,
        core_dist_n_jobs=settings.hdbscan_n_jobs,
    )
    labels = clusterer.fit_predict(umap_vectors)
    probs = clusterer.probabilities_.astype(np.float64)
    probs[labels == -1] = 0.0
    return labels, probs


def persist_cluster_assignments(
    pg_conn_str: str,
    run_id: str,
    assignments: list[tuple[str, int, float]],
) -> None:
    if not assignments:
        return
    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TEMP TABLE _cluster_assignments (chunk_key VARCHAR, cluster_id INT, pertenencia REAL) ON COMMIT DROP"
        )
        with cur.copy("COPY _cluster_assignments FROM STDIN") as copy:
            for chunk_key, cid, membership in assignments:
                copy.write_row((chunk_key, cid, membership))
        cur.execute(
            """
            UPDATE gold.rag_corpus AS g
            SET cluster_id = a.cluster_id,
                cluster_pertenencia = a.pertenencia,
                clustering_run_id = %s
            FROM _cluster_assignments AS a
            WHERE g.chunk_key = a.chunk_key
        """,
            (run_id,),
        )
        conn.commit()


def select_representative_chunks(
    chunks: list[dict],
    cluster_id: int,
    k: int = 5,
) -> list[dict]:
    if cluster_id < 0:
        return []
    cluster_chunks = [c for c in chunks if c.get("cluster_id") == cluster_id]
    cluster_chunks.sort(key=lambda c: (-c.get("cluster_pertenencia", 0.0), c["chunk_key"]))
    return cluster_chunks[:k]


_LABEL_RE = re.compile(r"\s+")
_LABEL_PREFIXES = [
    "etiqueta:",
    "tema:",
    "categoria:",
    "respuesta:",
    "label:",
    "category:",
    "topic:",
]


def validate_label(raw_label: str) -> tuple[str | None, str | None]:
    if not raw_label or not raw_label.strip():
        return None, "empty"

    label = raw_label.strip()

    lines = [line for line in label.split("\n") if line.strip()]
    if len(lines) > 1:
        return None, "multiline"

    label = _LABEL_RE.sub(" ", label)
    label = label.strip('"').strip("'")
    label = label.rstrip(".")

    lower = label.lower()
    for prefix in _LABEL_PREFIXES:
        if lower.startswith(prefix):
            label = label[len(prefix) :].strip()
            break

    if not label:
        return None, "empty_after_normalize"

    words = label.split()
    if len(words) > 4:
        return None, "too_many_words"

    if not label.strip():
        return None, "empty_after_normalize"

    return label.strip(), None


def load_prompt_template(version: str = "v1") -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    prompt_path = prompt_dir / f"cluster_label_{version}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def format_labeling_prompt(
    prompt_template: str,
    samples: list[dict],
    max_chars: int = 1500,
) -> str:
    texts = []
    for chunk in samples:
        text = chunk.get("chunk_text", "")
        if len(text) > max_chars:
            text = text[:max_chars]
        texts.append(f"- {text}")
    return prompt_template.replace("{textos_formateados}", "\n".join(texts))


def generate_label(
    prompt: str,
    base_url: str,
    model: str,
    max_tokens: int = 100,
    timeout: int = 30,
) -> str:
    response = httpx.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    raw = data["choices"][0]["message"]["content"].strip()
    if not raw:
        raise ValueError("empty_response")
    return raw


def label_clusters(
    pg_conn_str: str,
    run_id: str,
    cluster_ids: list[int],
    chunks: list[dict],
    settings,
) -> tuple[int, int]:
    prompt_template = load_prompt_template(settings.cluster_label_prompt_version)

    completed = 0
    failed = 0

    for cid in cluster_ids:
        if cid < 0:
            continue

        samples = select_representative_chunks(
            chunks,
            cid,
            k=settings.k_hdbscan_sampling,
        )
        if not samples:
            continue

        prompt = format_labeling_prompt(
            prompt_template,
            samples,
            max_chars=settings.cluster_label_max_chars_per_chunk,
        )

        label = None
        error_msg = None
        total_attempts = 0

        for attempt in range(settings.cluster_label_max_retries + 1):
            total_attempts = attempt + 1
            try:
                raw = generate_label(
                    prompt,
                    settings.llamacpp_base_url,
                    settings.llamacpp_model,
                )
                label, validation_error = validate_label(raw)
                if label:
                    break
                error_msg = validation_error
            except Exception as e:  # noqa: BLE001
                error_msg = str(e)

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            sample_keys = [s["chunk_key"] for s in samples]

            if label:
                cur.execute(
                    """
                    INSERT INTO gold.cluster_labels
                        (clustering_run_id, cluster_id, cluster_label, label_status,
                         sample_size, sample_chunk_keys, model_name, prompt_version,
                         attempt_count)
                    VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s, %s)
                    ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                    SET cluster_label = EXCLUDED.cluster_label,
                        label_status = 'completed',
                        sample_size = EXCLUDED.sample_size,
                        sample_chunk_keys = EXCLUDED.sample_chunk_keys,
                        attempt_count = EXCLUDED.attempt_count,
                        updated_at = NOW()
                """,
                    (
                        run_id,
                        cid,
                        label,
                        len(samples),
                        sample_keys,
                        settings.llamacpp_model,
                        settings.cluster_label_prompt_version,
                        total_attempts,
                    ),
                )
                completed += 1
            else:
                cur.execute(
                    """
                    INSERT INTO gold.cluster_labels
                        (clustering_run_id, cluster_id, label_status, error_message,
                         sample_size, sample_chunk_keys, model_name, prompt_version,
                         attempt_count)
                    VALUES (%s, %s, 'failed', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                    SET label_status = 'failed',
                        error_message = EXCLUDED.error_message,
                        attempt_count = EXCLUDED.attempt_count,
                        updated_at = NOW()
                """,
                    (
                        run_id,
                        cid,
                        error_msg or "unknown",
                        len(samples),
                        sample_keys,
                        settings.llamacpp_model,
                        settings.cluster_label_prompt_version,
                        total_attempts,
                    ),
                )
                failed += 1

            conn.commit()

    return completed, failed


def run_clustering(settings, force: bool = False) -> dict | None:
    pg_conn_str = _build_pg_conn_str(settings)

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    input_count = len(keys) + len(null_keys)

    valid_keys, valid_embeddings, rejected = validate_embeddings(
        keys,
        [embeddings[i] for i in range(len(keys))],
        expected_dim=768,
    )
    rejected_count = len(rejected) + len(null_keys)

    if len(valid_keys) < 4:
        logger.warning(
            "clustering_abortado", motivo="menos de 4 embeddings validos", validos=len(valid_keys)
        )
        return None

    umap_params = {
        "n_components": settings.umap_clustering_n_components,
        "n_neighbors": settings.umap_clustering_n_neighbors,
        "min_dist": settings.umap_clustering_min_dist,
        "metric": settings.umap_clustering_metric,
        "random_state": settings.umap_clustering_random_state,
    }
    hdbscan_params = {
        "min_cluster_size": settings.hdbscan_min_cluster_size,
        "min_samples": settings.hdbscan_min_samples,
        "metric": settings.hdbscan_metric,
        "algorithm": settings.hdbscan_algorithm,
        "cluster_selection_method": settings.hdbscan_cluster_selection_method,
        "n_jobs": settings.hdbscan_n_jobs,
    }

    all_params = {**umap_params, **hdbscan_params}
    corpus_fp = compute_corpus_fingerprint(
        valid_keys, valid_embeddings, settings.ollama_embed_model
    )
    params_hash = compute_parameters_hash(all_params)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT run_id FROM gold.clustering_runs
            WHERE status = 'completed'
              AND corpus_fingerprint = %s
              AND parameters_hash = %s
            LIMIT 1
        """,
            (corpus_fp, params_hash),
        )
        existing = cur.fetchone()
        if existing and not force:
            logger.info("corrida_equivalente_existente", run_id=existing[0])
            return {"run_id": existing[0], "skipped": True}

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gold.clustering_runs
                (status, input_count, valid_count, rejected_count,
                 corpus_fingerprint, parameters_hash, embedding_model,
                 umap_parameters, hdbscan_parameters)
            VALUES ('running', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
        """,
            (
                input_count,
                len(valid_keys),
                rejected_count,
                corpus_fp,
                params_hash,
                settings.ollama_embed_model,
                json.dumps(umap_params),
                json.dumps(hdbscan_params),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("No se pudo crear el run de clusterizacion")
        run_id = row[0]
        conn.commit()

    try:
        normalized = normalize(valid_embeddings, norm="l2")

        umap_vectors = run_umap_clustering(normalized, settings)

        labels, probs = run_hdbscan(umap_vectors, settings)

        unique_clusters = sorted({int(lb) for lb in labels if lb >= 0})
        noise_count = int((labels == -1).sum())

        assignments = [
            (valid_keys[i], int(labels[i]), float(probs[i])) for i in range(len(valid_keys))
        ]
        persist_cluster_assignments(pg_conn_str, run_id, assignments)

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE gold.clustering_runs
                SET cluster_count = %s, noise_count = %s, status = 'completed',
                    finished_at = NOW()
                WHERE run_id = %s
            """,
                (len(unique_clusters), noise_count, run_id),
            )
            conn.commit()

        logger.info(
            "clusterizacion_completada",
            run_id=run_id,
            clusters=len(unique_clusters),
            noise=noise_count,
        )
        return {"run_id": run_id, "clusters": len(unique_clusters), "noise": noise_count}

    except Exception as e:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE gold.clustering_runs
                SET status = 'failed', error_message = %s, finished_at = NOW()
                WHERE run_id = %s
            """,
                (str(e)[:500], run_id),
            )
            conn.commit()
        raise


def run_labeling(settings, run_id: str | None = None) -> dict | None:
    pg_conn_str = _build_pg_conn_str(settings)

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    with psycopg.connect(pg_conn_str) as conn:
        if run_id:
            cur = conn.execute(
                """
                SELECT run_id FROM gold.clustering_runs
                WHERE run_id = %s AND status IN ('completed', 'partial')
                """,
                (run_id,),
            )
        else:
            cur = conn.execute(
                """
                SELECT run_id FROM gold.clustering_runs
                WHERE status IN ('completed', 'partial')
                ORDER BY started_at DESC LIMIT 1
                """
            )
        row = cur.fetchone()
    if row is None:
        logger.info("etiquetado_sin_corrida_objetivo", run_id=run_id)
        return None
    target_run_id = row[0]

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT chunk_key, chunk_text, cluster_id, cluster_pertenencia
            FROM gold.rag_corpus
            WHERE clustering_run_id = %s AND cluster_id >= 0
            """,
            (target_run_id,),
        )
        chunk_rows = cur.fetchall()

    chunks = [
        {
            "chunk_key": r[0],
            "chunk_text": r[1] or "",
            "cluster_id": int(r[2]),
            "cluster_pertenencia": float(r[3]) if r[3] is not None else 0.0,
        }
        for r in chunk_rows
    ]
    if not chunks:
        logger.info("etiquetado_sin_chunks", run_id=target_run_id)
        return None

    cluster_ids = sorted({int(c["cluster_id"]) for c in chunks})

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT cluster_id FROM gold.cluster_labels
            WHERE clustering_run_id = %s AND label_status = 'completed'
            """,
            (target_run_id,),
        )
        done = {r[0] for r in cur.fetchall()}

    targets = [cid for cid in cluster_ids if cid not in done]
    if not targets:
        logger.info("etiquetado_sin_pendientes", run_id=target_run_id)
        return None

    completed, failed = label_clusters(pg_conn_str, target_run_id, targets, chunks, settings)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT label_status, COUNT(*) FROM gold.cluster_labels
            WHERE clustering_run_id = %s GROUP BY label_status
            """,
            (target_run_id,),
        )
        counts = {r[0]: r[1] for r in cur.fetchall()}
        labeled_count = counts.get("completed", 0)
        failed_count = counts.get("failed", 0)
        final_status = "partial" if failed_count > 0 else "completed"
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE gold.clustering_runs
            SET labeled_cluster_count = %s, failed_label_count = %s,
                status = %s, finished_at = NOW()
            WHERE run_id = %s
            """,
            (labeled_count, failed_count, final_status, target_run_id),
        )
        conn.commit()

    logger.info(
        "etiquetado_completado",
        run_id=target_run_id,
        clusters=len(targets),
        completed=completed,
        failed=failed,
    )
    return {
        "run_id": target_run_id,
        "clusters": len(targets),
        "completed": completed,
        "failed": failed,
    }
