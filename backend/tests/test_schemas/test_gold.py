import pytest
from pydantic import ValidationError

from lakehouse.schemas.gold import RagCorpusRecord


class TestRagCorpusRecord:
    def test_valid_record(self):
        r = RagCorpusRecord(
            chunk_key="chunk_conf_1_000_a1b2",
            conference_id="conf_abc123",
            conference_date="2024-10-01",
            participant="PRESIDENTA CLAUDIA SHEINBAUM PARDO",
            chunk_text="El día de hoy vamos a informar sobre...",
            payload="Contexto: Conferencia del 2024-10-01\nParticipante: PRESIDENTA\nPregunta activa: ¿Cómo va la reforma?\nRespuesta: El día de hoy...",
            url="https://example.com",
        )
        assert r.chunk_key == "chunk_conf_1_000_a1b2"
        assert r.url == "https://example.com"

    def test_rejects_empty_chunk_text(self):
        with pytest.raises(ValidationError):
            RagCorpusRecord(
                chunk_key="key_1",
                conference_id="conf1",
                conference_date="2024-10-01",
                participant="test",
                chunk_text="",
                payload="",
                url="https://example.com",
            )

    def test_embedding_optional(self):
        r = RagCorpusRecord(
            chunk_key="key_1",
            conference_id="conf1",
            conference_date="2024-10-01",
            participant="test",
            chunk_text="some text",
            payload="some payload",
            url="https://example.com",
        )
        assert r.embedding is None
