import pytest
from pydantic import ValidationError

from lakehouse.schemas.chat import ChatRequest, ChatResponse, SourceChunk


class TestChatRequest:
    def test_valid_request(self):
        r = ChatRequest(query="¿Cómo va la reforma?")
        assert r.query == "¿Cómo va la reforma?"

    def test_rejects_empty_query(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="")


class TestSourceChunk:
    def test_valid_source(self):
        s = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El día de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
        )
        assert s.similarity == 0.95
        assert s.conference_url == "https://example.com"


class TestChatResponse:
    def test_valid_response(self):
        r = ChatResponse(
            answer="La reforma va bien.",
            sources=[
                SourceChunk(
                    conference_date="2024-10-01",
                    conference_id="abc123",
                    participant="PRESIDENTA",
                    chunk_text="El día de hoy...",
                    similarity=0.95,
                    conference_url="https://example.com",
                )
            ],
            token_usage={"prompt": 100, "completion": 50},
        )
        assert len(r.sources) == 1
        assert r.token_usage["prompt"] == 100


class TestSourceChunkNewFields:
    def test_with_qualitative_label(self):
        s = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El dia de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
            qualitative_label="Alta",
        )
        assert s.qualitative_label == "Alta"
        assert s.embedding_3d is None

    def test_with_embedding_3d(self):
        s = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El dia de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
            qualitative_label="Media",
            embedding_3d=[1.0, 2.0, 3.0],
        )
        assert s.embedding_3d == [1.0, 2.0, 3.0]
        assert s.qualitative_label == "Media"

    def test_valid_labels(self):
        for label in ("Alta", "Media", "Baja"):
            s = SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc",
                participant="X",
                chunk_text="texto",
                similarity=0.5,
                qualitative_label=label,
            )
            assert s.qualitative_label == label


class TestChatResponseNewFields:
    def test_with_model_and_latency(self):
        r = ChatResponse(
            answer="respuesta",
            sources=[],
            token_usage={"prompt": 100, "completion": 50, "total": 150},
            model_used="gemma4",
            latency_ms=1250.5,
        )
        assert r.model_used == "gemma4"
        assert r.latency_ms == 1250.5
        assert r.token_usage["total"] == 150
