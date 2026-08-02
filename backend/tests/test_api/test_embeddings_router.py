import psycopg
from fastapi.testclient import TestClient

from lakehouse.api.routers import embeddings
from lakehouse.config import Settings
from lakehouse.db.observability_conn import add_embedding_3d_column
from lakehouse.main import app

client = TestClient(app)


def _conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


class TestEmbeddings3D:
    def test_returns_points_with_3d_data(self, monkeypatch):
        conn_str = _conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.embeddings._get_pg_conn_str",
            lambda: conn_str,
        )

        add_embedding_3d_column(conn_str)

        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus
            (chunk_key, conference_id, participant, chunk_text, payload, url, embedding_3d, conference_date)
            VALUES
            ('test-ck-1', 'conf-1', 'TEST', 'texto prueba 1', 'payload 1', 'http://x.com',
             ARRAY[1.0, 2.0, 3.0], '2026-01-15'),
            ('test-ck-2', 'conf-2', 'TEST', 'texto prueba 2', 'payload 2', 'http://x.com',
             ARRAY[4.0, 5.0, 6.0], '2026-01-16')
            ON CONFLICT (chunk_key) DO UPDATE SET embedding_3d = EXCLUDED.embedding_3d
        """)

        try:
            resp = client.get("/embeddings/3d")
            assert resp.status_code == 200
            data = resp.json()
            points = {p["chunk_key"]: p for p in data["points"]}
            test_points = {k: v for k, v in points.items() if k.startswith("test-ck-")}
            assert test_points["test-ck-1"] == {
                "chunk_key": "test-ck-1",
                "x": 1.0,
                "y": 2.0,
                "z": 3.0,
                "conference_date": "2026-01-15",
            }
            assert test_points["test-ck-2"] == {
                "chunk_key": "test-ck-2",
                "x": 4.0,
                "y": 5.0,
                "z": 6.0,
                "conference_date": "2026-01-16",
            }
        finally:
            cur.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'test-ck-%'")
            conn.close()

    def test_empty_when_no_points(self, monkeypatch):
        conn_str = _conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.embeddings._get_pg_conn_str",
            lambda: conn_str,
        )
        add_embedding_3d_column(conn_str)
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "UPDATE gold.rag_corpus SET embedding_3d = NULL WHERE chunk_key LIKE 'test-ck-%'"
        )
        cur.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'test-ck-%'")
        conn.close()

        resp = client.get("/embeddings/3d")
        assert resp.status_code == 200
        data = resp.json()
        test_points = [p for p in data["points"] if p["chunk_key"].startswith("test-ck-")]
        assert test_points == []

    def test_returns_empty_points_on_db_error(self, monkeypatch):
        conn_str = _conn_str()
        monkeypatch.setattr(
            "lakehouse.api.routers.embeddings._get_pg_conn_str",
            lambda: conn_str,
        )

        def _raise(_conn_str: str) -> None:
            raise psycopg.Error("db down")

        monkeypatch.setattr(embeddings.psycopg, "connect", _raise)

        resp = client.get("/embeddings/3d")
        assert resp.status_code == 200
        assert resp.json() == {"points": []}

    def test_get_pg_conn_str_builds_url(self):
        conn_str = embeddings._get_pg_conn_str()
        assert conn_str.startswith("postgresql://")
        assert "@localhost:5433/mananeras" in conn_str
