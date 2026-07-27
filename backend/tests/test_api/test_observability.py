import json

import pytest
from fastapi.testclient import TestClient

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
