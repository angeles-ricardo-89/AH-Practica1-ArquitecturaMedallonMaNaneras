from unittest.mock import MagicMock

import numpy as np
import psycopg
import pytest
import umap
from hdbscan import HDBSCAN
from sklearn.preprocessing import normalize

from lakehouse.config import Settings
from lakehouse.pipeline import clustering
from lakehouse.pipeline.clustering import (
    compute_corpus_fingerprint,
    compute_parameters_hash,
    ensure_clustering_schema,
    format_labeling_prompt,
    load_embeddings,
    load_prompt_template,
    persist_cluster_assignments,
    run_clustering_pipeline,
    select_representative_chunks,
    validate_embeddings,
    validate_label,
)


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
    keys, _, rejected = validate_embeddings(
        keys=["k1", "k2"],
        embeddings=[None, np.array([1.0, 2.0, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert keys == ["k2"]
    assert rejected[0][0] == "k1"
    assert rejected[0][1] == "null"


def test_validate_embeddings_rejects_nan():
    _, _, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.nan, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_inf():
    _, _, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.inf, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_wrong_dim():
    _, _, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, 2.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert "dimension" in rejected[0][1]


def test_validate_embeddings_rejects_zero_norm():
    _, _, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([0.0, 0.0, 0.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "zero_norm"


def test_validate_embeddings_accepts_valid():
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
    vecs = np.array([[3.0, 4.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
    result = normalize(vecs, norm="l2")
    assert result.shape == vecs.shape


def test_normalize_l2_unit_norm():
    vecs = np.random.RandomState(42).randn(10, 768).astype(np.float64)
    result = normalize(vecs, norm="l2")
    norms = np.linalg.norm(result, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_corpus_fingerprint_deterministic():
    keys = ["key_a", "key_b", "key_c"]
    emb = np.random.RandomState(42).randn(3, 768).astype(np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    fp2 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    assert fp1 == fp2


def test_corpus_fingerprint_changes_with_data():
    keys = ["k1", "k2"]
    emb1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    emb2 = np.array([[1.0, 2.0], [3.0, 5.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb1, "model")
    fp2 = compute_corpus_fingerprint(keys, emb2, "model")
    assert fp1 != fp2


def test_corpus_fingerprint_different_key_order_same_hash():
    emb = np.array([[1.0], [2.0], [3.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(["c", "a", "b"], emb, "model")
    fp2 = compute_corpus_fingerprint(["a", "b", "c"], emb, "model")
    assert fp1 == fp2


def test_parameters_hash_deterministic():
    params1 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    params2 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    assert compute_parameters_hash(params1) == compute_parameters_hash(params2)


def test_parameters_hash_changes_with_params():
    h1 = compute_parameters_hash({"x": 15})
    h2 = compute_parameters_hash({"x": 16})
    assert h1 != h2


def test_load_embeddings_returns_keys_and_array(pg_conn_str):
    rng = np.random.RandomState(42)
    vec_a = rng.randn(768).tolist()
    vec_b = rng.randn(768).tolist()

    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'ck_test_%' "
            "OR chunk_key LIKE 'viz_chunk_%' OR chunk_key LIKE 'assign_%' "
            "OR chunk_key LIKE 'int_test_%'"
        )
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
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
        """,
            (
                "[" + ",".join(str(x) for x in vec_a) + "]",
                "[" + ",".join(str(x) for x in vec_b) + "]",
            ),
        )
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
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'ck_test_%'")
        conn.commit()

    keys, embeddings, _ = load_embeddings(pg_conn_str)
    assert keys == []
    assert embeddings.shape[0] == 0


def test_umap_clustering_output_dimension():
    data = np.random.RandomState(42).randn(100, 768).astype(np.float64)
    reducer = umap.UMAP(
        n_components=15,
        metric="cosine",
        min_dist=0.0,
        n_neighbors=15,
        random_state=42,
    )
    result = reducer.fit_transform(data)
    assert result.shape == (100, 15)


def test_hdbscan_labels_and_probabilities_shapes():
    rng = np.random.RandomState(42)
    data = rng.randn(50, 5).astype(np.float64)
    clusterer = HDBSCAN(min_cluster_size=5, min_samples=3)
    labels = clusterer.fit_predict(data)
    probs = clusterer.probabilities_
    assert labels.shape == (50,)
    assert probs.shape == (50,)


def test_noise_gets_cluster_minus_one():
    rng = np.random.RandomState(42)
    data = rng.randn(20, 2).astype(np.float64)
    data[:5] = np.random.RandomState(99).randn(5, 2) * 0.01
    data[5:10] = np.random.RandomState(88).randn(5, 2) * 0.01 + 10.0
    clusterer = HDBSCAN(min_cluster_size=3, min_samples=2)
    labels = clusterer.fit_predict(data)
    probs = clusterer.probabilities_
    for i in range(len(labels)):
        if labels[i] == -1:
            assert probs[i] == 0.0, f"Ruido debe tener pertenencia 0.0, obtuvo {probs[i]}"


def test_persist_cluster_assignments(pg_conn_str):
    run_id = "00000000-0000-0000-0000-000000000001"

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload)
            VALUES
            ('assign_1', 'c1', '2025-01-01', 'p1', 't1', 'pl1'),
            ('assign_2', 'c1', '2025-01-01', 'p1', 't2', 'pl2')
            ON CONFLICT (chunk_key) DO NOTHING
        """)
        conn.commit()

    assignments = [
        ("assign_1", 0, 0.95),
        ("assign_2", 1, 0.80),
    ]
    persist_cluster_assignments(pg_conn_str, run_id, assignments)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            "SELECT chunk_key, cluster_id, cluster_pertenencia, clustering_run_id "
            "FROM gold.rag_corpus WHERE chunk_key IN ('assign_1', 'assign_2') "
            "ORDER BY chunk_key"
        )
        rows = cur.fetchall()
        assert rows[0][0] == "assign_1"
        assert rows[0][1] == 0
        assert rows[0][2] == pytest.approx(0.95)
        assert str(rows[0][3]) == run_id
        assert rows[1][0] == "assign_2"
        assert rows[1][1] == 1
        assert rows[1][2] == pytest.approx(0.80)
        assert str(rows[1][3]) == run_id


def test_select_representative_chunks_top_k():
    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.5},
        {"chunk_key": "b", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "c", "cluster_id": 0, "cluster_pertenencia": 0.3},
        {"chunk_key": "d", "cluster_id": 0, "cluster_pertenencia": 0.7},
        {"chunk_key": "e", "cluster_id": 0, "cluster_pertenencia": 0.6},
        {"chunk_key": "f", "cluster_id": 0, "cluster_pertenencia": 0.8},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=3)
    assert len(result) == 3
    assert result[0]["chunk_key"] == "b"
    assert result[1]["chunk_key"] == "f"
    assert result[2]["chunk_key"] == "d"


def test_select_representative_chunks_tiebreaker():
    chunks = [
        {"chunk_key": "z", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=2)
    assert result[0]["chunk_key"] == "a"
    assert result[1]["chunk_key"] == "z"


def test_select_representative_chunks_small_cluster():
    chunks = [
        {"chunk_key": "x", "cluster_id": 1, "cluster_pertenencia": 0.8},
    ]
    result = select_representative_chunks(chunks, cluster_id=1, k=5)
    assert len(result) == 1


def test_select_representative_chunks_excludes_other_clusters():
    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "b", "cluster_id": 1, "cluster_pertenencia": 0.95},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=5)
    assert len(result) == 1
    assert result[0]["chunk_key"] == "a"


def test_select_representative_chunks_excludes_noise():
    chunks = [
        {"chunk_key": "n", "cluster_id": -1, "cluster_pertenencia": 0.0},
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
    ]
    result = select_representative_chunks(chunks, cluster_id=-1, k=5)
    assert len(result) == 0


def test_validate_label_rejects_empty():
    label, error = validate_label("")
    assert label is None
    assert error == "empty"


def test_validate_label_rejects_multiline():
    label, error = validate_label("linea1\nlinea2")
    assert label is None
    assert error == "multiline"


def test_validate_label_rejects_too_many_words():
    label, error = validate_label("una etiqueta con mas de cuatro palabras aqui")
    assert label is None
    assert error == "too_many_words"


def test_validate_label_strips_prefixes():
    label, _ = validate_label("Etiqueta: Salud Publica")
    assert label == "Salud Publica"

    label, _ = validate_label("Tema: Educacion")
    assert label == "Educacion"

    label, _ = validate_label("Categoria: Seguridad Nacional")
    assert label == "Seguridad Nacional"

    label, _ = validate_label("Respuesta: Economia")
    assert label == "Economia"


def test_validate_label_strips_quotes():
    label, _ = validate_label('"Salud Publica"')
    assert label == "Salud Publica"


def test_validate_label_normalizes_spaces():
    label, _ = validate_label("  mucha   salud  publica  .")
    assert label == "mucha salud publica"


def test_validate_label_collapses_single_newline_with_text():
    label, _ = validate_label("texto\n")
    assert label == "texto"


def test_validate_label_accepts_valid_four_words():
    label, error = validate_label("Seguridad y Salud Publica")
    assert label == "Seguridad y Salud Publica"
    assert error is None


def test_validate_label_accepts_single_word():
    label, error = validate_label("Economia")
    assert label == "Economia"
    assert error is None


def test_load_prompt_template_returns_content():
    template = load_prompt_template("v1")
    assert "{textos_formateados}" in template
    assert "REGLAS ESTRICTAS" in template


def test_load_prompt_template_missing_version():
    with pytest.raises(FileNotFoundError):
        load_prompt_template("no_existe")


def test_format_labeling_prompt_replaces_placeholder():
    template = "INST: {textos_formateados}"
    samples = [
        {"chunk_key": "a", "chunk_text": "texto uno"},
        {"chunk_key": "b", "chunk_text": "texto dos"},
    ]
    result = format_labeling_prompt(template, samples, max_chars=100)
    assert "- texto uno\n- texto dos" in result


def test_format_labeling_prompt_truncates_long_text():
    template = "{textos_formateados}"
    samples = [{"chunk_key": "a", "chunk_text": "x" * 200}]
    result = format_labeling_prompt(template, samples, max_chars=10)
    assert "- xxxxxxxxxx" in result
    assert "x" * 11 not in result


def test_generate_label_returns_content(monkeypatch):
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "  Salud Publica  "}}],
    }
    monkeypatch.setattr(clustering.httpx, "post", lambda *_args, **_kwargs: fake_response)

    result = clustering.generate_label("prompt", "http://llm", "gemma4")
    assert result == "Salud Publica"


def test_generate_label_raises_on_empty_response(monkeypatch):
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "   "}}]}
    monkeypatch.setattr(clustering.httpx, "post", lambda *_args, **_kwargs: fake_response)

    with pytest.raises(ValueError):
        clustering.generate_label("prompt", "http://llm", "gemma4")


def test_generate_label_raises_on_http_error(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = RuntimeError("500")
    monkeypatch.setattr(clustering.httpx, "post", lambda *_args, **_kwargs: fake_response)

    with pytest.raises(RuntimeError):
        clustering.generate_label("prompt", "http://llm", "gemma4")


def test_label_clusters_completes_all(monkeypatch, pg_conn_str):
    settings = Settings()
    settings.k_hdbscan_sampling = 2
    settings.cluster_label_max_retries = 1
    settings.cluster_label_prompt_version = "v1"
    settings.llamacpp_base_url = "http://llm"
    settings.llamacpp_model = "gemma4"

    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9, "chunk_text": "t a"},
        {"chunk_key": "b", "cluster_id": 0, "cluster_pertenencia": 0.8, "chunk_text": "t b"},
        {"chunk_key": "c", "cluster_id": 1, "cluster_pertenencia": 0.7, "chunk_text": "t c"},
        {"chunk_key": "n", "cluster_id": -1, "cluster_pertenencia": 0.0, "chunk_text": "t n"},
    ]

    monkeypatch.setattr(clustering, "generate_label", lambda *_args, **_kwargs: "Salud Publica")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    monkeypatch.setattr(clustering.psycopg, "connect", lambda *_args, **_kwargs: mock_cm)

    completed, failed = clustering.label_clusters(pg_conn_str, "run-1", [0, 1], chunks, settings)
    assert completed == 2
    assert failed == 0
    assert mock_conn.commit.call_count == 2


def test_label_clusters_marks_failed_when_invalid(monkeypatch, pg_conn_str):
    settings = Settings()
    settings.k_hdbscan_sampling = 2
    settings.cluster_label_max_retries = 1
    settings.cluster_label_prompt_version = "v1"
    settings.llamacpp_base_url = "http://llm"
    settings.llamacpp_model = "gemma4"

    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9, "chunk_text": "t a"},
    ]

    monkeypatch.setattr(
        clustering,
        "generate_label",
        lambda *_args, **_kwargs: "una etiqueta con mas de cuatro palabras aqui",
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    monkeypatch.setattr(clustering.psycopg, "connect", lambda *_args, **_kwargs: mock_cm)

    completed, failed = clustering.label_clusters(pg_conn_str, "run-2", [0], chunks, settings)
    assert completed == 0
    assert failed == 1


def _mock_pg_connect(
    monkeypatch,
    select_fetchone=None,
    insert_fetchone=None,
) -> tuple[MagicMock, MagicMock]:
    mock_conn = MagicMock()
    mock_select = MagicMock()
    mock_select.fetchone.return_value = select_fetchone
    mock_conn.execute.return_value = mock_select

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = insert_fetchone
    mock_conn.cursor.return_value = mock_cursor

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    monkeypatch.setattr(clustering.psycopg, "connect", lambda *_args, **_kwargs: mock_cm)
    return mock_conn, mock_cursor


def _valid_embeddings(n: int = 4, dim: int = 768) -> tuple[list[str], np.ndarray]:
    rng = np.random.RandomState(7)
    keys = [f"k{i}" for i in range(n)]
    arr = rng.randn(n, dim).astype(np.float64)
    return keys, arr


def test_run_clustering_pipeline_aborts_with_fewer_than_4(monkeypatch):
    keys, arr = _valid_embeddings(n=3)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))
    _mock_pg_connect(monkeypatch)

    result = run_clustering_pipeline(Settings())
    assert result is None


