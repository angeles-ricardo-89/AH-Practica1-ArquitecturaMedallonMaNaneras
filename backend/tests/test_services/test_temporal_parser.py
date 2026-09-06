from unittest.mock import patch

import httpx
import pytest

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser

PATCH_CHAT = "lakehouse.services.temporal_parser.chat_json"


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def parser(settings):
    return TemporalParser(settings)


@pytest.fixture
def mock_chat():
    with patch(PATCH_CHAT) as mock:
        yield mock


def _ok(content: str) -> str:
    return content


class TestTemporalParserExtraer:
    @patch(PATCH_CHAT)
    def test_extrae_fecha_exacta(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            '{"requiere_filtro_tiempo":true,"fecha_inicio":"2025-07-15 00:00:00",'
            '"fecha_fin":"2025-07-15 23:59:59",'
            '"texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC"}'
        )

        result = parser.extraer(
            "Que dijo Sheinbaum sobre el T-MEC en la conferencia del 15 de julio 2025"
        )

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"
        assert "15 de julio" not in result.filter_out.texto_busqueda_semantica

    @patch(PATCH_CHAT)
    def test_sin_intencion_temporal(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,'
            '"texto_busqueda_semantica":"postura sobre energia nuclear"}'
        )

        result = parser.extraer("postura sobre energia nuclear")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.fecha_inicio is None
        assert result.filter_out.fecha_fin is None

    @patch(PATCH_CHAT)
    def test_llm_responde_con_markdown_json_block(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            '```json\n{"requiere_filtro_tiempo":false,"fecha_inicio":null,'
            '"fecha_fin":null,"texto_busqueda_semantica":"que es la reforma"}\n```\n'
            "Espero que te sirva."
        )

        result = parser.extraer("que es la reforma")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False

    @patch(PATCH_CHAT)
    def test_llm_responde_invalido_usa_fallback(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok("no soy un JSON valido en ningun intento, solo texto")

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch(PATCH_CHAT)
    def test_prompt_incluye_datetime_actual(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,'
            '"texto_busqueda_semantica":"test"}'
        )

        parser.extraer("test")

        call_args = mock_chat_json.call_args
        messages = call_args.args[1]
        system_content = messages[0]["content"]
        assert "fecha/hora actual" in system_content

    @patch(PATCH_CHAT)
    def test_llm_responde_con_json_embebido_en_texto(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            'Aqui esta tu respuesta: {"requiere_filtro_tiempo":true,'
            '"fecha_inicio":"2025-01-10 00:00:00","fecha_fin":"2025-01-10 23:59:59",'
            '"texto_busqueda_semantica":"reforma educativa"}'
        )

        result = parser.extraer("reforma educativa en enero")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-01-10 00:00:00"
        assert result.filter_out.texto_busqueda_semantica == "reforma educativa"

    @patch(PATCH_CHAT)
    def test_json_valido_pero_incoherente_reintenta_y_falla(self, mock_chat_json, parser):
        mock_chat_json.return_value = _ok(
            '{"requiere_filtro_tiempo":true,"fecha_inicio":null,"fecha_fin":null,'
            '"texto_busqueda_semantica":"x"}'
        )

        result = parser.extraer("algo con fecha")

        assert result.fallback_ocurrido is True
        assert mock_chat_json.call_count == 3

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch(PATCH_CHAT)
    def test_error_http_reintenta_y_falla(self, mock_chat_json, mock_sleep, parser):
        mock_chat_json.side_effect = httpx.HTTPError("boom")

        result = parser.extraer("cualquier consulta")

        assert result.fallback_ocurrido is True
        assert mock_chat_json.call_count == 3

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch(PATCH_CHAT)
    def test_llm_responde_con_llaves_invalidas_usa_fallback(
        self, mock_chat_json, mock_sleep, parser
    ):
        mock_chat_json.return_value = _ok('respuesta {"incompleto, no es json valido}')

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch(PATCH_CHAT)
    def test_reintenta_exitoso_tras_error(self, mock_chat_json, mock_sleep, parser):
        mock_chat_json.side_effect = [
            httpx.HTTPError("boom"),
            _ok(
                '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,'
                '"texto_busqueda_semantica":"recuperado"}'
            ),
        ]

        result = parser.extraer("recuperado")

        assert result.fallback_ocurrido is False
        assert result.filter_out.texto_busqueda_semantica == "recuperado"
        mock_sleep.assert_called_once()
