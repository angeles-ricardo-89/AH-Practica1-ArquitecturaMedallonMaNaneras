from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest

from lakehouse.pipeline.enrichment import (
    _embed_one,
    _store_gold,
    build_embedding_payload,
    build_embedding_text,
    build_window_key,
    build_window_text,
    build_windows,
    drop_gold_tables,
    embed_text,
    enrich_interventions,
    ensure_gold_tables,
    get_pgvector_connection_string,
)
from lakehouse.pipeline.interrupt import interrupt_state
from lakehouse.schemas.gold import WindowRecord
from lakehouse.schemas.silver import InterventionRecord
from lakehouse.services.token_estimator import estimate_tokens


@pytest.fixture
def sample_window() -> WindowRecord:
    return WindowRecord(
        chunk_key="conf123_w000_abc123",
        conference_id="conf123",
        conference_date="2024-10-01",
        participant="PRESIDENTA CLAUDIA SHEINBAUM PARDO",
        text="Buenos días. Hoy vamos a informar sobre los avances del país.",
        pregunta_activa="¿Cómo va la reforma energética?",
        url="https://example.com/conf-2024-10-01",
        window_index=0,
    )


@pytest.fixture
def sample_window_no_question() -> WindowRecord:
    return WindowRecord(
        chunk_key="conf456_w001_def456",
        conference_id="conf456",
        conference_date="2025-01-15",
        participant="SECRETARIO DE GOBERNACIÓN",
        text="Informamos que los programas sociales continúan.",
        pregunta_activa="",
        url="https://example.com/conf-2024-10-01",
        window_index=1,
    )


class TestBuildEmbeddingPayload:
    def test_format_matches_prd(self, sample_window: WindowRecord):
        payload = build_embedding_payload(record=sample_window, conference_date="2024-10-01")
        expected = (
            "Contexto: Conferencia del 2024-10-01\n"
            "Participante: PRESIDENTA CLAUDIA SHEINBAUM PARDO\n"
            "Pregunta activa: ¿Cómo va la reforma energética?\n"
            "Respuesta: Buenos días. Hoy vamos a informar sobre los avances del país."
        )
        assert payload == expected

    def test_no_pregunta_activa(self, sample_window_no_question: WindowRecord):
        payload = build_embedding_payload(
            record=sample_window_no_question,
            conference_date="2025-01-15",
        )
        expected = (
            "Contexto: Conferencia del 2025-01-15\n"
            "Participante: SECRETARIO DE GOBERNACIÓN\n"
            "Pregunta activa: \n"
            "Respuesta: Informamos que los programas sociales continúan."
        )
        assert payload == expected

    def test_no_technical_ids_or_hashes(self, sample_window: WindowRecord):
        payload = build_embedding_payload(record=sample_window, conference_date="2024-10-01")
        assert "abc123" not in payload
        assert "conf123" not in payload
        assert "intervention_key" not in payload.lower()
        assert "chunk_index" not in payload.lower()
        assert "chunk_key" not in payload.lower()
        assert "window_index" not in payload.lower()

    def test_special_characters(self):
        record = WindowRecord(
            chunk_key="spec_w000_chars",
            conference_id="spec",
            conference_date="2025-03-01",
            participant="LIC. MARÍA JOSÉ PÉREZ",
            text="Costo: $1,234.56 — 100% real. ¡Vamos! ¿De acuerdo?",
            pregunta_activa="¿Costo total? $500 pesos",
            url="https://example.com",
            window_index=0,
        )
        payload = build_embedding_payload(record=record, conference_date="2025-03-01")
        assert "$1,234.56" in payload
        assert "100%" in payload
        assert "¿Costo total?" in payload
        assert "MARÍA JOSÉ PÉREZ" in payload


