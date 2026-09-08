from __future__ import annotations

from unittest.mock import patch

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser

PATCH_CHAT = "lakehouse.services.temporal_parser.chat_json"


class TestParserGeminiProduction:
    """
    Verifica que el parser temporal extrae correctamente filtros temporales
    cuando el LLM responde en formato JSON compatible con Gemini.
    """

    def test_absoluta_extrae_rango(self):
        """'Que dijo Sheinbaum el 15 de julio de 2025?' debe extraer 2025-07-15."""
        settings = Settings(gemini_api_key="fake-key")

        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2025-07-15 00:00:00",'
                '"fecha_fin":"2025-07-15 23:59:59",'
                '"texto_busqueda_semantica":"discurso Sheinbaum 15 julio 2025"}'
            )
            parser = TemporalParser(settings)
            result = parser.extraer("Que dijo Sheinbaum el 15 de julio de 2025?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"
        assert result.fallback_ocurrido is False

    def test_relativa_ayer(self):
        """'Que paso ayer?' debe extraer fecha de ayer."""
        settings = Settings(gemini_api_key="fake-key")

        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-09-06 00:00:00",'
                '"fecha_fin":"2026-09-06 23:59:59",'
                '"texto_busqueda_semantica":"acontecimientos"}'
            )
            parser = TemporalParser(settings)
            result = parser.extraer("Que paso ayer?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio is not None
        assert result.filter_out.fecha_fin is not None
        assert result.fallback_ocurrido is False

    def test_sin_intento_temporal(self):
        """'Que es la贫血?' no debe activar filtro temporal."""
        settings = Settings(gemini_api_key="fake-key")

        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":false,'
                '"fecha_inicio":null,'
                '"fecha_fin":null,'
                '"texto_busqueda_semantica":"贫血 definicion"}'
            )
            parser = TemporalParser(settings)
            result = parser.extraer("Que es la贫血?")

        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.fallback_ocurrido is False

    def test_lunes_pasado(self):
        """'Que dijo en la conferencia del lunes pasado?' debe extraer fecha del lunes anterior."""
        settings = Settings(gemini_api_key="fake-key")

        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-08-31 00:00:00",'
                '"fecha_fin":"2026-08-31 23:59:59",'
                '"texto_busqueda_semantica":"conferencia"}'
            )
            parser = TemporalParser(settings)
            result = parser.extraer("Que dijo en la conferencia del lunes pasado?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio is not None
        assert result.filter_out.fecha_fin is not None

    def test_ultima_semana(self):
        """'Que paso la ultima semana?' debe activar filtro con rango."""
        settings = Settings(gemini_api_key="fake-key")

        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-08-31 00:00:00",'
                '"fecha_fin":"2026-09-07 23:59:59",'
                '"texto_busqueda_semantica":"acontecimientos ultima semana"}'
            )
            parser = TemporalParser(settings)
            result = parser.extraer("Que paso la ultima semana?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio is not None
        assert result.filter_out.fecha_fin is not None
