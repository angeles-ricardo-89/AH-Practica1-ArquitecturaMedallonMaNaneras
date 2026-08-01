from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest

from lakehouse.pipeline.enrichment import (
    _embed_one,
    _store_gold,
    build_embedding_payload,
    build_embedding_text,
    drop_gold_tables,
    embed_text,
    enrich_interventions,
    ensure_gold_tables,
    get_pgvector_connection_string,
)
from lakehouse.schemas.silver import InterventionRecord


@pytest.fixture
def sample_intervention() -> InterventionRecord:
    return InterventionRecord(
        intervention_key="abc123_000_abc123",
        conference_id="conf123",
        participant="PRESIDENTA CLAUDIA SHEINBAUM PARDO",
        text="Buenos días. Hoy vamos a informar sobre los avances del país.",
        pregunta_activa="¿Cómo va la reforma energética?",
        chunk_index=0,
        url="https://example.com/conf-2024-10-01",
        ingested_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_intervention_no_question() -> InterventionRecord:
    return InterventionRecord(
        intervention_key="def456_001_def456",
        conference_id="conf456",
        participant="SECRETARIO DE GOBERNACIÓN",
        text="Informamos que los programas sociales continúan.",
        pregunta_activa="",
        chunk_index=1,
        url="https://example.com/conf-2024-10-01",
        ingested_at=datetime.now(UTC),
    )


class TestBuildEmbeddingPayload:
    def test_format_matches_prd(self, sample_intervention: InterventionRecord):
        payload = build_embedding_payload(
            intervention=sample_intervention,
            conference_date="2024-10-01",
        )
        expected = (
            "Contexto: Conferencia del 2024-10-01\n"
            "Participante: PRESIDENTA CLAUDIA SHEINBAUM PARDO\n"
            "Pregunta activa: ¿Cómo va la reforma energética?\n"
            "Respuesta: Buenos días. Hoy vamos a informar sobre los avances del país."
        )
        assert payload == expected

    def test_no_pregunta_activa(self, sample_intervention_no_question: InterventionRecord):
        payload = build_embedding_payload(
            intervention=sample_intervention_no_question,
            conference_date="2025-01-15",
        )
        expected = (
            "Contexto: Conferencia del 2025-01-15\n"
            "Participante: SECRETARIO DE GOBERNACIÓN\n"
            "Pregunta activa: \n"
            "Respuesta: Informamos que los programas sociales continúan."
        )
        assert payload == expected

    def test_no_technical_ids_or_hashes(self, sample_intervention: InterventionRecord):
        payload = build_embedding_payload(
            intervention=sample_intervention,
            conference_date="2024-10-01",
        )
        assert "abc123" not in payload
        assert "conf123" not in payload
        assert "intervention_key" not in payload.lower()
        assert "chunk_index" not in payload.lower()

    def test_special_characters(self):
        record = InterventionRecord(
            intervention_key="spec_000_chars",
            conference_id="spec",
            participant="LIC. MARÍA JOSÉ PÉREZ",
            text="Costo: $1,234.56 — 100% real. ¡Vamos! ¿De acuerdo?",
            pregunta_activa="¿Costo total? $500 pesos",
            chunk_index=0,
            url="https://example.com",
        )
        payload = build_embedding_payload(
            intervention=record,
            conference_date="2025-03-01",
        )
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

        record = InterventionRecord(
            intervention_key="k1",
            conference_id="c1",
            participant="PRESIDENTA",
            text="Texto de prueba.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
            conference_date="2025-03-01",
        )

        result = enrich_interventions(
            interventions=[record],
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

        record = InterventionRecord(
            intervention_key="k2",
            conference_id="c2",
            participant="PRESIDENTA",
            text="Texto de prueba.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
            conference_date="2025-03-01",
        )

        result = enrich_interventions(
            interventions=[record],
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

        record = InterventionRecord(
            intervention_key="k3",
            conference_id="c3",
            participant="PRESIDENTA",
            text="Texto de prueba.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )

        result = enrich_interventions(
            interventions=[record],
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

        record = InterventionRecord(
            intervention_key="k4",
            conference_id="c4",
            participant="PRESIDENTA",
            text="Texto de prueba.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
            conference_date="2025-03-01",
        )

        result = enrich_interventions(
            interventions=[record],
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
        sample_intervention: InterventionRecord,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        enrich_interventions(
            interventions=[sample_intervention],
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
        sample_intervention: InterventionRecord,
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        result = enrich_interventions(
            interventions=[sample_intervention],
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
        assert params[0] == sample_intervention.intervention_key
        assert params[1] == sample_intervention.conference_id
        assert params[2] == "2024-10-01"
        assert params[3] == sample_intervention.participant
        assert params[4] == sample_intervention.text
        assert "Contexto: Conferencia del 2024-10-01" in params[5]
        assert params[6] == sample_intervention.url
        assert params[7] == sample_intervention.pregunta_activa
        assert params[8] == [0.5] * 768

        expected_embed_text = build_embedding_text(sample_intervention)
        mock_embed.assert_called_once_with(
            expected_embed_text, "http://localhost:11434", "nomic-embed-text"
        )
        assert "Contexto" not in expected_embed_text
        assert "Participante" not in expected_embed_text

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_empty_interventions_list(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        result = enrich_interventions(
            interventions=[],
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

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(3)
        ]

        result = enrich_interventions(
            interventions=records,
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
        sample_intervention: InterventionRecord,
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
            interventions=[sample_intervention],
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
    def test_returns_payload_and_embedding_on_success(
        self, sample_intervention: InterventionRecord
    ) -> None:
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.return_value = [0.1] * 768
            payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert "Contexto: Conferencia del 2024-10-01" in payload
        assert "Participante:" in payload
        assert embedding == [0.1] * 768
        mock_embed.assert_called_once_with(
            build_embedding_text(sample_intervention),
            "http://localhost:11434",
            "nomic-embed-text",
        )

    def test_returns_none_on_connection_error(
        self, sample_intervention: InterventionRecord
    ) -> None:
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ConnectionError("Ollama embedding failed after 3 retries")
            payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert embedding is None
        assert "Contexto: Conferencia del 2024-10-01" in payload

    def test_returns_none_on_value_error(self, sample_intervention: InterventionRecord) -> None:
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ValueError("Ollama returned empty embeddings")
            _payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert embedding is None


class TestStoreGold:
    def test_executes_insert_with_correct_params(
        self, sample_intervention: InterventionRecord
    ) -> None:
        cur = MagicMock()
        _store_gold(
            cur,
            sample_intervention,
            "2024-10-01",
            "payload metadata",
            [0.1] * 768,
        )
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO gold.rag_corpus" in sql
        assert params[0] == sample_intervention.intervention_key
        assert params[2] == "2024-10-01"
        assert params[5] == "payload metadata"
        assert params[8] == [0.1] * 768


class TestEnrichInterventionsParallel:
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

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"P {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(3)
        ]

        main_thread_id = threading.current_thread().ident or 0

        result = enrich_interventions(
            interventions=records,
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

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(5)
        ]

        result = enrich_interventions(
            interventions=records,
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

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(3)
        ]

        result = enrich_interventions(
            interventions=records,
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

        records = [
            InterventionRecord(
                intervention_key="rec_000_hash",
                conference_id="conf",
                participant="P",
                text="Texto",
                pregunta_activa="",
                chunk_index=0,
                url="https://example.com",
            )
        ]

        result = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=0,
        )

        assert result["embedded"] == 1
        assert result["failed"] == 0
