from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import numpy as np
import psycopg
import pytest

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import ensure_bronze_table, get_connection
from lakehouse.pipeline.verify import ensure_verify_database, load_frozen_bronze, verify_pipeline

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "bronze"


class _FakeEmbedResponse:
    status_code = 200

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    def json(self) -> dict:
        return {"embeddings": [self._vector]}


class _FakeLabelResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "Salud Publica"}}]}


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


_SALUD_CENTROID = np.random.RandomState(1).randn(768)
_ECONOMIA_CENTROID = np.random.RandomState(2).randn(768)


def _fake_embed(text: str) -> list[float]:
    lower = text.lower()
    if "salud" in lower:
        centroid = _SALUD_CENTROID
    elif "econom" in lower:
        centroid = _ECONOMIA_CENTROID
    else:
        centroid = np.zeros(768)
    rng = np.random.RandomState(_stable_seed(text))
    return (centroid + rng.randn(768) * 0.5).tolist()


def _fake_embed_post(self, url: str, json: dict | None = None, timeout: float | None = None):  # noqa: ANN202
    text = (json or {}).get("input", "")
    return _FakeEmbedResponse(_fake_embed(text))


def _fake_label_post(url: str, json: dict | None = None, timeout: float | None = None):  # noqa: ANN202
    return _FakeLabelResponse()


@pytest.fixture
def verify_settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.ducklake_data_path = str(tmp_path / "verify.duckdb")
    settings.ollama_embed_model = "fixture-embed-test"
    return settings


def test_load_frozen_bronze_inserts_all_files(verify_settings: Settings) -> None:
    conn = get_connection(verify_settings.ducklake_data_path)
    ensure_bronze_table(conn)
    hashes = load_frozen_bronze(conn, str(FIXTURE_DIR))
    conn.close()

    assert len(hashes) == 8
    assert len(set(hashes)) == 8


def test_ensure_verify_database_creates_db_and_vector_extension() -> None:
    settings = Settings()
    test_db = "mananeras_verify_test"
    settings.postgres_db = test_db

    admin_conn_str = "postgresql://mananeras:mananeras@localhost:5433/postgres"
    target_conn_str = f"postgresql://mananeras:mananeras@localhost:5433/{test_db}"

    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{test_db}"')

    try:
        ensure_verify_database(settings)
        with psycopg.connect(target_conn_str) as conn:
            ext = conn.execute(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()[0]
        assert ext == 1

        ensure_verify_database(settings)
    finally:
        with psycopg.connect(admin_conn_str, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{test_db}"')


def test_verify_pipeline_runs_all_layers(
    verify_settings: Settings,
    pg_conn_str: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx.Client, "post", _fake_embed_post)
    monkeypatch.setattr(httpx, "post", _fake_label_post)

    result = verify_pipeline(verify_settings, str(FIXTURE_DIR), clean=False)

    try:
        assert result["bronze"] == 8
        assert result["silver_conferences"] == 8
        assert result["silver_interventions"] == 16
        assert result["silver_dlq"] == 0
        assert result["gold_total"] == 8
        assert result["gold_embedded"] == 8
        assert result["clusters"] == 2
        assert result["noise"] == 0
        assert result["labels_completed"] == 2
        assert result["labels_failed"] == 0
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE url LIKE 'https://fixture.local/%'")
            conn.execute(
                "DELETE FROM gold.cluster_labels WHERE clustering_run_id IN "
                "(SELECT run_id FROM gold.clustering_runs WHERE embedding_model = 'fixture-embed-test')"
            )
            conn.execute(
                "DELETE FROM gold.clustering_runs WHERE embedding_model = 'fixture-embed-test'"
            )
            conn.commit()
