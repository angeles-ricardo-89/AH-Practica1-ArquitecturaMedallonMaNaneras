from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest

from lakehouse.config import Settings
from lakehouse.schemas.chat import SourceChunk
from lakehouse.services.rag_search import (
    _call_ollama_embed,
    _embed_query,
    _get_pgvector_connection_string,
    search_gold_corpus,
    search_sources,
)


class TestGetPgvectorConnectionString:
    def test_formats_url_from_settings(self):
        settings = Settings()
        url = _get_pgvector_connection_string(settings)
        assert url == (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )


class TestCallOllamaEmbed:
    @patch("lakehouse.services.rag_search.httpx.Client")
    def test_returns_embedding(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        mock_client.post.return_value = mock_response

        result = _call_ollama_embed(
            "http://localhost:11434/api/embed",
            "nomic-embed-text",
            "texto",
        )

        assert result == [0.1, 0.2, 0.3]
        mock_client.post.assert_called_once()

    @patch("lakehouse.services.rag_search.httpx.Client")
    def test_raises_on_bad_status(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            _call_ollama_embed("http://localhost:11434/api/embed", "m", "t")

    @patch("lakehouse.services.rag_search.httpx.Client")
    def test_raises_on_empty_embeddings(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": []}
        mock_client.post.return_value = mock_response

        with pytest.raises(ValueError, match="empty embeddings"):
            _call_ollama_embed("http://localhost:11434/api/embed", "m", "t")


class TestEmbedQuery:
    @patch("lakehouse.services.rag_search._call_ollama_embed")
    def test_returns_embedding(self, mock_embed: MagicMock) -> None:
        mock_embed.return_value = [0.5] * 768

        result = _embed_query("query", "http://localhost:11434", "model")

        assert result == [0.5] * 768
        mock_embed.assert_called_once_with(
            "http://localhost:11434/api/embed",
            "model",
            "query",
        )

    @patch("lakehouse.services.rag_search._call_ollama_embed")
    def test_reraises_value_error(self, mock_embed: MagicMock) -> None:
        mock_embed.side_effect = ValueError("empty")

        with pytest.raises(ValueError, match="empty"):
            _embed_query("query", "http://localhost:11434", "model")

    @patch("lakehouse.services.rag_search.time.sleep")
    @patch("lakehouse.services.rag_search._call_ollama_embed")
    def test_retries_then_succeeds(
        self,
        mock_embed: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_embed.side_effect = [
            httpx.ConnectError("down"),
            httpx.ConnectError("down"),
            [0.5] * 768,
        ]

        result = _embed_query(
            "query",
            "http://localhost:11434",
            "model",
            max_retries=3,
            base_delay=2.0,
        )

        assert result == [0.5] * 768
        assert mock_embed.call_count == 3
        mock_sleep.assert_called()

    @patch("lakehouse.services.rag_search.time.sleep")
    @patch("lakehouse.services.rag_search._call_ollama_embed")
    def test_raises_after_max_retries(
        self,
        mock_embed: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_embed.side_effect = httpx.ConnectError("always down")

        with pytest.raises(ConnectionError, match="failed after 3 retries"):
            _embed_query("query", "http://localhost:11434", "model", max_retries=3)

        assert mock_embed.call_count == 3
        assert mock_sleep.call_count == 2


class TestSearchGoldCorpus:
    @patch("lakehouse.services.rag_search.psycopg.connect")
    @patch("lakehouse.services.rag_search._embed_query")
    def test_returns_mapped_rows(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        mock_embed.return_value = [0.1] * 768
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2024-10-01", "c1", "PARTICIPANTE", "texto", "https://u", "pregunta", 0.95),
        ]

        results = search_gold_corpus("reforma", top_k=5, settings=Settings())

        assert len(results) == 1
        assert results[0]["conference_id"] == "c1"
        assert results[0]["participant"] == "PARTICIPANTE"
        assert results[0]["pregunta_activa"] == "pregunta"
        assert results[0]["similarity"] == 0.95
        sql, params = mock_cursor.execute.call_args.args
        assert "ORDER BY embedding <=> %s::vector" in sql
        assert params[2] == 5

    @patch("lakehouse.services.rag_search.logger")
    @patch("lakehouse.services.rag_search._embed_query")
    def test_raises_when_embedding_fails(
        self,
        mock_embed: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_embed.side_effect = ConnectionError("embedding failed")

        with pytest.raises(RuntimeError, match="embedding generation failed"):
            search_gold_corpus("reforma", top_k=5, settings=Settings())

    @patch("lakehouse.services.rag_search.logger")
    @patch("lakehouse.services.rag_search.psycopg.connect")
    @patch("lakehouse.services.rag_search._embed_query")
    def test_raises_when_db_query_fails(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_embed.return_value = [0.1] * 768
        mock_connect.side_effect = psycopg.OperationalError("db down")

        with pytest.raises(RuntimeError, match="database query failed"):
            search_gold_corpus("reforma", top_k=5, settings=Settings())

    @patch("lakehouse.services.rag_search.logger")
    @patch("lakehouse.services.rag_search.psycopg.connect")
    @patch("lakehouse.services.rag_search._embed_query")
    def test_query_filters_short_chunks(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_embed.return_value = [0.1] * 768
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        search_gold_corpus("reforma", top_k=5, settings=Settings())

        sql, _params = mock_cursor.execute.call_args.args
        assert "LENGTH(chunk_text) >= 50" in sql


class TestSearchSources:
    @patch("lakehouse.services.rag_search.search_gold_corpus")
    def test_builds_source_chunks(self, mock_search: MagicMock) -> None:
        mock_search.return_value = [
            {
                "conference_date": "2024-10-01",
                "conference_id": "c1",
                "participant": "P",
                "chunk_text": "texto",
                "url": "https://u",
                "pregunta_activa": "q",
                "similarity": 0.9,
            }
        ]

        chunks = search_sources("reforma", top_k=5)

        assert isinstance(chunks[0], SourceChunk)
        assert chunks[0].conference_id == "c1"
        assert chunks[0].conference_url == "https://u"
        assert chunks[0].pregunta_activa == "q"
        mock_search.assert_called_once_with("reforma", 5)
