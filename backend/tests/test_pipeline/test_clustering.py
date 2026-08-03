import numpy as np
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


def test_validate_embeddings_rejects_null():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1", "k2"],
        embeddings=[None, np.array([1.0, 2.0, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert keys == ["k2"]
    assert rejected[0][0] == "k1"
    assert rejected[0][1] == "null"


def test_validate_embeddings_rejects_nan():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.nan, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_inf():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.inf, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_wrong_dim():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, 2.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert "dimension" in rejected[0][1]


def test_validate_embeddings_rejects_zero_norm():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([0.0, 0.0, 0.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "zero_norm"


def test_validate_embeddings_accepts_valid():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1", "k2"],
        embeddings=[
            np.array([1.0, 2.0, 3.0], dtype=np.float64),
            np.array([4.0, 5.0, 6.0], dtype=np.float64),
        ],
        expected_dim=3,
    )
    assert keys == ["k1", "k2"]
    assert len(rejected) == 0
    assert vecs.shape == (2, 3)


def test_normalize_l2_preserves_shape():
    from sklearn.preprocessing import normalize

    vecs = np.array([[3.0, 4.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
    result = normalize(vecs, norm="l2")
    assert result.shape == vecs.shape


def test_normalize_l2_unit_norm():
    from sklearn.preprocessing import normalize

    vecs = np.random.RandomState(42).randn(10, 768).astype(np.float64)
    result = normalize(vecs, norm="l2")
    norms = np.linalg.norm(result, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_corpus_fingerprint_deterministic():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    keys = ["key_a", "key_b", "key_c"]
    emb = np.random.RandomState(42).randn(3, 768).astype(np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    fp2 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    assert fp1 == fp2


def test_corpus_fingerprint_changes_with_data():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    keys = ["k1", "k2"]
    emb1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    emb2 = np.array([[1.0, 2.0], [3.0, 5.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb1, "model")
    fp2 = compute_corpus_fingerprint(keys, emb2, "model")
    assert fp1 != fp2


def test_corpus_fingerprint_different_key_order_same_hash():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    emb = np.array([[1.0], [2.0], [3.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(["c", "a", "b"], emb, "model")
    fp2 = compute_corpus_fingerprint(["a", "b", "c"], emb, "model")
    assert fp1 == fp2


def test_parameters_hash_deterministic():
    from lakehouse.pipeline.clustering import compute_parameters_hash

    params1 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    params2 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    assert compute_parameters_hash(params1) == compute_parameters_hash(params2)


def test_parameters_hash_changes_with_params():
    from lakehouse.pipeline.clustering import compute_parameters_hash

    h1 = compute_parameters_hash({"x": 15})
    h2 = compute_parameters_hash({"x": 16})
    assert h1 != h2


def test_load_embeddings_returns_keys_and_array(pg_conn_str):
    from lakehouse.pipeline.clustering import ensure_clustering_schema, load_embeddings

    rng = np.random.RandomState(42)
    vec_a = rng.randn(768).tolist()
    vec_b = rng.randn(768).tolist()

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload, embedding)
            VALUES
            ('ck_test_1', 'conf_1', '2025-01-01', 'p1', 'texto 1', 'payload 1',
             %s::vector),
            ('ck_test_2', 'conf_1', '2025-01-01', 'p1', 'texto 2', 'payload 2',
             %s::vector),
            ('ck_test_null', 'conf_1', '2025-01-01', 'p1', 'texto null', 'payload null',
             NULL)
            ON CONFLICT (chunk_key) DO NOTHING
        """, (
            "[" + ",".join(str(x) for x in vec_a) + "]",
            "[" + ",".join(str(x) for x in vec_b) + "]",
        ))
        conn.commit()

    try:
        keys, embeddings, null_keys = load_embeddings(pg_conn_str)
        assert len(keys) == 2
        assert "ck_test_1" in keys
        assert "ck_test_2" in keys
        assert "ck_test_null" in null_keys
        assert embeddings.shape == (2, 768)
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'ck_test_%'")
            conn.commit()


def test_load_embeddings_empty_table(pg_conn_str):
    from lakehouse.pipeline.clustering import load_embeddings

    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'ck_test_%'")
        conn.commit()

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    assert keys == []
    assert embeddings.shape[0] == 0


def test_umap_clustering_output_dimension():
    import umap

    X = np.random.RandomState(42).randn(100, 768).astype(np.float64)
    reducer = umap.UMAP(
        n_components=15, metric="cosine", min_dist=0.0,
        n_neighbors=15, random_state=42,
    )
    result = reducer.fit_transform(X)
    assert result.shape == (100, 15)


def test_hdbscan_labels_and_probabilities_shapes():
    from hdbscan import HDBSCAN

    rng = np.random.RandomState(42)
    X = rng.randn(50, 5).astype(np.float64)
    clusterer = HDBSCAN(min_cluster_size=5, min_samples=3)
    labels = clusterer.fit_predict(X)
    probs = clusterer.probabilities_
    assert labels.shape == (50,)
    assert probs.shape == (50,)


def test_noise_gets_cluster_minus_one():
    from hdbscan import HDBSCAN

    rng = np.random.RandomState(42)
    X = rng.randn(20, 2).astype(np.float64)
    X[:5] = np.random.RandomState(99).randn(5, 2) * 0.01
    X[5:10] = np.random.RandomState(88).randn(5, 2) * 0.01 + 10.0
    clusterer = HDBSCAN(min_cluster_size=3, min_samples=2)
    labels = clusterer.fit_predict(X)
    probs = clusterer.probabilities_
    for i in range(len(labels)):
        if labels[i] == -1:
            assert probs[i] == 0.0, f"Ruido debe tener pertenencia 0.0, obtuvo {probs[i]}"
