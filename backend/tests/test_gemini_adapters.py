from __future__ import annotations

from typing import ClassVar

import psycopg
import pytest
from google import genai
from google.genai import types

from lakehouse.config import Settings
from lakehouse.db.index_metadata import (
    ensure_index_metadata_tables,
    read_index_metadata,
    store_index_metadata,
)
from lakehouse.db.pgvector_conn import build_neon_connection_string
from lakehouse.schemas.index_metadata import IndexMetadata
from lakehouse.services.gemini_chat import GeminiChatAdapter
from lakehouse.services.gemini_embedding import (
    RETRIEVAL_DOCUMENT,
    RETRIEVAL_QUERY,
    GeminiEmbeddingAdapter,
)
from lakehouse.services.index_metadata import (
    IndexMetadataMismatchError,
    build_corpus_hash,
    validate_index_at_startup,
    validate_query_config,
)
from lakehouse.services.reindex_production import reindex_corpus


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self) -> None:
        self.embed_calls: list[tuple] = []
        self.generate_calls: list[tuple] = []
        self.embed_batches: list[list[list[float]]] = []
        self.gen_text = ""

    def embed_content(self, *, model, contents, config=None) -> types.EmbedContentResponse:
        self.embed_calls.append((model, list(contents), config))
        batch = self.embed_batches.pop(0)
        return types.EmbedContentResponse(
            embeddings=[types.ContentEmbedding(values=list(v)) for v in batch]
        )

    def generate_content(self, *, model, contents, config=None) -> _FakeResponse:
        self.generate_calls.append((model, contents, config))
        return _FakeResponse(self.gen_text)


class _FakeClient:
    api_keys: ClassVar[list[str | None]] = []
    shared_models: _FakeModels | None = None

    def __init__(self, api_key: str | None = None, **kwargs: object) -> None:
        self.api_key = api_key
        _FakeClient.api_keys.append(api_key)
        if _FakeClient.shared_models is None:
            _FakeClient.shared_models = _FakeModels()
        self.models = _FakeClient.shared_models


@pytest.fixture
def fake_genai(monkeypatch) -> _FakeModels:
    models = _FakeModels()
    _FakeClient.shared_models = models
    _FakeClient.api_keys = []
    monkeypatch.setattr(genai, "Client", _FakeClient)
    return models


def _sample_metadata(**overrides: object) -> IndexMetadata:
    base = {
        "provider": "google",
        "model": "gemini-embedding-001",
        "dimension": 768,
        "task_type": RETRIEVAL_DOCUMENT,
        "format_version": "v1",
        "built_at": "2026-09-05T00:00:00+00:00",
        "corpus_hash": "abc123",
    }
    base.update(overrides)
    return IndexMetadata(**base)


class TestGeminiEmbeddingAdapter:
    def test_embed_documents_uses_retrieval_document_task_and_dimension(self, fake_genai):
        fake_genai.embed_batches = [[[0.1, 0.2], [0.3, 0.4]]]
        adapter = GeminiEmbeddingAdapter(api_key="k", model="gemini-embedding-001", dimension=2)
        vectors = adapter.embed_documents(["uno", "dos"])
        assert _FakeClient.api_keys[-1] == "k"
        model, contents, config = fake_genai.embed_calls[0]
        assert model == "gemini-embedding-001"
        assert contents == ["uno", "dos"]
        assert config.task_type == RETRIEVAL_DOCUMENT
        assert config.output_dimensionality == 2
        assert len(vectors) == 2

    def test_embed_query_uses_retrieval_query_task(self, fake_genai):
        fake_genai.embed_batches = [[[0.5, 0.5]]]
        adapter = GeminiEmbeddingAdapter(api_key="k", model="gemini-embedding-001", dimension=2)
        vector = adapter.embed_query("pregunta")
        _model, contents, config = fake_genai.embed_calls[0]
        assert config.task_type == RETRIEVAL_QUERY
        assert contents == ["pregunta"]
        assert len(vector) == 2

    def test_embeddings_are_l2_normalized(self, fake_genai):
        fake_genai.embed_batches = [[[3.0, 4.0]]]
        adapter = GeminiEmbeddingAdapter(api_key="k", model="m", dimension=2)
        vector = adapter.embed_query("q")
        assert vector == pytest.approx([0.6, 0.8])

    def test_dimension_mismatch_fails_closed(self, fake_genai):
        fake_genai.embed_batches = [[[0.1, 0.2, 0.3]]]
        adapter = GeminiEmbeddingAdapter(api_key="k", model="m", dimension=768)
        with pytest.raises(RuntimeError, match="dimension"):
            adapter.embed_documents(["hola"])

    def test_missing_api_key_fails_closed(self):
        adapter = GeminiEmbeddingAdapter(api_key="", model="gemini-embedding-001")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            adapter.embed_query("q")

    def test_embed_documents_empty_returns_empty(self):
        adapter = GeminiEmbeddingAdapter(api_key="k", model="m")
        assert adapter.embed_documents([]) == []


