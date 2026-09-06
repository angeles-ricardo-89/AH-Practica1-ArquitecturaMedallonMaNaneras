from __future__ import annotations

from fastapi.testclient import TestClient

from lakehouse.config import Settings
from lakehouse.main import create_app


def _app_with_static(static_dir: str, *, app_env: str = "production") -> TestClient:
    settings = Settings(app_env=app_env, frontend_dist_dir=static_dir)
    return TestClient(create_app(settings))


class TestStaticServing:
    def test_index_served_at_root(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>root</html>")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.text == "<html>root</html>"

    def test_spa_fallback_serves_index_for_client_route(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/login", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert resp.text == "<html>app</html>"

    def test_unknown_non_html_path_is_404_not_index(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/no-such-route")
        assert resp.status_code == 404

    def test_asset_file_served_with_content_type(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('hi')")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/assets/app.js")
        assert resp.status_code == 200
        assert resp.text == "console.log('hi')"
        assert resp.headers["content-type"].startswith("text/javascript")

    def test_health_still_served_by_router(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_protected_api_unaffected_by_static(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        client = _app_with_static(str(tmp_path))
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_no_static_when_dir_not_configured(self) -> None:
        client = TestClient(create_app(Settings(app_env="local", frontend_dist_dir="")))
        resp = client.get("/")
        assert resp.status_code == 404

    def test_docs_disabled_in_production(self, tmp_path) -> None:
        (tmp_path / "index.html").write_text("<html>app</html>")
        client = _app_with_static(str(tmp_path), app_env="production")
        for path in ("/docs", "/redoc", "/openapi.json"):
            resp = client.get(path)
            assert resp.status_code == 404
