import numpy as np
import psycopg
import pytest
from sklearn.preprocessing import normalize

from lakehouse.config import Settings
from lakehouse.pipeline.clustering import (
    compute_corpus_fingerprint,
    compute_parameters_hash,
    ensure_clustering_schema,
    load_embeddings,
    persist_cluster_assignments,
    run_hdbscan,
    run_umap_clustering,
    validate_embeddings,
)


@pytest.fixture
def seeded_embeddings():
    rng = np.random.RandomState(42)
    return rng.randn(50, 768).astype(np.float64)


@pytest.fixture
def settings_override():
    s = Settings()
    s.umap_clustering_n_components = 5
    s.umap_clustering_n_neighbors = 10
    s.hdbscan_min_cluster_size = 5
    s.hdbscan_min_samples = 3
    return s


def test_umap_output_dimension_configurable(seeded_embeddings, settings_override):
    settings_override.umap_clustering_n_components = 10
    result = run_umap_clustering(seeded_embeddings, settings_override)
    assert result.shape == (50, 10)


def test_full_umap_hdbscan_pipeline(seeded_embeddings, settings_override):
    normalized = normalize(seeded_embeddings, norm="l2")
    umap_vecs = run_umap_clustering(normalized, settings_override)
    labels, probs = run_hdbscan(umap_vecs, settings_override)
    assert len(labels) == 50
    assert len(probs) == 50
    assert np.all((labels == -1) == (probs == 0.0))


def test_cluster_assignments_persisted(pg_conn_str):
    run_id = "00000000-0000-0000-0000-000000000002"
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'int_test_%'")
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload)
            VALUES
            ('int_test_a', 'c1', '2025-01-01', 'p1', 'texto a', 'payload a'),
            ('int_test_b', 'c1', '2025-01-01', 'p1', 'texto b', 'payload b'),
            ('int_test_c', 'c1', '2025-01-01', 'p1', 'texto c', 'payload c')
            ON CONFLICT (chunk_key) DO NOTHING
        """)
        conn.commit()

    try:
        assignments = [
            ("int_test_a", 0, 0.99),
            ("int_test_b", 1, 0.85),
            ("int_test_c", 1, 0.75),
        ]
        persist_cluster_assignments(pg_conn_str, run_id, assignments)

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.execute(
                "SELECT chunk_key, cluster_id, cluster_pertenencia, clustering_run_id "
                "FROM gold.rag_corpus WHERE chunk_key IN ('int_test_a', 'int_test_b', 'int_test_c') "
                "ORDER BY chunk_key"
            )
            rows = cur.fetchall()
            assert rows[0][0] == "int_test_a"
            assert rows[0][1] == 0
            assert rows[0][2] == pytest.approx(0.99)
            assert str(rows[0][3]) == run_id
            assert rows[1][0] == "int_test_b"
            assert rows[1][1] == 1
            assert rows[1][2] == pytest.approx(0.85)
            assert str(rows[1][3]) == run_id
            assert rows[2][0] == "int_test_c"
            assert rows[2][1] == 1
            assert rows[2][2] == pytest.approx(0.75)
            assert str(rows[2][3]) == run_id
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'int_test_%'")
            conn.commit()


def test_idempotency_same_input_creates_single_run(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    keys = ["idem_key_1", "idem_key_2"]
    emb = np.random.RandomState(99).randn(2, 768).astype(np.float64)
    fp = compute_corpus_fingerprint(keys, emb, "test_model")
    ph = compute_parameters_hash({"test": "v1"})

    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO gold.clustering_runs
                    (status, valid_count, corpus_fingerprint, parameters_hash, embedding_model)
                VALUES ('completed', 2, %s, %s, 'test_model')
            """,
                (fp, ph),
            )
            conn.commit()

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM gold.clustering_runs "
                "WHERE corpus_fingerprint = %s AND parameters_hash = %s",
                (fp, ph),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute(
                "DELETE FROM gold.clustering_runs "
                "WHERE corpus_fingerprint = %s AND parameters_hash = %s",
                (fp, ph),
            )
            conn.commit()


def test_embedding_3d_not_used_for_hdbscan(pg_conn_str):
    from lakehouse.pipeline.enrichment import _compute_umap_3d  # noqa: PLC0415

    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'viz_chunk_%'")
        conn.commit()

    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                             participant, chunk_text, payload, embedding)
                VALUES
                ('viz_chunk_a', 'c1', '2025-01-01', 'p1', 'text a', 'payload a',
                 %s::vector),
                ('viz_chunk_b', 'c1', '2025-01-01', 'p1', 'text b', 'payload b',
                 %s::vector),
                ('viz_chunk_c', 'c1', '2025-01-01', 'p1', 'text c', 'payload c',
                 %s::vector),
                ('viz_chunk_d', 'c1', '2025-01-01', 'p1', 'text d', 'payload d',
                 %s::vector)
                ON CONFLICT (chunk_key) DO NOTHING
            """,
                (
                    f"[{','.join(str(x) for x in np.random.RandomState(1).randn(768).tolist())}]",
                    f"[{','.join(str(x) for x in np.random.RandomState(2).randn(768).tolist())}]",
                    f"[{','.join(str(x) for x in np.random.RandomState(3).randn(768).tolist())}]",
                    f"[{','.join(str(x) for x in np.random.RandomState(4).randn(768).tolist())}]",
                ),
            )
            conn.commit()

        _compute_umap_3d(pg_conn_str)

        keys, embeddings, _ = load_embeddings(pg_conn_str)
        valid_keys, valid_embeddings, _ = validate_embeddings(
            keys,
            [embeddings[i] for i in range(len(keys))],
            expected_dim=768,
        )
        normalized = normalize(valid_embeddings, norm="l2")

        settings = Settings()
        settings.umap_clustering_n_components = 2
        settings.umap_clustering_n_neighbors = 3
        umap_cluster_vectors = run_umap_clustering(normalized, settings)

        labels, probs = run_hdbscan(umap_cluster_vectors, settings)

        assert len(labels) == len(valid_keys)
        assert len(probs) == len(valid_keys)
        assert umap_cluster_vectors.shape[1] == 2
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'viz_chunk_%'")
            conn.commit()
