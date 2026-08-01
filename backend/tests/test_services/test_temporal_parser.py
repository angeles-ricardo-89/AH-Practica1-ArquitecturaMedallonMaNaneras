from unittest.mock import MagicMock, patch

import httpx
import pytest

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def parser(settings):
    return TemporalParser(settings)


class TestTemporalParserExtraer:
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_extrae_fecha_exacta(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"requiere_filtro_tiempo":true,"fecha_inicio":"2025-07-15 00:00:00","fecha_fin":"2025-07-15 23:59:59","texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC"}'
                    }
                }
            ]
        }

        result = parser.extraer(
            "Que dijo Sheinbaum sobre el T-MEC en la conferencia del 15 de julio 2025"
        )

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"
        assert "15 de julio" not in result.filter_out.texto_busqueda_semantica

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_sin_intencion_temporal(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"postura sobre energia nuclear"}'
                    }
                }
            ]
        }

        result = parser.extraer("postura sobre energia nuclear")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.fecha_inicio is None
        assert result.filter_out.fecha_fin is None

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_con_markdown_json_block(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"que es la reforma"}\n```\nEspero que te sirva.'
                    }
                }
            ]
        }

        result = parser.extraer("que es la reforma")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_invalido_usa_fallback(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {"message": {"content": "no soy un JSON valido en ningun intento, solo texto"}}
            ]
        }

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_prompt_incluye_datetime_actual(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"test"}'
                    }
                }
            ]
        }

        parser.extraer("test")

        call_args = mock_client.post.call_args
        messages = call_args[1]["json"]["messages"]
        system_content = messages[0]["content"]
        assert "fecha/hora actual" in system_content

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_con_json_embebido_en_texto(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": 'Aqui esta tu respuesta: {"requiere_filtro_tiempo":true,"fecha_inicio":"2025-01-10 00:00:00","fecha_fin":"2025-01-10 23:59:59","texto_busqueda_semantica":"reforma educativa"}'
                    }
                }
            ]
        }

        result = parser.extraer("reforma educativa en enero")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-01-10 00:00:00"
        assert result.filter_out.texto_busqueda_semantica == "reforma educativa"

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_json_valido_pero_incoherente_reintenta_y_falla(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"requiere_filtro_tiempo":true,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"x"}'
                    }
                }
            ]
        }

        result = parser.extraer("algo con fecha")

        assert result.fallback_ocurrido is True
        assert mock_client.post.call_count == 3

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_error_http_reintenta_y_falla(self, mock_client_class, mock_sleep, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPError("boom")

        result = parser.extraer("cualquier consulta")

        assert result.fallback_ocurrido is True
        assert mock_client.post.call_count == 3

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_con_llaves_invalidas_usa_fallback(
        self, mock_client_class, mock_sleep, parser
    ):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": 'respuesta {"incompleto, no es json valido}'}}]
        }

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch("lakehouse.services.temporal_parser.time.sleep")
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_reintenta_exitoso_tras_error(self, mock_client_class, mock_sleep, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = [
            httpx.HTTPError("boom"),
            MagicMock(
                status_code=200,
                json=lambda: {
                    "choices": [
                        {
                            "message": {
                                "content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"recuperado"}'
                            }
                        }
                    ]
                },
            ),
        ]

        result = parser.extraer("recuperado")

        assert result.fallback_ocurrido is False
        assert result.filter_out.texto_busqueda_semantica == "recuperado"
        mock_sleep.assert_called_once()
