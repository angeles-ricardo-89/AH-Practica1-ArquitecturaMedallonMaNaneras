from lakehouse.pipeline.dlq import DLQ
from lakehouse.pipeline.parsing import (
    _detect_participant,
    _extract_title,
    build_conference_record,
    parse_conference_date,
    parse_html_to_interventions,
)
from lakehouse.schemas.silver import ConferenceRecord, DLQRejectRecord, InterventionRecord

SAMPLE_HTML = """
<html><body><main>
<p><strong>PRESIDENTA CLAUDIA SHEINBAUM PARDO:</strong> Buenos días. Hoy vamos a informar sobre los avances.</p>
<p><strong>PREGUNTA:</strong> ¿Cómo va la reforma energética?</p>
<p><strong>REPORTERA MARÍA LÓPEZ:</strong> Señora presidenta, ¿cuándo estará lista?</p>
</main></body></html>
"""

REAL_WORLD_HTML = """
<html><body><main>
<p><strong>PRESIDENTA DE M&Eacute;XICO, CLAUDIA SHEINBAUM PARDO:</strong> Buenos d&iacute;as.</p>
<p><strong>PREGUNTA: Buenos d&iacute;as, Presidenta.</strong></p>
<p><strong>PRESIDENTA DE M&Eacute;XICO, CLAUDIA SHEINBAUM PARDO:</strong> Disculpen, se nos hizo un poco tarde ah&iacute; en el Gabinete de Seguridad.</p>
<p>&mdash;Si&eacute;ntense, por favor&mdash;.</p>
<p>Bueno, hoy es lunes 27 de julio, ya se est&aacute; acabando julio.</p>
<p><strong>INTERVENCI&Oacute;N DE REPORTERO:</strong> Gracias, Presidenta. Mi pregunta es sobre energ&iacute;a.</p>
<p>¿Cu&aacute;ndo se espera que las nuevas plantas solares entren en operaci&oacute;n?</p>
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

    def test_empty_content_sends_to_dlq(self):
        html = """
        <html><body><main>
        <p><strong>PRESIDENTA:</strong><br></p>
        </main></body></html>
        """
        result = parse_html_to_interventions(
            raw_html=html,
            source_url="https://example.com/a",
            conference_date="2024-10-01",
        )
        dlq = [r for r in result if isinstance(r, DLQRejectRecord)]
        assert len(dlq) == 1
        assert dlq[0].rejection_reason == "empty_after_clean"

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


class TestParseHtmlRealWorld:
    def test_captures_interventions_from_real_format(self):
        result = parse_html_to_interventions(
            raw_html=REAL_WORLD_HTML,
            source_url="https://example.com/conf",
            conference_date="2026-07-27",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        assert len(interventions) == 3

    def test_accumulates_continuation_paragraphs(self):
        result = parse_html_to_interventions(
            raw_html=REAL_WORLD_HTML,
            source_url="https://example.com/conf",
            conference_date="2026-07-27",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        presidenta_pre = interventions[0]
        assert presidenta_pre.participant == "PRESIDENTA DE MÉXICO, CLAUDIA SHEINBAUM PARDO"
        assert "Buenos días" in presidenta_pre.text
        assert presidenta_pre.pregunta_activa == ""

        presidenta_post = interventions[1]
        assert presidenta_post.participant == "PRESIDENTA DE MÉXICO, CLAUDIA SHEINBAUM PARDO"
        assert "Disculpen" in presidenta_post.text
        assert "Siéntense" in presidenta_post.text
        assert "hoy es lunes 27 de julio" in presidenta_post.text
        assert presidenta_post.pregunta_activa == "Buenos días, Presidenta."

    def test_extracts_pregunta_from_strong(self):
        result = parse_html_to_interventions(
            raw_html=REAL_WORLD_HTML,
            source_url="https://example.com/conf",
            conference_date="2026-07-27",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        assert "Buenos días, Presidenta." in interventions[1].pregunta_activa
        assert "Buenos días, Presidenta." in interventions[2].pregunta_activa

    def test_acumula_continuacion_reportero(self):
        result = parse_html_to_interventions(
            raw_html=REAL_WORLD_HTML,
            source_url="https://example.com/conf",
            conference_date="2026-07-27",
        )
        interventions = [r for r in result if isinstance(r, InterventionRecord)]
        reportero = interventions[2]
        assert reportero.participant == "INTERVENCIÓN DE REPORTERO"
        assert "Gracias, Presidenta" in reportero.text
        assert (
            "Cuándo se espera que las nuevas plantas solares entren en operación" in reportero.text
        )


class TestParticipantDetection:
    def test_detect_strong_participant(self):
        text = "<p><strong>PRESIDENTA CLAUDIA SHEINBAUM PARDO:</strong> Buenos días</p>"
        name = _detect_participant(text)
        assert name == "PRESIDENTA CLAUDIA SHEINBAUM PARDO"

    def test_no_match_returns_desconocido(self):
        name = _detect_participant("<p>Some text without strong tag</p>")
        assert name == "DESCONOCIDO"


class TestConferenceRecordBuilder:
    def test_builds_conference_record(self):
        html = "<html><title>Conferencia matutina 2024</title><body><main><p>text</p></main></body></html>"
        record = build_conference_record(
            source_url="https://example.com/conf-2024-10-01",
            conference_date="2024-10-01",
            raw_html=html,
        )
        assert isinstance(record, ConferenceRecord)
        assert record.date == "2024-10-01"
        assert record.url == "https://example.com/conf-2024-10-01"

    def test_uses_title_from_html(self):
        html = "<html><title>Conferencia del presidente</title><body><main><p>text</p></main></body></html>"
        record = build_conference_record(
            source_url="https://example.com/conf",
            conference_date="2024-10-01",
            raw_html=html,
        )
        assert "Conferencia del presidente" in record.title

    def test_fallback_title_without_title_tag(self):
        html = "<html><body><main><p>text</p></main></body></html>"
        record = build_conference_record(
            source_url="https://example.com/conf",
            conference_date="2024-10-02",
            raw_html=html,
        )
        assert "2024-10-02" in record.title

    def test_conference_id_is_deterministic(self):
        html = "<html><body><main><p>text</p></main></body></html>"
        a = build_conference_record("https://example.com/x", "2024-10-01", html)
        b = build_conference_record("https://example.com/x", "2024-10-01", html)
        assert a.conference_id == b.conference_id


class TestTitleExtraction:
    def test_extracts_title_tag(self):
        html = "<html><title>  Mi título  </title><body><p>foo</p></body></html>"
        assert _extract_title(html) == "Mi título"

    def test_no_title_returns_empty(self):
        assert _extract_title("<html><body><p>foo</p></body></html>") == ""

    def test_html_entities_unescaped(self):
        html = "<html><title>Sheinbaum &amp; AMLO</title><body></body></html>"
        assert _extract_title(html) == "Sheinbaum & AMLO"


class TestParseConferenceDate:
    def test_from_html_title(self):
        html = "<html><title>Presidencia de la República | 27 de julio de 2026</title><body><main><p>text</p></main></body></html>"
        assert parse_conference_date(html, "https://example.com/x") == "2026-07-27"

    def test_from_url_fallback(self):
        html = "<html><body><p>no date here</p></body></html>"
        url = "https://www.gob.mx/presidencia/articulos/version-27-de-julio-de-2026"
        assert parse_conference_date(html, url) == "2026-07-27"

    def test_html_takes_precedence_over_url(self):
        html = "<html><title>Presidencia de la República | 1 de enero de 2025</title></html>"
        url = "https://example.com/15-de-marzo-de-2024"
        assert parse_conference_date(html, url) == "2025-01-01"

    def test_different_months(self):
        cases = [
            ("enero", "01"),
            ("febrero", "02"),
            ("marzo", "03"),
            ("abril", "04"),
            ("mayo", "05"),
            ("junio", "06"),
            ("julio", "07"),
            ("agosto", "08"),
            ("septiembre", "09"),
            ("octubre", "10"),
            ("noviembre", "11"),
            ("diciembre", "12"),
        ]
        for month_name, month_num in cases:
            html = f"<html><title>Presidencia de la República | 15 de {month_name} de 2024</title></html>"
            assert parse_conference_date(html, "") == f"2024-{month_num}-15"

    def test_single_digit_day(self):
        html = "<html><title>Presidencia de la República | 3 de mayo de 2024</title></html>"
        assert parse_conference_date(html, "") == "2024-05-03"

    def test_returns_none_when_no_date(self):
        html = "<html><body><p>sin fecha</p></body></html>"
        url = "https://example.com/sin-fecha"
        assert parse_conference_date(html, url) is None

    def test_returns_none_on_invalid_month(self):
        html = "<html><title>Presidencia de la República | 15 de falsario de 2024</title></html>"
        url = "https://example.com/15-de-falsario-de-2024"
        assert parse_conference_date(html, url) is None


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
