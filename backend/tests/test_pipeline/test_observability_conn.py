from __future__ import annotations

import psycopg
import pytest

import lakehouse.config
from lakehouse.config import Settings
from lakehouse.db.observability_conn import ensure_observability_tables

EXPECTED_PIPELINE_RUNS_COLUMNS = {
    "run_id",
    "capa",
    "status",
    "started_at",
    "finished_at",
    "records_in",
    "records_out",
    "dlq_count",
    "error_message",
}


@pytest.fixture
def conn_str(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _prepare_gold_rag_corpus(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS gold")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold.rag_corpus (
                chunk_key VARCHAR PRIMARY KEY,
                embedding vector(768)
            )
        """)
        conn.execute("ALTER TABLE gold.rag_corpus DROP COLUMN IF EXISTS embedding_3d")


def _drop_observability_schema(conn_str: str) -> None:
    with psycopg.connect(conn_str) as conn:
        conn.execute("DROP SCHEMA IF EXISTS observability CASCADE")


class TestEnsureObservabilityTables:
    def test_creates_schema_and_table(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            ensure_observability_tables(conn_str)

            with psycopg.connect(conn_str) as conn:
                cols = {
                    row[0]
                    for row in conn.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'observability'
                          AND table_name = 'pipeline_runs'
                    """).fetchall()
                }
                assert cols == EXPECTED_PIPELINE_RUNS_COLUMNS

                embedding_3d = conn.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
                      AND column_name = 'embedding_3d'
                """).fetchone()
                assert embedding_3d is not None
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)

    def test_idempotent_on_second_call(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            ensure_observability_tables(conn_str)
            ensure_observability_tables(conn_str)

            with psycopg.connect(conn_str) as conn:
                cols = {
                    row[0]
                    for row in conn.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'observability'
                          AND table_name = 'pipeline_runs'
                    """).fetchall()
                }
                assert cols == EXPECTED_PIPELINE_RUNS_COLUMNS

                index_count = conn.execute("""
                    SELECT COUNT(*)
                    FROM pg_indexes
                    WHERE schemaname = 'observability'
                      AND tablename = 'pipeline_runs'
                      AND indexname = 'idx_pipeline_runs_capa_started'
                """).fetchone()[0]
                assert index_count == 1

                embedding_count = conn.execute("""
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
                      AND column_name = 'embedding_3d'
                """).fetchone()[0]
                assert embedding_count == 1
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)

    def test_status_constraint_accepts_interrupted(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            ensure_observability_tables(conn_str)
            with psycopg.connect(conn_str) as conn:
                conn.execute(
                    """INSERT INTO observability.pipeline_runs
                    (run_id, capa, status)
                    VALUES ('run-interrupted', 'bronze', 'interrupted')"""
                )
                conn.commit()
                count = conn.execute(
                    "SELECT COUNT(*) FROM observability.pipeline_runs WHERE run_id = %s",
                    ("run-interrupted",),
                ).fetchone()[0]
            assert count == 1
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)

    def test_migrates_existing_constraint(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            with psycopg.connect(conn_str) as conn:
                conn.execute("CREATE SCHEMA IF NOT EXISTS observability")
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS observability.pipeline_runs (
                        run_id TEXT PRIMARY KEY,
                        capa TEXT NOT NULL
                             CHECK (capa IN ('bronze', 'silver', 'gold')),
                        status TEXT NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running', 'ok', 'error')),
                        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ,
                        records_in INTEGER NOT NULL DEFAULT 0,
                        records_out INTEGER NOT NULL DEFAULT 0,
                        dlq_count INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT
                    )"""
                )
                conn.commit()
            ensure_observability_tables(conn_str)
            with psycopg.connect(conn_str) as conn:
                conn.execute(
                    """INSERT INTO observability.pipeline_runs
                    (run_id, capa, status)
                    VALUES ('run-interrupted', 'bronze', 'interrupted')"""
                )
                conn.commit()
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)
