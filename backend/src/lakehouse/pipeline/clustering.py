from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import psycopg
import umap
from hdbscan import HDBSCAN
from sklearn.preprocessing import normalize

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="gold")


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

    for key, vec in zip(keys, embeddings):
        if vec is None:
            rejected.append((key, "null"))
            continue
        if not isinstance(vec, np.ndarray):
            vec = np.array(vec, dtype=np.float64)
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

    arr = np.array(valid_vecs, dtype=np.float64) if valid_vecs else np.empty((0, expected_dim), dtype=np.float64)
    return valid_keys, arr, rejected


def compute_corpus_fingerprint(
    chunk_keys: list[str],
    embeddings: np.ndarray,
    model: str,
) -> str:
    data = json.dumps({
        "keys": sorted(chunk_keys),
        "embedding_hash": hashlib.sha256(embeddings.tobytes()).hexdigest(),
        "model": model,
    }, sort_keys=True)
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
        cur = conn.execute(
            "SELECT chunk_key, embedding::text FROM gold.rag_corpus"
        )
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
        n_jobs=settings.hdbscan_n_jobs,
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
        cur.execute("""
            UPDATE gold.rag_corpus AS g
            SET cluster_id = a.cluster_id,
                cluster_pertenencia = a.pertenencia,
                clustering_run_id = %s
            FROM _cluster_assignments AS a
            WHERE g.chunk_key = a.chunk_key
        """, (run_id,))
        conn.commit()


def select_representative_chunks(
    chunks: list[dict],
    cluster_id: int,
    k: int = 5,
) -> list[dict]:
    if cluster_id < 0:
        return []
    cluster_chunks = [
        c for c in chunks
        if c.get("cluster_id") == cluster_id
    ]
    cluster_chunks.sort(key=lambda c: (-c.get("cluster_pertenencia", 0.0), c["chunk_key"]))
    return cluster_chunks[:k]





