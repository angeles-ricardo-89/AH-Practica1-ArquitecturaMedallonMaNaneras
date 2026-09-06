from __future__ import annotations

import psycopg

from lakehouse.services.neon_bootstrap import bootstrap_neon_schema


def _tables(conn_str: str, schema: str) -> set[str]:
    with psycopg.connect(conn_str) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        ).fetchall()
    return {r[0] for r in rows}


def _has_column(conn_str: str, table: str, column: str) -> bool:
    with psycopg.connect(conn_str) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'gold' AND table_name = %s AND column_name = %s",
            (table, column),
        ).fetchone()
    return row is not None


class TestBootstrapNeonSchema:
    def test_creates_required_schema(self, pg_conn_str: str) -> None:
        bootstrap_neon_schema(pg_conn_str)
        gold = _tables(pg_conn_str, "gold")
        assert "rag_corpus" in gold
        assert "clustering_runs" in gold
        assert "cluster_labels" in gold
        assert _has_column(pg_conn_str, "rag_corpus", "embedding_3d")
        assert _has_column(pg_conn_str, "rag_corpus", "cluster_id")
        public_tables = _tables(pg_conn_str, "public")
        for table in (
            "app_user",
            "conversation",
            "message",
            "tool_execution",
            "rate_limit_counter",
            "index_metadata",
        ):
            assert table in public_tables

    def test_is_idempotent(self, pg_conn_str: str) -> None:
        bootstrap_neon_schema(pg_conn_str)
        bootstrap_neon_schema(pg_conn_str)
        assert "clustering_runs" in _tables(pg_conn_str, "gold")