def test_run_clustering_pipeline_skips_existing_run(monkeypatch):
    keys, arr = _valid_embeddings(n=4)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))
    _mock_pg_connect(monkeypatch, select_fetchone=("existing-run-1",))

    result = run_clustering_pipeline(Settings())
    assert result == {"run_id": "existing-run-1", "skipped": True}


def test_run_clustering_pipeline_success(monkeypatch):
    keys, arr = _valid_embeddings(n=4)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))

    mock_conn, _ = _mock_pg_connect(monkeypatch, select_fetchone=None, insert_fetchone=("run-abc",))

    labels = np.array([0, 0, 1, -1], dtype=np.int64)
    probs = np.array([0.9, 0.8, 0.7, 0.0], dtype=np.float64)
    monkeypatch.setattr(
        clustering, "run_umap_clustering", lambda _emb, _settings: np.zeros((4, 15))
    )
    monkeypatch.setattr(clustering, "run_hdbscan", lambda _vecs, _settings: (labels, probs))
    monkeypatch.setattr(clustering, "persist_cluster_assignments", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clustering, "label_clusters", lambda *_args, **_kwargs: (2, 0))

    result = run_clustering_pipeline(Settings())
    assert result == {"run_id": "run-abc", "clusters": 2, "noise": 1}
    assert mock_conn.commit.call_count >= 2