class TestEmbedText:
    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_calls_ollama_with_correct_params(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1] * 768]}
        mock_client.post.return_value = mock_response

        embedding = embed_text(
            text="test payload",
            base_url="http://localhost:11434",
            model="nomic-embed-text",
        )

        assert len(embedding) == 768
        assert embedding[0] == 0.1
        expected_url = "http://localhost:11434/api/embed"
        mock_client.post.assert_called_once_with(
            expected_url,
            json={"model": "nomic-embed-text", "input": "test payload"},
            timeout=30,
        )

    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_retries_on_connection_error(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = [
            httpx.ConnectError("connection refused"),
            httpx.ConnectError("connection refused"),
            MagicMock(
                status_code=200,
                json=lambda: {"embeddings": [[0.2] * 768]},
            ),
        ]

        embedding = embed_text(
            text="test",
            base_url="http://localhost:11434",
            model="nomic-embed-text",
        )

        assert len(embedding) == 768
        assert mock_client.post.call_count == 3

    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_retries_on_bad_status(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        bad_resp = MagicMock()
        bad_resp.status_code = 500
        mock_client.post.side_effect = [
            bad_resp,
            bad_resp,
            MagicMock(
                status_code=200,
                json=lambda: {"embeddings": [[0.3] * 768]},
            ),
        ]

        embedding = embed_text(
            text="test",
            base_url="http://localhost:11434",
            model="nomic-embed-text",
        )

        assert len(embedding) == 768
        assert mock_client.post.call_count == 3

    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_raises_after_max_retries(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.ConnectError("always down")

        with pytest.raises(ConnectionError, match="Ollama embedding failed after 3 retries"):
            embed_text(
                text="test",
                base_url="http://localhost:11434",
                model="nomic-embed-text",
            )

        assert mock_client.post.call_count == 3

    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_invalid_embedding_dimension_format(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"embeddings": [[0.1, 0.2, 0.3]]},
        )

        embedding = embed_text(
            text="test",
            base_url="http://localhost:11434",
            model="nomic-embed-text",
        )

        assert len(embedding) == 3

    @patch("lakehouse.pipeline.enrichment.httpx.Client")
    def test_raises_on_empty_embeddings_response(self, mock_client_class: MagicMock):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"embeddings": []},
        )

        with pytest.raises(ValueError, match="Ollama returned empty embeddings"):
            embed_text(
                text="test",
                base_url="http://localhost:11434",
                model="nomic-embed-text",
            )


class TestPgvectorConnection:
    @patch("lakehouse.pipeline.enrichment.get_pgvector_connection_string")
    def test_connection_string_format(self, mock_conn_str: MagicMock):
        mock_conn_str.return_value = "postgresql://user:pass@host:5433/db"
        result = get_pgvector_connection_string(
            host="myhost",
            port=5433,
            db="mydb",
            user="myuser",
            password="mypass",
        )
        assert result == "postgresql://myuser:mypass@myhost:5433/mydb"


