import psycopg
import pytest
from lakehouse.pipeline.clustering import ensure_clustering_schema


def test_ensure_clustering_schema_creates_columns_and_tables(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
              AND column_name IN ('cluster_id', 'cluster_pertenencia', 'clustering_run_id')
            ORDER BY column_name
        """)
        cols = [r[0] for r in cur.fetchall()]
        assert "cluster_id" in cols
        assert "cluster_pertenencia" in cols
        assert "clustering_run_id" in cols

        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'gold'
              AND table_name IN ('clustering_runs', 'cluster_labels')
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        assert "clustering_runs" in tables
        assert "cluster_labels" in tables


def test_ensure_clustering_schema_is_idempotent(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        ensure_clustering_schema(conn)


def test_cluster_pertenencia_check_constraint(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'gold.rag_corpus'::regclass AND conname = 'chk_cluster_pertenencia_range'
        """)
        row = cur.fetchone()
        assert row is not None


def test_cluster_labels_no_negative_cluster_id(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO gold.cluster_labels (clustering_run_id, cluster_id, label_status)
                VALUES (gen_random_uuid(), -1, 'pending')
            """)
            conn.commit()
            assert False, "Deberia haber fallado por CHECK"
        except psycopg.errors.CheckViolation:
            conn.rollback()
