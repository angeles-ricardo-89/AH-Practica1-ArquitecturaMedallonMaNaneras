import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.api.routers.observability import _get_pg_conn_str
from lakehouse.config import Settings
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.main import app

client = TestClient(app)


@pytest.fixture
def temp_status_file(tmp_path):
    path = tmp_path / "cron.status"
    data = {
        "status": "ok",
        "last_run": "2026-07-26T10:00:00Z",
        "last_success": "2026-07-26T10:00:00Z",
        "records_count": 150,
    }
    path.write_text(json.dumps(data))
    return str(path)


@pytest.fixture
def temp_log_file(tmp_path):
    path = tmp_path / "pipeline.log"
    lines = [f"line {i}" for i in range(100)]
    path.write_text("\n".join(lines))
    return str(path)


class TestObservabilityStatus:
    def test_status_returns_ok(self, monkeypatch, temp_status_file):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.STATUS_FILE_PATH",
            temp_status_file,
        )
        resp = client.get("/observability/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["records_count"] == 150

    def test_status_returns_unknown_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.STATUS_FILE_PATH",
            str(tmp_path / "nonexistent.json"),
        )
        resp = client.get("/observability/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"

    def test_status_semaphore_colors(self, monkeypatch, temp_status_file):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.STATUS_FILE_PATH",
            temp_status_file,
        )
        resp = client.get("/observability/status")
        data = resp.json()

        status_to_color = {"ok": "green", "running": "yellow", "error": "red"}
        assert data["semaphore"] == status_to_color.get(data["status"], "gray")


class TestObservabilityLogs:
    def test_logs_returns_lines(self, monkeypatch, temp_log_file):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.LOG_FILE_PATH",
            temp_log_file,
        )
        resp = client.get("/observability/logs?lines=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 5
        assert data["total_lines"] == 100

    def test_logs_defaults_to_50_lines(self, monkeypatch, temp_log_file):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.LOG_FILE_PATH",
            temp_log_file,
        )
        resp = client.get("/observability/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 50

    def test_logs_empty_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability.LOG_FILE_PATH",
            str(tmp_path / "nonexistent.log"),
        )
        resp = client.get("/observability/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lines"] == []
        assert data["total_lines"] == 0


class TestPipelineLayers:
    def _pg_conn_str(self) -> str:
        settings = Settings()
        return (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )

    def _clean_pipeline_runs(self, conn_str: str) -> None:
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        conn.execute("DELETE FROM observability.pipeline_runs")
        conn.close()

    def _insert_run(
        self,
        conn_str: str,
        run_id: str,
        capa: str,
        status: str,
        started: str,
        finished: str,
    ) -> None:
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        conn.execute(
            """INSERT INTO observability.pipeline_runs
            (run_id, capa, status, started_at, finished_at, records_in, records_out)
            VALUES (%s, %s, %s, %s, %s, 150, 140)
            """,
            (run_id, capa, status, started, finished),
        )
        conn.close()

    def test_layers_empty_when_no_runs(self, monkeypatch):
        conn_str = self._pg_conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        ensure_observability_tables(conn_str)
        self._clean_pipeline_runs(conn_str)
        try:
            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert data["layers"] == []
            assert data["health_global"] == "sin datos"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_returns_latest_per_capa(self, monkeypatch):
        conn_str = self._pg_conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        ensure_observability_tables(conn_str)
        self._clean_pipeline_runs(conn_str)
        try:
            conn = psycopg.connect(conn_str)
            conn.autocommit = True
            conn.execute(
                """INSERT INTO observability.pipeline_runs
                (run_id, capa, status, started_at, finished_at, records_in, records_out)
                VALUES
                ('r1', 'bronze', 'ok', '2026-08-01T10:00:00Z', '2026-08-01T10:00:12Z', 150, 150),
                ('r2', 'silver', 'ok', '2026-08-01T10:00:05Z', '2026-08-01T10:00:20Z', 150, 140),
                ('r3', 'gold', 'ok', '2026-08-01T10:00:10Z', '2026-08-01T10:00:30Z', 140, 140)
                """
            )
            conn.close()

            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["layers"]) == 3
            assert data["health_global"] == "Healthy"
            assert data["layers"][0]["capa"] == "bronze"
            assert data["layers"][0]["records_in"] == 150
            assert data["ultima_corrida_global"] == "2026-08-01 10:00:10+00:00"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_health_failed_when_any_error(self, monkeypatch):
        conn_str = self._pg_conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        ensure_observability_tables(conn_str)
        self._clean_pipeline_runs(conn_str)
        try:
            self._insert_run(
                conn_str, "r1", "bronze", "ok", "2026-08-01T10:00:00Z", "2026-08-01T10:00:12Z"
            )
            self._insert_run(
                conn_str, "r2", "silver", "error", "2026-08-01T10:00:05Z", "2026-08-01T10:00:20Z"
            )
            self._insert_run(
                conn_str, "r3", "gold", "ok", "2026-08-01T10:00:10Z", "2026-08-01T10:00:30Z"
            )

            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert data["health_global"] == "Failed"
            silver = next(l for l in data["layers"] if l["capa"] == "silver")
            assert silver["status"] == "error"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_health_degraded_when_running(self, monkeypatch):
        conn_str = self._pg_conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        ensure_observability_tables(conn_str)
        self._clean_pipeline_runs(conn_str)
        try:
            self._insert_run(
                conn_str, "r1", "bronze", "ok", "2026-08-01T10:00:00Z", "2026-08-01T10:00:12Z"
            )
            self._insert_run(conn_str, "r2", "silver", "running", "2026-08-01T10:00:05Z", None)
            self._insert_run(
                conn_str, "r3", "gold", "ok", "2026-08-01T10:00:10Z", "2026-08-01T10:00:30Z"
            )

            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert data["health_global"] == "Degraded"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_health_degraded_when_missing_layers(self, monkeypatch):
        conn_str = self._pg_conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        ensure_observability_tables(conn_str)
        self._clean_pipeline_runs(conn_str)
        try:
            self._insert_run(
                conn_str, "r1", "bronze", "ok", "2026-08-01T10:00:00Z", "2026-08-01T10:00:12Z"
            )

            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["layers"]) == 1
            assert data["health_global"] == "Degraded"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_returns_sin_datos_on_db_error(self, monkeypatch):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: "postgresql://invalid:invalid@localhost:1/invalid",
        )
        resp = client.get("/observability/pipeline/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["layers"] == []
        assert data["health_global"] == "sin datos"

    def test_get_pg_conn_str_builds_url(self):
        conn_str = _get_pg_conn_str()
        assert conn_str.startswith("postgresql://")
        assert "@localhost:5433/mananeras" in conn_str