class TestEnsureGoldTables:
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_creates_schema_table_and_indexes(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        ensure_gold_tables(
            conn_str="postgresql://user:pass@localhost:5433/mydb",
        )

        calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
        executed_sql = " ".join(calls)

        assert "CREATE SCHEMA IF NOT EXISTS gold" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS gold.rag_corpus" in executed_sql
        assert "vector(768)" in executed_sql
        assert "chunk_key VARCHAR PRIMARY KEY" in executed_sql
        assert "conference_id" in executed_sql
        assert "conference_date" in executed_sql
        assert "participant" in executed_sql
        assert "chunk_text" in executed_sql
        assert "payload" in executed_sql
        assert "url" in executed_sql
        assert "pregunta_activa" in executed_sql
        assert "embedding" in executed_sql
        assert "ingested_at" in executed_sql
        assert "idx_rag_corpus_conference_date" in executed_sql
        assert "idx_rag_corpus_participant" in executed_sql
        assert "idx_rag_corpus_embedding_hnsw" in executed_sql
        assert "hnsw" in executed_sql
        assert "vector_cosine_ops" in executed_sql


class TestDropGoldTables:
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_drops_rag_corpus(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        drop_gold_tables("postgresql://u:p@h:5433/d")

        calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert "DROP TABLE IF EXISTS gold.rag_corpus" in calls


class TestEnrichInterventions:
    def _window(self, i: int, text: str = "Texto de la ventana.") -> WindowRecord:
        return WindowRecord(
            chunk_key=f"conf1_w{i:03d}_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text=text,
            url="https://example.com",
            window_index=i,
        )

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_uses_record_conference_date_when_param_none(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        result = enrich_interventions(
            windows=[self._window(0)],
            conference_date=None,
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        insert_call = next(
            c
            for c in mock_cursor.execute.call_args_list
            if "INSERT INTO gold.rag_corpus" in c[0][0]
        )
        params = insert_call[0][1]
        assert params[2] == "2025-03-01"
        assert "Contexto: Conferencia del 2025-03-01" in params[5]

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_param_overrides_record_conference_date(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        result = enrich_interventions(
            windows=[self._window(0)],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        insert_call = next(
            c
            for c in mock_cursor.execute.call_args_list
            if "INSERT INTO gold.rag_corpus" in c[0][0]
        )
        params = insert_call[0][1]
        assert params[2] == "2024-10-01"
        assert "Contexto: Conferencia del 2024-10-01" in params[5]

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_record_without_date_is_failed(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        record = self._window(0)
        record.conference_date = ""

        result = enrich_interventions(
            windows=[record],
            conference_date=None,
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 0
        assert result["failed"] == 1
        mock_embed.assert_not_called()

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_unique_violation_logs_and_counts_embedded(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        class MockExecute:
            def __call__(self, sql: str, params: tuple | None = None) -> MagicMock:
                raise psycopg.errors.UniqueViolation("duplicate key")

        mock_cursor.execute = MockExecute()

        result = enrich_interventions(
            windows=[self._window(0)],
            conference_date=None,
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        assert result["failed"] == 0

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_on_conflict_updates_metadata(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        enrich_interventions(
            windows=[self._window(0)],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        insert_call = next(
            c
            for c in mock_cursor.execute.call_args_list
            if "INSERT INTO gold.rag_corpus" in c[0][0]
        )
        sql = insert_call[0][0]
        assert "ON CONFLICT (chunk_key) DO UPDATE" in sql
        assert "conference_date" in sql
        assert "url" in sql
        assert "payload" in sql
        assert "pregunta_activa" in sql

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_single_intervention_stored_correctly(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        record = self._window(0, text="P: Q?\nPRESIDENTA: R.")

        result = enrich_interventions(
            windows=[record],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        assert result["failed"] == 0

        execute_args = mock_cursor.execute.call_args_list
        insert_call = None
        for call in execute_args:
            sql = call[0][0]
            if "INSERT INTO gold.rag_corpus" in sql:
                insert_call = call
                break

        assert insert_call is not None
        params = insert_call[0][1]
        assert params[0] == record.chunk_key
        assert params[1] == record.conference_id
        assert params[2] == "2024-10-01"
        assert params[3] == record.participant
        assert params[4] == record.text
        assert "Contexto: Conferencia del 2024-10-01" in params[5]
        assert params[6] == record.url
        assert params[7] == ""
        assert params[8] == [0.5] * 768

        mock_embed.assert_called_once_with(
            "P: Q?\nPRESIDENTA: R.", "http://localhost:11434", "nomic-embed-text"
        )

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_empty_interventions_list(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        result = enrich_interventions(
            windows=[],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 0
        assert result["embedded"] == 0
        assert result["failed"] == 0
        mock_embed.assert_not_called()

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_partial_embedding_failure_logs_and_continues(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_embed.side_effect = [
            [0.1] * 768,
            ConnectionError("Ollama embedding failed after 3 retries"),
            [0.2] * 768,
        ]

        records = [self._window(i, f"Texto {i}") for i in range(3)]

        result = enrich_interventions(
            windows=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 3
        assert result["embedded"] == 2
        assert result["failed"] == 1

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_on_conflict_do_nothing(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        class MockExecute:
            def __init__(self) -> None:
                self.call_count = 0

            def __call__(self, sql: str, params: tuple | None = None) -> MagicMock:
                self.call_count += 1
                if self.call_count == 2:
                    raise ValueError(
                        'duplicate key value violates unique constraint "rag_corpus_pkey"'
                    )
                return MagicMock()

        mock_cursor.execute = MockExecute()

        result = enrich_interventions(
            windows=[self._window(0)],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        assert result["failed"] == 0


class TestBuildEmbeddingText:
    def test_build_embedding_text_with_pregunta(self) -> None:
        intervention = InterventionRecord(
            intervention_key="k1",
            conference_id="c1",
            participant="PRESIDENTA",
            text="Avanzamos en paneles solares en Sonora.",
            pregunta_activa="Como va la reforma energetica?",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert (
            result
            == "P: Como va la reforma energetica?\nR: Avanzamos en paneles solares en Sonora."
        )
        assert "Conferencia" not in result
        assert "Participante" not in result
        assert "Contexto" not in result
        assert intervention.participant not in result

    def test_build_embedding_text_without_pregunta(self) -> None:
        intervention = InterventionRecord(
            intervention_key="k2",
            conference_id="c2",
            participant="SECRETARIO",
            text="Se implemento la estrategia nacional de seguridad.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert result == "R: Se implemento la estrategia nacional de seguridad."
        assert "P:" not in result
        assert "Conferencia" not in result

    def test_build_embedding_text_no_ids_no_hashes(self) -> None:
        intervention = InterventionRecord(
            intervention_key="k3_abc123",
            conference_id="conf_xyz",
            participant="PRESIDENTA",
            text="Contenido de prueba.",
            pregunta_activa="Pregunta?",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert intervention.intervention_key not in result
        assert intervention.conference_id not in result
        assert str(intervention.chunk_index) not in result


class TestEmbedOne:
    def test_returns_embedding_on_success(self) -> None:
        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text="P: Como va la reforma?\nPRESIDENTA: Avanzamos en paneles.",
            url="https://example.com",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.return_value = [0.1] * 768
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding == [0.1] * 768
        mock_embed.assert_called_once_with(
            "P: Como va la reforma?\nPRESIDENTA: Avanzamos en paneles.",
            "http://localhost:11434",
            "nomic-embed-text",
        )

    def test_returns_none_on_connection_error(self) -> None:
        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="P",
            text="texto",
            url="",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ConnectionError("Ollama embedding failed after 3 retries")
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding is None

    def test_returns_none_on_value_error(self) -> None:
        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="P",
            text="texto",
            url="",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ValueError("Ollama returned empty embeddings")
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding is None


class TestStoreGold:
    def test_executes_insert_with_window_params(self) -> None:
        cur = MagicMock()
        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text="P: Q?\nPRESIDENTA: R.",
            url="https://example.com",
            window_index=0,
        )
        _store_gold(cur, record, "2025-03-01", [0.1] * 768)
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO gold.rag_corpus" in sql
        assert params[0] == "conf1_w000_abc123"
        assert params[2] == "2025-03-01"
        assert params[4] == "P: Q?\nPRESIDENTA: R."  # chunk_text
        assert (
            params[5]
            == "Contexto: Conferencia del 2025-03-01\nParticipante: PRESIDENTA\nPregunta activa: \nRespuesta: P: Q?\nPRESIDENTA: R."
        )  # payload con metadata
        assert params[7] == ""  # pregunta_activa vacia
        assert params[8] == [0.1] * 768


class TestEnrichInterventionsParallel:
    def _window(self, i: int, text: str) -> WindowRecord:
        return WindowRecord(
            chunk_key=f"conf1_w{i:03d}_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant=f"P {i}",
            text=text,
            url="",
            window_index=i,
        )

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_runs_embeddings_in_parallel_threads(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        seen_threads: set[int] = set()
        arrivals = 0
        arrivals_lock = threading.Lock()
        release = threading.Event()

        def side_effect(text: str, base_url: str, model: str) -> list[float]:
            nonlocal arrivals
            with arrivals_lock:
                seen_threads.add(threading.current_thread().ident or 0)
                arrivals += 1
                if arrivals >= 2:
                    release.set()
            release.wait(timeout=5)
            return [0.5] * 768

        mock_embed.side_effect = side_effect

        records = [self._window(i, f"Texto {i}") for i in range(3)]

        main_thread_id = threading.current_thread().ident or 0

        result = enrich_interventions(
            windows=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=2,
        )

        assert result["total"] == 3
        assert result["embedded"] == 3
        assert result["failed"] == 0
        assert main_thread_id not in seen_threads
        assert len(seen_threads) > 1

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_greater_than_one_embeds_all(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        records = [self._window(i, f"Texto {i}") for i in range(5)]

        result = enrich_interventions(
            windows=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=3,
        )

        assert result["total"] == 5
        assert result["embedded"] == 5
        assert result["failed"] == 0
        assert mock_embed.call_count == 5
        insert_count = sum(
            1
            for c in mock_cursor.execute.call_args_list
            if "INSERT INTO gold.rag_corpus" in c[0][0]
        )
        assert insert_count == 5

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_parallel_counts_failures(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        def side_effect(text: str, base_url: str, model: str) -> list[float]:
            if "Texto 1" in text:
                raise ConnectionError("Ollama embedding failed after 3 retries")
            return [0.5] * 768

        mock_embed.side_effect = side_effect

        records = [self._window(i, f"Texto {i}") for i in range(3)]

        result = enrich_interventions(
            windows=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=2,
        )

        assert result["total"] == 3
        assert result["embedded"] == 2
        assert result["failed"] == 1

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_zero_clamped_to_one(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        records = [self._window(0, "Texto")]

        result = enrich_interventions(
            windows=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=0,
        )

        assert result["embedded"] == 1
        assert result["failed"] == 0

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_parallel_window_without_date_is_failed(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        record = self._window(0, "Texto")
        record.conference_date = (
            ""  # fecha invalida (el schema exige patron, se asigna post-construccion)
        )

        result = enrich_interventions(
            windows=[record],
            conference_date=None,
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=2,
        )

        assert result["embedded"] == 0
        assert result["failed"] == 1
        assert mock_embed.call_count == 0

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_parallel_unique_violation_counts_embedded(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        def raise_unique(sql: str, params=None) -> MagicMock:
            if "INSERT INTO gold.rag_corpus" in sql:
                raise psycopg.errors.UniqueViolation("duplicate key")
            return MagicMock()

        mock_cursor.execute.side_effect = raise_unique

        result = enrich_interventions(
            windows=[self._window(0, "Texto"), self._window(1, "Texto 2")],
            conference_date="2025-03-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=2,
        )

        assert result["embedded"] == 2
        assert result["failed"] == 0


class TestEnrichInterrupt:
    def _window(self, i: int, text: str = "Texto de la ventana.") -> WindowRecord:
        return WindowRecord(
            chunk_key=f"conf1_w{i:03d}_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text=text,
            url="https://example.com",
            window_index=i,
        )

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_sequential_stops_on_interrupt(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        with patch.object(interrupt_state, "requested", side_effect=[False, True]):
            result = enrich_interventions(
                windows=[self._window(0), self._window(1)],
                conference_date="2024-10-01",
                pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
                ollama_base_url="http://localhost:11434",
                ollama_model="nomic-embed-text",
            )

        assert result["total"] == 2
        assert result["embedded"] == 1
        assert result["failed"] == 0
        assert mock_embed.call_count == 1

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_parallel_stops_submitting_on_interrupt(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        with patch.object(interrupt_state, "requested", side_effect=[False, True]):
            result = enrich_interventions(
                windows=[self._window(0), self._window(1)],
                conference_date="2024-10-01",
                pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
                ollama_base_url="http://localhost:11434",
                ollama_model="nomic-embed-text",
                workers=2,
            )

        assert result["total"] == 2
        assert result["embedded"] == 1
        assert result["failed"] == 0
        assert mock_embed.call_count == 1


class TestBuildWindows:
    def _iv(self, i: int, text: str, conference_id: str = "conf1") -> InterventionRecord:
        return InterventionRecord(
            intervention_key=f"k{i:03d}",
            conference_id=conference_id,
            participant="PRESIDENTA",
            text=text,
            pregunta_activa=f"Pregunta {i}",
            chunk_index=i,
            url="https://example.com",
            conference_date="2025-03-01",
        )

    def test_single_window_under_max_tokens(self) -> None:
        ivs = [self._iv(0, "Hola."), self._iv(1, "Mundo."), self._iv(2, "Test.")]
        windows = build_windows(ivs, max_tokens=1600)
        assert len(windows) == 1
        assert len(windows[0]) == 3

    def test_splits_into_multiple_windows_with_overlap(self) -> None:
        long_text = "palabra " * 200  # ~200 tokens
        ivs = [self._iv(i, long_text) for i in range(6)]
        windows = build_windows(ivs, max_tokens=500, overlap_tokens=50)
        assert len(windows) > 1
        last_of_first = windows[0][-1].intervention_key
        first_keys_second = {iv.intervention_key for iv in windows[1]}
        assert last_of_first in first_keys_second

    def test_empty_list_returns_empty(self) -> None:
        assert build_windows([]) == []

    def test_single_intervention_returns_one_window(self) -> None:
        ivs = [self._iv(0, "Hola.")]
        windows = build_windows(ivs)
        assert len(windows) == 1
        assert len(windows[0]) == 1

    def test_single_oversized_intervention_gets_own_window(self) -> None:
        big_text = "palabra " * 1000  # ~2000 tokens > max_tokens=500
        ivs = [self._iv(0, big_text), self._iv(1, "Hola.")]
        windows = build_windows(ivs, max_tokens=500, overlap_tokens=50)
        # la intervencion grande va sola en su ventana, la chica en otra
        assert len(windows) == 2
        assert len(windows[0]) == 1
        assert len(windows[1]) == 1

    def test_windows_bounded_by_max_tokens_plus_one_intervention(self) -> None:
        long_text = "palabra " * 200  # 400 tokens
        ivs = [self._iv(i, long_text) for i in range(6)]
        max_tokens = 500
        overlap_tokens = 50
        windows = build_windows(ivs, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        max_single = estimate_tokens(long_text)
        for w in windows:
            total = sum(estimate_tokens(iv.text) for iv in w)
            assert total <= max_tokens + max_single + overlap_tokens

    def test_mid_sequence_oversized_intervention_gets_own_window(self) -> None:
        big_text = "palabra " * 1000  # ~2000 tokens > max_tokens=500
        ivs = [self._iv(0, "Hola."), self._iv(1, big_text), self._iv(2, "Mundo.")]
        windows = build_windows(ivs, max_tokens=500, overlap_tokens=50)
        assert len(windows) == 3
        for w in windows:
            assert len(w) == 1
        assert windows[1][0].intervention_key == "k001"

    def test_overlap_tokens_must_be_less_than_max_tokens(self) -> None:
        ivs = [self._iv(0, "Hola.")]
        with pytest.raises(ValueError, match="overlap_tokens"):
            build_windows(ivs, max_tokens=100, overlap_tokens=100)


class TestBuildWindowText:
    def test_includes_pregunta_and_participant(self) -> None:
        iv = InterventionRecord(
            intervention_key="k000",
            conference_id="conf1",
            participant="PRESIDENTA",
            text="Avanzamos en paneles.",
            pregunta_activa="Como va la reforma?",
            chunk_index=0,
            url="https://example.com",
        )
        text = build_window_text([iv])
        assert "P: Como va la reforma?" in text
        assert "PRESIDENTA: Avanzamos en paneles." in text

    def test_without_pregunta_omits_p_label(self) -> None:
        iv = InterventionRecord(
            intervention_key="k000",
            conference_id="conf1",
            participant="SECRETARIO",
            text="Se implemento la estrategia.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )
        text = build_window_text([iv])
        assert text == "SECRETARIO: Se implemento la estrategia."
        assert "P:" not in text

    def test_multiple_interventions_separated_by_blank_line(self) -> None:
        ivs = [
            InterventionRecord(
                intervention_key="k000",
                conference_id="c",
                participant="P1",
                text="Uno.",
                pregunta_activa="",
                chunk_index=0,
                url="",
            ),
            InterventionRecord(
                intervention_key="k001",
                conference_id="c",
                participant="P2",
                text="Dos.",
                pregunta_activa="Q?",
                chunk_index=1,
                url="",
            ),
        ]
        text = build_window_text(ivs)
        assert text.count("\n\n") == 1


class TestBuildWindowKey:
    def test_deterministic_for_same_text(self) -> None:
        k1 = build_window_key("conf1", 0, "mismo texto")
        k2 = build_window_key("conf1", 0, "mismo texto")
        assert k1 == k2

    def test_differs_for_index(self) -> None:
        k1 = build_window_key("conf1", 0, "texto")
        k2 = build_window_key("conf1", 1, "texto")
        assert k1 != k2

    def test_contains_conference_and_index(self) -> None:
        key = build_window_key("conf1", 2, "texto")
        assert key.startswith("conf1_w002_")
        assert len(key) == len("conf1_w002_") + 6
