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