class TestGeminiChatAdapter:
    def test_generate_returns_text(self, fake_genai):
        fake_genai.gen_text = "respuesta"
        adapter = GeminiChatAdapter(api_key="k", model="gemini-3.5-flash-lite")
        text = adapter.generate([{"role": "user", "content": "hola"}], temperature=0.2)
        assert text == "respuesta"
        model, contents, config = fake_genai.generate_calls[0]
        assert model == "gemini-3.5-flash-lite"
        assert config.temperature == 0.2
        assert contents[0].role == "user"

    def test_missing_api_key_fails_closed(self):
        adapter = GeminiChatAdapter(api_key="", model="gemini-3.5-flash-lite")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            adapter.generate([{"role": "user", "content": "hola"}])

    def test_system_role_becomes_system_instruction(self, fake_genai):
        fake_genai.gen_text = "ok"
        adapter = GeminiChatAdapter(api_key="k", model="gemini-3.5-flash-lite")
        adapter.generate(
            [
                {"role": "system", "content": "Eres un agente"},
                {"role": "user", "content": "pregunta"},
                {"role": "assistant", "content": "respuesta previa"},
            ]
        )
        _model, contents, config = fake_genai.generate_calls[0]
        roles = [c.role for c in contents]
        assert roles == ["user", "model"]
        assert config.system_instruction == "Eres un agente"


class TestNeonConnectionString:
    def test_adds_sslmode_require_when_missing(self):
        url = "postgresql://u:p@ep-test-pooler.us-east-2.aws.neon.tech/db"
        assert build_neon_connection_string(url).endswith("sslmode=require")

    def test_idempotent_when_sslmode_present(self):
        url = "postgresql://u:p@ep-test-pooler.us-east-2.aws.neon.tech/db?sslmode=require"
        assert build_neon_connection_string(url) == url

    def test_requires_pooled_endpoint(self):
        url = "postgresql://u:p@ep-test.us-east-2.aws.neon.tech/db?sslmode=require"
        with pytest.raises(ValueError, match="pooler"):
            build_neon_connection_string(url)


class TestIndexMetadataValidation:
    def test_matching_config_passes(self):
        metadata = _sample_metadata()
        validate_query_config(
            metadata,
            provider="google",
            model="gemini-embedding-001",
            dimension=768,
            query_task_type=RETRIEVAL_QUERY,
        )

    def test_model_mismatch_raises(self):
        metadata = _sample_metadata()
        with pytest.raises(IndexMetadataMismatchError):
            validate_query_config(
                metadata,
                provider="google",
                model="otro-modelo",
                dimension=768,
                query_task_type=RETRIEVAL_QUERY,
            )

    def test_dimension_mismatch_raises(self):
        metadata = _sample_metadata()
        with pytest.raises(IndexMetadataMismatchError):
            validate_query_config(
                metadata,
                provider="google",
                model="gemini-embedding-001",
                dimension=512,
                query_task_type=RETRIEVAL_QUERY,
            )

    def test_provider_mismatch_raises(self):
        metadata = _sample_metadata()
        with pytest.raises(IndexMetadataMismatchError):
            validate_query_config(
                metadata,
                provider="ollama",
                model="gemini-embedding-001",
                dimension=768,
                query_task_type=RETRIEVAL_QUERY,
            )

    def test_index_task_type_mismatch_raises(self):
        metadata = _sample_metadata(task_type=RETRIEVAL_QUERY)
        with pytest.raises(IndexMetadataMismatchError):
            validate_query_config(
                metadata,
                provider="google",
                model="gemini-embedding-001",
                dimension=768,
                query_task_type=RETRIEVAL_QUERY,
            )

    def test_query_task_type_mismatch_raises(self):
        metadata = _sample_metadata()
        with pytest.raises(IndexMetadataMismatchError):
            validate_query_config(
                metadata,
                provider="google",
                model="gemini-embedding-001",
                dimension=768,
                query_task_type=RETRIEVAL_DOCUMENT,
            )


class TestBuildCorpusHash:
    def test_deterministic_and_order_independent(self):
        assert build_corpus_hash(["a", "b"]) == build_corpus_hash(["b", "a"])
        assert build_corpus_hash(["a", "b"]) == build_corpus_hash(["a", "b"])
        assert build_corpus_hash(["a", "b"]) != build_corpus_hash(["a", "b", "c"])


class TestIndexMetadataStore:
    def test_store_and_read_roundtrip(self, pg_conn_str):
        ensure_index_metadata_tables(pg_conn_str)
        try:
            metadata = _sample_metadata()
            store_index_metadata(pg_conn_str, metadata)
            assert read_index_metadata(pg_conn_str) == metadata
        finally:
            with psycopg.connect(pg_conn_str) as conn:
                conn.execute("DELETE FROM index_metadata")
                conn.commit()


