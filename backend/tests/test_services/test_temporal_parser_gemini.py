from unittest.mock import patch

import pytest

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser

PATCH_CHAT = "lakehouse.services.temporal_parser.chat_json"

_RESPONSE = (
    '{"requiere_filtro_tiempo":true,'
    '"fecha_inicio":"2026-03-15 00:00:00",'
    '"fecha_fin":"2026-03-15 23:59:59",'
    '"texto_busqueda_semantica":"discurso Sheinbaum"}'
)


@pytest.fixture
def settings():
    return Settings(gemini_api_key="test-key")


@pytest.fixture
def parser(settings):
    return TemporalParser(settings)


@patch(PATCH_CHAT)
def test_parser_funciona_con_configuracion_produccion(mock_chat, parser):
    mock_chat.return_value = _RESPONSE

    result = parser.extraer("Que dijo Sheinbaum el 15 de marzo?")

    assert result.fallback_ocurrido is False
    assert result.filter_out.requiere_filtro_tiempo is True
    assert result.filter_out.fecha_inicio == "2026-03-15 00:00:00"
    assert result.filter_out.fecha_fin == "2026-03-15 23:59:59"
    assert result.filter_out.texto_busqueda_semantica == "discurso Sheinbaum"
