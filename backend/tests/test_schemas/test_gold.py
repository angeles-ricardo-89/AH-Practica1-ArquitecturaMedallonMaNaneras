import pytest
from pydantic import ValidationError

from lakehouse.schemas.gold import EnrichmentResult, RagCorpusRecord


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


class TestEnrichmentResult:
    def test_defaults_all_zero(self):
        r = EnrichmentResult()
        assert r.total == 0
        assert r.failed == 0
        assert r.embedded == 0
        assert r.failed_to_embed == 0
        assert r.mapped_3d == 0
        assert r.failed_to_map == 0
        assert r.clustered == 0
        assert r.noise == 0
        assert r.clusters == 0
        assert r.clustered_with_labels == 0
        assert r.failed_to_label == 0

    def test_populates_all_fields(self):
        r = EnrichmentResult(
            total=8,
            failed=2,
            embedded=6,
            failed_to_embed=2,
            mapped_3d=6,
            failed_to_map=0,
            clustered=6,
            noise=1,
            clusters=3,
            clustered_with_labels=2,
            failed_to_label=1,
        )
        assert r.total == 8
        assert r.failed == 2
        assert r.mapped_3d == 6
        assert r.clusters == 3
        assert r.clustered_with_labels == 2
        assert r.failed_to_label == 1
        assert r.model_dump()["mapped_3d"] == 6

    def test_rejects_non_int(self):
        with pytest.raises(ValidationError):
            EnrichmentResult(total="ocho")
