import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.api.routers import clusters
from lakehouse.config import Settings
from lakehouse.main import app
from lakehouse.pipeline.clustering import ensure_clustering_schema

client = TestClient(app)


def _conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _ensure_schema(monkeypatch) -> str:
    conn_str = _conn_str()
    monkeypatch.setattr(
        "lakehouse.api.routers.clusters._get_pg_conn_str",
        lambda: conn_str,
    )
    with psycopg.connect(conn_str) as conn:
        ensure_clustering_schema(conn)
    return conn_str


def test_get_clusters_latest_returns_200(monkeypatch):
    _ensure_schema(monkeypatch)
    response = client.get("/clusters/latest")
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "clusters" in data
    assert "points" in data


def test_get_clusters_latest_no_data_returns_empty(monkeypatch):
    _ensure_schema(monkeypatch)
    response = client.get("/clusters/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found" or data["run_id"] == ""


def test_get_clusters_by_run_id_not_found(monkeypatch):
    _ensure_schema(monkeypatch)
    response = client.get("/clusters/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"


def test_get_clusters_latest_returns_data(monkeypatch):
    conn_str = _ensure_schema(monkeypatch)

    run_id = "11111111-1111-1111-1111-111111111111"
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gold.clustering_runs
                (run_id, status, cluster_count, noise_count, corpus_fingerprint,
                 parameters_hash, embedding_model)
            VALUES (%s, 'completed', 1, 0, 'fp', 'ph', 'model')
            """,
            (run_id,),
        )
        cur.execute(
            """
            INSERT INTO gold.cluster_labels
                (clustering_run_id, cluster_id, cluster_label, label_status,
                 sample_size, sample_chunk_keys)
            VALUES (%s, 0, 'Salud Publica', 'completed', 1, ARRAY['p1'])
            """,
            (run_id,),
        )
        cur.execute(
            """
            INSERT INTO gold.rag_corpus
                (chunk_key, conference_id, participant, chunk_text, payload,
                 cluster_id, cluster_pertenencia, clustering_run_id, embedding_3d)
            VALUES
                ('cluster_point_1', 'c1', 'p1', 'texto 1', 'pl1',
                 0, 0.9, %s, ARRAY[1.0, 2.0, 3.0])
            ON CONFLICT (chunk_key) DO NOTHING
            """,
            (run_id,),
        )
        conn.commit()

    try:
        response = client.get(f"/clusters/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["cluster_count"] == 1
        assert data["clusters"][0]["label"] == "Salud Publica"
        assert data["clusters"][0]["chunk_count"] == 1
        assert data["points"][0]["chunk_key"] == "cluster_point_1"
        assert data["points"][0]["x"] == pytest.approx(1.0)
    finally:
        with psycopg.connect(conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'cluster_point_%'")
            conn.execute("DELETE FROM gold.cluster_labels WHERE clustering_run_id = %s", (run_id,))
            conn.execute("DELETE FROM gold.clustering_runs WHERE run_id = %s", (run_id,))
            conn.commit()


def test_get_pg_conn_str_builds_url():
    conn_str = clusters._get_pg_conn_str()
    assert conn_str.startswith("postgresql://")
    assert "@localhost:5433/mananeras" in conn_str
