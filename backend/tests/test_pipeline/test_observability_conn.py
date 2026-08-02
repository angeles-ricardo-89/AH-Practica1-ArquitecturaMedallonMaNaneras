import psycopg

import lakehouse.config
from lakehouse.config import Settings
from lakehouse.db.observability_conn import (
    add_embedding_3d_column,
    ensure_observability_tables,
)


class TestEnsureObservabilityTables:
    def test_creates_schema_and_table(self, monkeypatch):
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP SCHEMA IF EXISTS observability CASCADE")

        ensure_observability_tables(conn_str)
        add_embedding_3d_column(conn_str)

        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'observability' AND table_name = 'pipeline_runs'
            ORDER BY ordinal_position
        """)
        cols = {row[0]: row[1] for row in cur.fetchall()}
        assert "run_id" in cols
        assert "capa" in cols
        assert "status" in cols
        assert "started_at" in cols
        assert "finished_at" in cols
        assert "records_in" in cols
        assert "records_out" in cols
        assert "dlq_count" in cols
        assert "error_message" in cols

        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
            AND column_name = 'embedding_3d'
        """)
        assert cur.fetchone() is not None

        cur.execute("DROP SCHEMA IF EXISTS observability CASCADE")
        conn.close()

    def test_idempotent_on_second_call(self, monkeypatch):
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        ensure_observability_tables(conn_str)
        ensure_observability_tables(conn_str)
        add_embedding_3d_column(conn_str)
        add_embedding_3d_column(conn_str)
