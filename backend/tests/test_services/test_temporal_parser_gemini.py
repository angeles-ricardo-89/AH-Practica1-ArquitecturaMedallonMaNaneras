from __future__ import annotations

from unittest.mock import patch

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser

PATCH_CHAT = "lakehouse.services.temporal_parser.chat_json"


class TestParserGeminiJsonShape:
    """Verifica que el parser maneja formatos de respuesta especificos de Gemini:
    code fences markdown, texto embebido, pensamiento del modelo thinking,
    y queries con caracteres unicode."""

    def test_code_fence_json_limpa_wrapper(self):
        """Gemini devuelve JSON envuelto en ```json ... ```."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '```json\n{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2025-07-15 00:00:00",'
                '"fecha_fin":"2025-07-15 23:59:59",'
                '"texto_busqueda_semantica":"Sheinbaum discurso"}\n```'
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo Sheinbaum el 15 de julio de 2025?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.fallback_ocurrido is False

    def test_code_fence_con_texto_adicional(self):
        """Gemini agrega texto antes/despues del code fence."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                "Claro, aqui esta el analisis:\n"
                '```json\n{"requiere_filtro_tiempo":false,"fecha_inicio":null,'
                '"fecha_fin":null,"texto_busqueda_semantica":"energia nuclear"}\n```\n'
                "Espero que te sirva."
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("postura sobre energia nuclear")

        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.fallback_ocurrido is False

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

    def test_json_embebido_en_texto_largo(self):
        """Gemini a veces responde con explicaciones y el JSON en medio."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                "Basado en tu pregunta, el filtro temporal es: "
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-08-31 00:00:00",'
                '"fecha_fin":"2026-08-31 23:59:59",'
                '"texto_busqueda_semantica":"conferencia lunes"} '
                "y eso es todo."
            )
            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo en la conferencia del lunes pasado?")

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2026-08-31 00:00:00"
        assert result.fallback_ocurrido is False

    def test_query_unicode_acentos(self):
        """Gemini maneja correctamente consultas con caracteres unicode/accentos."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,'
                '"fecha_inicio":"2026-09-01 00:00:00",'
                '"fecha_fin":"2026-09-01 23:59:59",'
                '"texto_busqueda_semantica":"conferencia prensa"}'
            )
            parser = TemporalParser(Settings())
            result = parser.extraer(
                "Que dijo Sheinbaum en la conferencia de prensa el martes?"
            )

        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.fallback_ocurrido is False

    def test_respuesta_vacia_cae_fallback(self):
        """Gemini puede devolver string vacio en bloques de seguridad."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = ""

            parser = TemporalParser(Settings())
            result = parser.extraer("Que dijo Sheinbaum ayer?")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "Que dijo Sheinbaum ayer?"

    def test_respuesta_solo_texto_cae_fallback(self):
        """Gemini devuelve texto plano sin JSON (bloqueo de seguridad o error)."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                "Lo siento, no puedo procesar esta consulta en este momento."
            )

            parser = TemporalParser(Settings())
            result = parser.extraer("Que paso con el conflicto?")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "Que paso con el conflicto?"

    def test_json_incoherente_reintenta_y_falla(self):
        """JSON parseable pero con campos incoherentes (requiere_filtro_tiempo=true pero sin fechas)."""
        with patch(PATCH_CHAT) as mock_chat:
            mock_chat.return_value = (
                '{"requiere_filtro_tiempo":true,"fecha_inicio":null,"fecha_fin":null,'
                '"texto_busqueda_semantica":"x"}'
            )

            parser = TemporalParser(Settings())
            result = parser.extraer("algo con fecha")

        assert result.fallback_ocurrido is True
        assert mock_chat.call_count == 3

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
