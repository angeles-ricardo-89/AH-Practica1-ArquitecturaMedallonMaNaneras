from __future__ import annotations

import pytest

from lakehouse.config import Settings
from lakehouse.services.prod_visuals import sync_production_visuals, target_settings

NEON_URL = (
    "postgresql://conferencias_matutinas:npg_abc@ep-demo-pooler.us-east-1.aws.neon.tech/"
    "mananeras?sslmode=require"
)


class TestTargetSettings:
    def test_parses_neon_url_into_postgres_fields(self) -> None:
        settings = Settings(app_env="local", neon_database_url=NEON_URL)
        target = target_settings(settings)
        assert target.postgres_host == "ep-demo-pooler.us-east-1.aws.neon.tech"
        assert target.postgres_port == 5432
        assert target.postgres_user == "conferencias_matutinas"
        assert target.postgres_password == "npg_abc"
        assert target.postgres_db == "mananeras"
        assert target.ollama_embed_model == "gemini-embedding-001"

    def test_raises_without_neon_url(self) -> None:
        with pytest.raises(RuntimeError):
            target_settings(Settings(app_env="local", neon_database_url=""))


class TestSyncProductionVisuals:
    def test_orchestrates_3d_clustering_and_labels(self, monkeypatch) -> None:
        calls: dict[str, int] = {"3d": 0, "cluster": 0, "label": 0}

        def fake_3d(_conn: str) -> int:
            calls["3d"] += 1
            return 11120

        def fake_clustering(_settings, force: bool) -> dict:
            calls["cluster"] += 1
            assert force is True
            return {"run_id": "run-1", "clusters": 3, "noise": 5}

        def fake_labeling(_settings, run_id: str | None) -> dict:
            calls["label"] += 1
            assert run_id == "run-1"
            return {"completed": 3, "failed": 0}

        monkeypatch.setattr("lakehouse.services.prod_visuals._compute_umap_3d", fake_3d)
        monkeypatch.setattr("lakehouse.services.prod_visuals.run_clustering", fake_clustering)
        monkeypatch.setattr("lakehouse.services.prod_visuals.run_labeling", fake_labeling)

        settings = Settings(app_env="local", neon_database_url=NEON_URL)
        out = sync_production_visuals(settings)
        assert out["embedding_3d_updated"] == 11120
        assert out["run_id"] == "run-1"
        assert out["clusters"] == 3
        assert calls == {"3d": 1, "cluster": 1, "label": 1}

    def test_raises_when_clustering_returns_no_run(self, monkeypatch) -> None:
        monkeypatch.setattr("lakehouse.services.prod_visuals._compute_umap_3d", lambda _conn: 0)
        monkeypatch.setattr(
            "lakehouse.services.prod_visuals.run_clustering", lambda _s, **_ignore: None
        )
        settings = Settings(app_env="local", neon_database_url=NEON_URL)
        with pytest.raises(RuntimeError, match="run_id"):
            sync_production_visuals(settings)
