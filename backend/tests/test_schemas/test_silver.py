import pytest
from pydantic import ValidationError

from lakehouse.schemas.silver import ConferenceRecord, DLQRejectRecord, InterventionRecord


class TestConferenceRecord:
    def test_valid_conference(self):
        c = ConferenceRecord(
            conference_id="conf_20241001",
            date="2024-10-01",
            title="Conferencia matutina",
            url="https://example.com",
        )
        assert c.conference_id == "conf_20241001"

    def test_rejects_invalid_date(self):
        with pytest.raises(ValidationError):
            ConferenceRecord(
                conference_id="conf_1",
                date="not-a-date",
                title="test",
                url="https://example.com",
            )


class TestInterventionRecord:
    def test_valid_intervention(self):
        r = InterventionRecord(
            intervention_key="parent_conf_20241001_001_a1b2c3",
            conference_id="conf_20241001",
            participant="PRESIDENTA CLAUDIA SHEINBAUM PARDO",
            text="Buenos días. El día de hoy vamos a informar...",
            pregunta_activa="¿Cómo va la reforma?",
            chunk_index=0,
            url="https://example.com/conf-2024-10-01",
        )
        assert r.parent_key == "parent_conf_20241001"
        assert r.url == "https://example.com/conf-2024-10-01"

    def test_participant_defaults_to_desconocido(self):
        r = InterventionRecord(
            intervention_key="key_123",
            conference_id="conf_1",
            text="Hello",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )
        assert r.participant == "DESCONOCIDO"


class TestDLQRejectRecord:
    def test_valid_reject(self):
        d = DLQRejectRecord(
            source_record_id="rec_123",
            rejection_reason="participant_not_detected",
            raw_data="<html>bad</html>",
        )
        assert d.rejection_reason == "participant_not_detected"
