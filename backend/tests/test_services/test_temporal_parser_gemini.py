from __future__ import annotations

from unittest.mock import patch

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser

PATCH_CHAT = "lakehouse.services.temporal_parser.chat_json"


class TestParserGeminiJsonShape:
    """Verifica que el parser maneja formatos de respuesta especificos de Gemini:
    campo thought de thinking models, JSON multilinea con sangria,
    candidates vacios (safety block) y finish_reason SAFETY."""

    def test_respuesta_con_pensamiento_thinking_model(self):
        """Gemini thinking modelos incluyen campo 'thought' en el mismo JSON.
        Pydantic ignora campos desconocidos, asi que el parser lo acepta."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"thought":"Analizando la consulta temporal...",'
                '"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-01-01 00:00:00",'
                '"fecha_fin":"2026-01-01 23:59:59",'
                '"texto_busqueda_semantica":"conferencia inauguracion"}'
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo en la conferencia del primero de enero?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2026-01-01 00:00:00"
        assert result.fallback_ocurrido is False

    def test_formato_gemini_multilinea(self):
        """Gemini formatea el JSON con saltos de linea y sangria."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{\n'
                '  "requiere_filtro_tiempo": true,\n'
                '  "fecha_inicio": "2026-03-15 00:00:00",\n'
                '  "fecha_fin": "2026-03-15 23:59:59",\n'
                '  "texto_busqueda_semantica": "discurso Sheinbaum"\n'
                '}'
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo Sheinbaum el 15 de marzo?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2026-03-15 00:00:00"
        assert result.fallback_ocurrido is False

    def test_candidates_vacios_cae_fallback(self):
        """Gemini puede devolver candidates:[] (safety block), que no contiene JSON."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = '{"candidates":[]}'
            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo Sheinbaum ayer?")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "Que dijo Sheinbaum ayer?"

    def test_safety_finish_reason_cae_fallback(self):
        """Gemini bloquea la respuesta por safety y devuelve finish_reason SAFETY."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"candidates":[{"finishReason":"SAFETY","safetyRatings":[]}]}'
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("Que paso con el conflicto armado?")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "Que paso con el conflicto armado?"
