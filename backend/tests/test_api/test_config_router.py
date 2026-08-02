from pathlib import Path

from fastapi.testclient import TestClient

from lakehouse.main import app

client = TestClient(app)


class TestConfigEndpoint:
    def test_returns_config(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ambiente"] == "staging"
        assert data["version"] == "0.1.0"
        assert "modelos" in data
        assert "llm" in data["modelos"]
        assert "embedding" in data["modelos"]

    def test_default_ambiente_when_no_env(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ambiente"] == "local"

    def test_docker_detection(self, monkeypatch, tmp_path):
        fake_dockerenv = tmp_path / ".dockerenv"
        fake_dockerenv.write_text("")
        monkeypatch.setattr(Path, "exists", lambda self: self == Path("/.dockerenv"))
        resp = client.get("/config")
        data = resp.json()
        assert data["docker"] is True
