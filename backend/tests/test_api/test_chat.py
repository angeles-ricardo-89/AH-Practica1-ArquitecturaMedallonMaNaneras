from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lakehouse.main import app
from lakehouse.schemas.chat import SourceChunk
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.token_estimator import estimate_tokens

client = TestClient(app)


@pytest.fixture
def mock_llamacpp():
    response_data = {
        "choices": [{"message": {"content": "Respuesta basada en fuentes."}}],
        "usage": {"prompt_tokens": 150, "completion_tokens": 50},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data

    with (
        patch("lakehouse.api.routers.chat.httpx.Client") as mock_cls,
        patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls,
        patch("lakehouse.api.routers.chat._embed_query") as mock_embed,
        patch("lakehouse.api.routers.chat.search_gold_corpus_from_vector") as mock_search,
    ):
        mock_instance = MagicMock()
        mock_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.post.return_value = mock_resp
        mock_parser = MagicMock()
        mock_parser_cls.return_value = mock_parser
        mock_parser.extraer.return_value = MagicMock(
            filter_out=MagicMock(
                requiere_filtro_tiempo=False,
                fecha_inicio=None,
                fecha_fin=None,
                texto_busqueda_semantica="test query",
            ),
            fallback_ocurrido=False,
        )
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_search.return_value = []
        yield mock_cls, mock_search, mock_embed, mock_parser_cls


class TestChatEndpoint:
    def test_chat_returns_200(self, mock_llamacpp) -> None:
        resp = client.post("/chat/", json={"query": "¿Cómo va la reforma?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"] == "Respuesta basada en fuentes."

    def test_chat_returns_sources(self, mock_llamacpp) -> None:
        resp = client.post(
            "/chat/",
            json={"query": "reforma energética", "top_k": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_chat_returns_token_usage(self, mock_llamacpp) -> None:
        resp = client.post(
            "/chat/",
            json={"query": "¿Qué pasó con la salud?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token_usage" in data
        assert isinstance(data["token_usage"], dict)

    def test_chat_rejects_empty_query(self) -> None:
        resp = client.post("/chat/", json={"query": ""})
        assert resp.status_code == 422

    def test_chat_handles_llamacpp_unavailable(self) -> None:
        with (
            patch("lakehouse.api.routers.chat.httpx.Client") as mock_cls,
            patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls,
            patch("lakehouse.api.routers.chat._embed_query") as mock_embed,
            patch("lakehouse.api.routers.chat.search_gold_corpus_from_vector") as mock_search,
        ):
            mock_instance = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_instance
            mock_instance.post.side_effect = Exception("Connection refused")
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=False,
                    texto_busqueda_semantica="test query",
                ),
                fallback_ocurrido=False,
            )
            mock_embed.return_value = [0.1, 0.2, 0.3]
            mock_search.return_value = []
            resp = client.post("/chat/", json={"query": "test query"})
            assert resp.status_code == 503

    def test_chat_handles_embedding_failure(self, mock_llamacpp) -> None:
        _, _, mock_embed, _ = mock_llamacpp
        mock_embed.side_effect = ConnectionError("embedding failed")
        resp = client.post("/chat/", json={"query": "test query"})
        assert resp.status_code == 503

    def test_chat_with_conversation_id(self, mock_llamacpp) -> None:
        resp = client.post(
            "/chat/",
            json={
                "query": "Cuéntame más",
                "conversation_id": "conv_001",
            },
        )
        assert resp.status_code == 200

    def test_chat_with_temporal_filter(self, mock_llamacpp):
        _, mock_search, _, mock_parser_cls = mock_llamacpp
        mock_parser_cls.return_value.extraer.return_value = MagicMock(
            filter_out=MagicMock(
                requiere_filtro_tiempo=True,
                fecha_inicio="2025-07-15",
                fecha_fin="2025-07-15",
                texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
            ),
            fallback_ocurrido=False,
        )
        with patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            mock_date_search.return_value = []
            resp = client.post("/chat/", json={"query": "Que dijo Sheinbaum ayer sobre el T-MEC"})
            assert resp.status_code == 200
            mock_date_search.assert_called_once()
            mock_search.assert_not_called()

    def test_chat_without_temporal_intent(self, mock_llamacpp):
        _, mock_search, _, _ = mock_llamacpp
        with patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            resp = client.post("/chat/", json={"query": "postura sobre energia nuclear"})
            assert resp.status_code == 200
            mock_search.assert_called_once()
            mock_date_search.assert_not_called()

    def test_chat_parser_fallback_injects_nota(self, mock_llamacpp):
        mock_cls, _, _, mock_parser_cls = mock_llamacpp
        mock_parser_cls.return_value.extraer.return_value = MagicMock(
            filter_out=MagicMock(
                requiere_filtro_tiempo=False,
                texto_busqueda_semantica="query ambigua",
            ),
            fallback_ocurrido=True,
        )
        resp = client.post("/chat/", json={"query": "query ambigua con fecha confusa"})
        assert resp.status_code == 200
        mock_instance = mock_cls.return_value.__enter__.return_value
        payload = mock_instance.post.call_args[1]["json"]
        context = payload["messages"][1]["content"]
        assert "No se pudo determinar" in context

    def test_chat_with_empty_date_range_responds_no_info(self, mock_llamacpp):
        mock_cls, mock_search, _, mock_parser_cls = mock_llamacpp
        mock_parser_cls.return_value.extraer.return_value = MagicMock(
            filter_out=MagicMock(
                requiere_filtro_tiempo=True,
                fecha_inicio="2099-01-01",
                fecha_fin="2099-12-31",
                texto_busqueda_semantica="reforma energetica",
            ),
            fallback_ocurrido=False,
        )
        with patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            mock_date_search.return_value = []
            resp = client.post("/chat/", json={"query": "reforma energetica de 2099"})
            assert resp.status_code == 200
            assert resp.json()["sources"] == []
            mock_date_search.assert_called_once()
            mock_search.assert_not_called()
            mock_instance = mock_cls.return_value.__enter__.return_value
            payload = mock_instance.post.call_args[1]["json"]
            context = payload["messages"][1]["content"]
            assert "No se encontraron resultados para el rango de fechas solicitado" in context


class TestChatSourceDetails:
    def test_source_includes_required_fields(self) -> None:
        source = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El día de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
            pregunta_activa="¿Cómo va la reforma?",
        )
        assert source.conference_date == "2024-10-01"
        assert source.participant == "PRESIDENTA"
        assert source.chunk_text == "El día de hoy..."
        assert source.similarity == 0.95
        assert source.conference_url == "https://example.com"
        assert source.pregunta_activa == "¿Cómo va la reforma?"


class TestTokenEstimator:
    def test_estimate_tokens(self) -> None:
        assert estimate_tokens("hello world") == 2
        assert estimate_tokens("") == 1
        assert estimate_tokens("a" * 100) == 25

    def test_estimate_tokens_never_zero(self) -> None:
        assert estimate_tokens("") == 1
        assert estimate_tokens("x") == 1


class TestContextBuilder:
    def test_build_returns_context_and_usage(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        context, usage = builder.build(
            query="test query",
            system_prompt="Eres un asistente.",
            sources=[],
        )
        assert "test query" in context
        assert "Eres un asistente." in context
        assert usage.prompt > 0
        assert usage.completion == 0

    def test_system_prompt_and_query_never_truncated(self) -> None:
        builder = ContextBuilder(max_context_tokens=50)
        long_history = [
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 200},
        ]
        context, _usage = builder.build(
            query="short query",
            system_prompt="short sys",
            sources=[],
            history=long_history,
        )
        assert "short query" in context
        assert "short sys" in context

    def test_fifo_truncation_when_context_exceeds(self) -> None:
        builder = ContextBuilder(max_context_tokens=100)
        history = [
            {"role": "user", "content": "message " * 50},
            {"role": "assistant", "content": "reply " * 50},
            {"role": "user", "content": "second message " * 50},
            {"role": "assistant", "content": "second reply " * 50},
        ]
        context, _usage = builder.build(
            query="final query",
            system_prompt="sys",
            sources=[],
            history=history,
        )
        assert "final query" in context
        assert "sys" in context

    def test_sources_included_in_context(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
        )
        assert "PRESIDENTA" in context
        assert "Contenido de la fuente." in context
        assert "2024-10-01" in context

    def test_nota_fallback_included_in_context(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=True,
        )
        assert "No se pudo determinar" in context
        assert "filtro temporal" in context
        assert "PRESIDENTA" in context
        assert context.index("No se pudo determinar") < context.index("Fuentes:")

    def test_no_fallback_nota_when_not_requested(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=False,
        )
        assert "No se pudo determinar" not in context

    def test_empty_sources_handled_gracefully(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        context, _usage = builder.build(
            query="test query",
            system_prompt="sys",
            sources=[],
        )
        assert "test query" in context
        assert "sys" in context

    def test_sin_resultados_rango_injected(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=[],
            sin_resultados_rango=True,
        )
        assert "No se encontraron resultados para el rango de fechas solicitado" in context

    def test_no_sin_resultados_rango_by_default(self) -> None:
        builder = ContextBuilder(max_context_tokens=8192)
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=[],
        )
        assert "No se encontraron resultados" not in context