def test_run_clustering_pipeline_marks_failed_on_error(monkeypatch):
    keys, arr = _valid_embeddings(n=4)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))

    _, mock_cursor = _mock_pg_connect(
        monkeypatch, select_fetchone=None, insert_fetchone=("run-fail",)
    )

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("umap murio")

    monkeypatch.setattr(clustering, "run_umap_clustering", _boom)

    with pytest.raises(RuntimeError):
        run_clustering_pipeline(Settings())

    failed_calls = [c for c in mock_cursor.execute.call_args_list if "status = 'failed'" in c[0][0]]
    assert len(failed_calls) == 1


def test_run_clustering_pipeline_all_noise_no_labeling(monkeypatch):
    keys, arr = _valid_embeddings(n=4)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))

    _mock_pg_connect(monkeypatch, select_fetchone=None, insert_fetchone=("run-noise",))

    labels = np.full(4, -1, dtype=np.int64)
    probs = np.zeros(4, dtype=np.float64)
    monkeypatch.setattr(
        clustering, "run_umap_clustering", lambda _emb, _settings: np.zeros((4, 15))
    )
    monkeypatch.setattr(clustering, "run_hdbscan", lambda _vecs, _settings: (labels, probs))
    monkeypatch.setattr(clustering, "persist_cluster_assignments", lambda *_args, **_kwargs: None)
    labeled = MagicMock()
    monkeypatch.setattr(clustering, "label_clusters", labeled)

    result = run_clustering_pipeline(Settings())
    assert result == {"run_id": "run-noise", "clusters": 0, "noise": 4}
    labeled.assert_not_called()
