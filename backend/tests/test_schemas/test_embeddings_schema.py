from lakehouse.schemas.embeddings import Embedding3DPoint, Embedding3DResponse


class TestEmbedding3DPoint:
    def test_valid(self):
        p = Embedding3DPoint(chunk_key="abc123", x=1.2, y=-0.5, z=3.1, conference_date="2026-01-15")
        assert p.x == 1.2
        assert p.y == -0.5
        assert p.z == 3.1
        assert p.conference_date == "2026-01-15"


class TestEmbedding3DResponse:
    def test_with_points(self):
        r = Embedding3DResponse(
            points=[
                Embedding3DPoint(chunk_key="a", x=0.0, y=0.0, z=0.0, conference_date="2026-01-15"),
                Embedding3DPoint(chunk_key="b", x=1.0, y=1.0, z=1.0, conference_date="2026-01-16"),
            ]
        )
        assert len(r.points) == 2

    def test_empty(self):
        r = Embedding3DResponse(points=[])
        assert r.points == []
