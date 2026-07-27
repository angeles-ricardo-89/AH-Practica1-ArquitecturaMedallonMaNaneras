from fastapi.testclient import TestClient

from lakehouse.main import app

client = TestClient(app)


class TestHealth:
    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestSearchEndpoint:
    def test_search_valid_query(self):
        response = client.post("/search/", json={"query": "reforma energética"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)
        assert data["total"] == 0

    def test_search_empty_query_rejected(self):
        response = client.post("/search/", json={"query": ""})
        assert response.status_code == 422

    def test_search_blank_query_rejected(self):
        response = client.post("/search/", json={"query": "   "})
        assert response.status_code == 422

    def test_search_query_too_long_rejected(self):
        response = client.post("/search/", json={"query": "x" * 501})
        assert response.status_code == 422

    def test_search_custom_top_k(self):
        response = client.post("/search/", json={"query": "salud", "top_k": 3})
        assert response.status_code == 200

    def test_search_with_filters(self):
        response = client.post(
            "/search/",
            json={
                "query": "reforma",
                "filters": {"participant": "AMLO"},
            },
        )
        assert response.status_code == 200

    def test_search_with_strategy_hnsw(self):
        response = client.post("/search/", json={"query": "test"})
        assert response.status_code == 200
        assert response.json()["strategy"] == "hnsw"

    def test_search_top_k_out_of_range_rejected(self):
        response = client.post("/search/", json={"query": "test", "top_k": 0})
        assert response.status_code == 422
        response = client.post("/search/", json={"query": "test", "top_k": 51})
        assert response.status_code == 422

    def test_search_empty_results(self):
        response = client.post("/search/", json={"query": "xyz"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["total"] == 0
