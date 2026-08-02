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
            assert data["ultima_corrida_global"] == "2026-08-01T10:00:10+00:00"
        finally:
            self._clean_pipeline_runs(conn_str)

    def test_layers_returns_newest_run_per_capa(self, monkeypatch):
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
                conn_str, "r2", "silver", "ok", "2026-08-01T10:00:05Z", "2026-08-01T10:00:20Z"
            )
            self._insert_run(
                conn_str, "r3", "gold", "ok", "2026-08-01T10:00:10Z", "2026-08-01T10:00:30Z"
            )
            self._insert_run(
                conn_str, "r4", "bronze", "error", "2026-08-01T10:30:00Z", "2026-08-01T10:30:15Z"
            )

            resp = client.get("/observability/pipeline/layers")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["layers"]) == 3
            bronze = next(l for l in data["layers"] if l["capa"] == "bronze")
            assert bronze["run_id"] == "r4"
            assert bronze["status"] == "error"
            assert bronze["started_at"] == "2026-08-01T10:30:00+00:00"
            assert data["health_global"] == "Failed"
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


class TestPipelineLogsByLayer:
    def test_logs_by_layer_filters_correctly(self, monkeypatch, tmp_path):
        log_dir = tmp_path / "logs" / "2026-08-01"
        log_dir.mkdir(parents=True)
        bronze_log = log_dir / "bronze_20260801_12345.log"
        bronze_log.write_text("[bronze] linea 1\n[bronze] linea 2\n")
        silver_log = log_dir / "silver_20260801_12346.log"
        silver_log.write_text("[silver] linea A\n[silver] linea B\n[silver] linea C\n")

        monkeypatch.setattr(
            "lakehouse.api.routers.observability._find_layer_logs",
            lambda layer, _base_dir: [str(bronze_log)] if layer == "bronze" else [str(silver_log)],
        )

        resp = client.get("/observability/pipeline/logs/bronze?lines=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 2
        assert data["total_lines"] == 2

    def test_logs_by_layer_empty_for_missing_layer(self, monkeypatch):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._find_layer_logs",
            lambda _layer, _base_dir: [],
        )
        resp = client.get("/observability/pipeline/logs/gold?lines=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lines"] == []
        assert data["total_lines"] == 0

    def test_logs_by_layer_returns_most_recent_lines_across_files(self, monkeypatch, tmp_path):
        oldest_log = tmp_path / "oldest.log"
        oldest_log.write_text("o1\no2\no3\no4\no5\n")
        newest_log = tmp_path / "newest.log"
        newest_log.write_text("n1\nn2\n")

        monkeypatch.setattr(
            "lakehouse.api.routers.observability._find_layer_logs",
            lambda _layer, _base_dir: [str(newest_log), str(oldest_log)],
        )

        resp = client.get("/observability/pipeline/logs/bronze?lines=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lines"] == ["o5", "n1", "n2"]
        assert data["total_lines"] == 7
