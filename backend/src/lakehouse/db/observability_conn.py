from __future__ import annotations

import psycopg

PIPELINE_RUNS_DDL = """
CREATE SCHEMA IF NOT EXISTS observability;

CREATE TABLE IF NOT EXISTS observability.pipeline_runs (
    run_id         TEXT PRIMARY KEY,
    capa           TEXT NOT NULL CHECK (capa IN ('bronze', 'silver', 'gold')),
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'ok', 'error')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    records_in     INTEGER NOT NULL DEFAULT 0,
    records_out    INTEGER NOT NULL DEFAULT 0,
    dlq_count      INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_capa_started
    ON observability.pipeline_runs (capa, started_at DESC);
"""

EMBEDDING_3D_DDL = """
ALTER TABLE gold.rag_corpus
    ADD COLUMN IF NOT EXISTS embedding_3d DOUBLE PRECISION[3];
"""


def ensure_observability_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(PIPELINE_RUNS_DDL)
        conn.commit()


def add_embedding_3d_column(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(EMBEDDING_3D_DDL)
        conn.commit()
