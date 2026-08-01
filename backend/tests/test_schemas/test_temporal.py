import pytest
from pydantic import ValidationError

from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult


class TestTimeFilterOut:
    def test_valid_with_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
        )
        assert tf.requiere_filtro_tiempo is True
        assert tf.fecha_inicio == "2025-07-15 00:00:00"
        assert tf.fecha_fin == "2025-07-15 23:59:59"
        assert tf.texto_busqueda_semantica == "Que dijo Sheinbaum sobre el T-MEC"

    def test_valid_without_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="postura sobre energia nuclear",
        )
        assert tf.requiere_filtro_tiempo is False
        assert tf.fecha_inicio is None
        assert tf.fecha_fin is None

    def test_rejects_requires_filter_without_dates(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                texto_busqueda_semantica="algo",
            )

    def test_rejects_malformed_date_format(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio="15/07/2025",
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )

    def test_rejects_requires_filter_with_none_date(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio=None,
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )

    def test_rejects_requires_filter_with_none_end_date(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio="2025-07-15 00:00:00",
                fecha_fin=None,
                texto_busqueda_semantica="algo",
            )

    def test_rejects_reversed_date_range(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio="2025-07-16 00:00:00",
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )


class TestTimeParserResult:
    def test_successful_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="test",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=False,
            raw_llm_response='{"requiere_filtro_tiempo":true}',
        )
        assert result.fallback_ocurrido is False
        assert result.filter_out == tf

    def test_fallback_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="query original",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=True,
            raw_llm_response="respuesta invalida del LLM",
        )
        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