class TestValidateIndexAtStartup:
    def test_noop_when_local(self):
        settings = Settings(app_env="local")
        validate_index_at_startup(settings)

    def test_noop_when_production_without_neon_url(self):
        settings = Settings(app_env="production", neon_database_url="")
        validate_index_at_startup(settings)

    def test_raises_on_mismatch_in_production(self, monkeypatch):
        settings = Settings(
            app_env="production",
            neon_database_url=(
                "postgresql://u:p@ep-test-pooler.us-east-2.aws.neon.tech/db?sslmode=require"
            ),
            gemini_embedding_model="gemini-embedding-001",
            gemini_embedding_dimension=768,
        )
        stored = _sample_metadata(model="otro-modelo")

        def fake_read(conn_str: str) -> IndexMetadata:
            return stored

        monkeypatch.setattr("lakehouse.services.index_metadata.read_index_metadata", fake_read)
        with pytest.raises(IndexMetadataMismatchError):
            validate_index_at_startup(settings)

    def test_raises_when_no_metadata_in_production(self, monkeypatch):
        settings = Settings(
            app_env="production",
            neon_database_url=(
                "postgresql://u:p@ep-test-pooler.us-east-2.aws.neon.tech/db?sslmode=require"
            ),
        )
        monkeypatch.setattr("lakehouse.services.index_metadata.read_index_metadata", lambda _: None)
        with pytest.raises(IndexMetadataMismatchError, match="No index metadata"):
            validate_index_at_startup(settings)


class TestReindexCorpus:
    def _create_index_table(self, conn_str: str, schema: str) -> None:
        with psycopg.connect(conn_str) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.rag_corpus (
                    chunk_key VARCHAR PRIMARY KEY,
                    conference_id VARCHAR,
                    conference_date DATE,
                    participant VARCHAR,
                    chunk_text TEXT,
                    payload TEXT,
                    url VARCHAR,
                    pregunta_activa VARCHAR,
                    embedding vector(768)
                )
                """
            )
            conn.commit()

    def _seed_source(self, conn_str: str, schema: str) -> None:
        with psycopg.connect(conn_str) as conn:
            conn.execute(f"DELETE FROM {schema}.rag_corpus")
            conn.execute(
                f"""
                INSERT INTO {schema}.rag_corpus
                    (chunk_key, conference_id, conference_date, participant, chunk_text, payload, url, pregunta_activa)
                VALUES
                    ('k1', 'c1', '2024-10-01', 'A', 'texto uno', 'payload uno', 'http://x/1', ''),
                    ('k2', 'c2', '2024-10-02', 'B', 'texto dos', 'payload dos', 'http://x/2', 'q2')
                """
            )
            conn.commit()

    def test_writes_to_separate_target_and_records_metadata(self, pg_conn_str):
        src = "reindex_src"
        dst = "reindex_dst"
        self._create_index_table(pg_conn_str, src)
        self._create_index_table(pg_conn_str, dst)
        self._seed_source(pg_conn_str, src)
        try:

            def fake_embed(texts: list[str]) -> list[list[float]]:
                return [[0.5] * 768 for _ in texts]

            result = reindex_corpus(
                source_conn_str=pg_conn_str,
                target_conn_str=pg_conn_str,
                embed_documents=fake_embed,
                provider="google",
                model="gemini-embedding-001",
                dimension=768,
                task_type=RETRIEVAL_DOCUMENT,
                format_version="v1",
                source_table=f"{src}.rag_corpus",
                target_table=f"{dst}.rag_corpus",
            )
            assert result["total"] == 2
            assert result["embedded"] == 2

            with psycopg.connect(pg_conn_str) as conn:
                src_rows = conn.execute(f"SELECT COUNT(*) FROM {src}.rag_corpus").fetchone()
                dst_rows = conn.execute(f"SELECT COUNT(*) FROM {dst}.rag_corpus").fetchone()
                src_emb = conn.execute(
                    f"SELECT COUNT(*) FROM {src}.rag_corpus WHERE embedding IS NOT NULL"
                ).fetchone()
            assert src_rows[0] == 2
            assert src_emb[0] == 0  # source embeddings untouched
            assert dst_rows[0] == 2

            stored = read_index_metadata(pg_conn_str)
            assert stored is not None
            assert stored.provider == "google"
            assert stored.model == "gemini-embedding-001"
            assert stored.dimension == 768
            assert stored.task_type == RETRIEVAL_DOCUMENT
        finally:
            with psycopg.connect(pg_conn_str) as conn:
                conn.execute(f"DROP SCHEMA IF EXISTS {src} CASCADE")
                conn.execute(f"DROP SCHEMA IF EXISTS {dst} CASCADE")
                conn.execute("DELETE FROM index_metadata")
                conn.commit()
