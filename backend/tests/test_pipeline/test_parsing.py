from lakehouse.pipeline.dlq import DLQ
from lakehouse.pipeline.parsing import _detect_participant, parse_html_to_interventions
from lakehouse.schemas.silver import InterventionRecord

SAMPLE_HTML = """
<html><body><main>
<p><strong>PRESIDENTA CLAUDIA SHEINBAUM PARDO:</strong> Buenos días. Hoy vamos a informar sobre los avances.</p>
<p><strong>PREGUNTA:</strong> ¿Cómo va la reforma energética?</p>
<p><strong>REPORTERA MARÍA LÓPEZ:</strong> Señora presidenta, ¿cuándo estará lista?</p>
</main></body></html>
"""


class TestParseHtml:
    def test_extracts_interventions(self):
        result = parse_html_to_interventions(
            raw_html=SAMPLE_HTML,
            source_url="https://example.com/a",
            conference_date="2024-10-01",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        assert len(interventions) == 2

    def test_detects_participant_names(self):
        result = parse_html_to_interventions(
            raw_html=SAMPLE_HTML,
            source_url="https://example.com/a",
            conference_date="2024-10-01",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        assert interventions[0].participant == "PRESIDENTA CLAUDIA SHEINBAUM PARDO"
        assert interventions[1].participant == "REPORTERA MARÍA LÓPEZ"
        assert interventions[0].pregunta_activa == ""

    def test_tracks_pregunta_activa(self):
        result = parse_html_to_interventions(
            raw_html=SAMPLE_HTML,
            source_url="https://example.com/a",
            conference_date="2024-10-01",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        assert interventions[0].pregunta_activa == ""
        assert "reforma energética" in interventions[1].pregunta_activa

    def test_empty_html_returns_empty(self):
        result = parse_html_to_interventions(
            raw_html="<html><body></body></html>",
            source_url="https://example.com",
            conference_date="2024-10-01",
        )
        assert len(result) == 0  # No interventions detected


class TestParticipantDetection:
    def test_detect_strong_participant(self):
        text = "<p><strong>PRESIDENTA CLAUDIA SHEINBAUM PARDO:</strong> Buenos días</p>"
        name = _detect_participant(text)
        assert name == "PRESIDENTA CLAUDIA SHEINBAUM PARDO"

    def test_no_match_returns_desconocido(self):
        name = _detect_participant("<p>Some text without strong tag</p>")
        assert name == "DESCONOCIDO"


class TestDLQ:
    def test_add_and_count(self):
        dlq = DLQ()
        dlq.add("rec_1", "participant_not_detected", "<html></html>")
        assert dlq.count() == 1

    def test_get_records(self):
        dlq = DLQ()
        dlq.add("rec_1", "empty_after_clean", "<html></html>")
        records = dlq.get_records()
        assert records[0].rejection_reason == "empty_after_clean"
