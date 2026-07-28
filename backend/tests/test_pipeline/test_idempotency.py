from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from lakehouse.db.duckdb_conn import ensure_bronze_table, insert_bronze_record
from lakehouse.db.merge import ensure_silver_tables, merge_conference, merge_intervention
from lakehouse.pipeline.enrichment import enrich_interventions
from lakehouse.schemas.silver import ConferenceRecord, InterventionRecord


@pytest.fixture
def duck_conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_interventions() -> list[InterventionRecord]:
    return [
        InterventionRecord(
            intervention_key="idem_001_key_abc",
            conference_id="conf_idem_001",
            participant="PRESIDENTA",
            text="Buenos días a todos.",
            pregunta_activa="¿Cómo va la reforma?",
            chunk_index=0,
            ingested_at=datetime.now(UTC),
        ),
        InterventionRecord(
            intervention_key="idem_002_key_def",
            conference_id="conf_idem_001",
            participant="SECRETARIO DE SALUD",
            text="Informamos sobre los avances.",
            pregunta_activa="",
            chunk_index=1,
            ingested_at=datetime.now(UTC),
        ),
    ]


class TestBronzeIdempotency:
    def test_insert_duplicate_content_hash_returns_false(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:
        ensure_bronze_table(duck_conn)

        first = insert_bronze_record(
            conn=duck_conn,
            ingestion_run_id="run_001",
            source_url="https://gob.mx/art1",
            raw_html="<html>contenido</html>",
            content_hash="hash_abc",
        )
        assert first is True

        second = insert_bronze_record(
            conn=duck_conn,
            ingestion_run_id="run_002",
            source_url="https://gob.mx/art1",
            raw_html="<html>contenido</html>",
            content_hash="hash_abc",
        )
        assert second is False

    def test_different_content_hash_inserts_both(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:
        ensure_bronze_table(duck_conn)

        insert_bronze_record(
            conn=duck_conn,
            ingestion_run_id="run_001",
            source_url="https://gob.mx/art1",
            raw_html="<html>primero</html>",
            content_hash="hash_001",
        )
        insert_bronze_record(
            conn=duck_conn,
            ingestion_run_id="run_001",
            source_url="https://gob.mx/art2",
            raw_html="<html>segundo</html>",
            content_hash="hash_002",
        )

        count = duck_conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchone()[0]
        assert count == 2

    def test_content_hash_primary_key_enforced(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:

        ensure_bronze_table(duck_conn)

        duck_conn.execute(
            """
            INSERT INTO bronze.raw_html (ingestion_run_id, source_url, raw_html, content_hash)
            VALUES ('run_001', 'https://gob.mx/art', '<html>a</html>', 'hash_unique')
            """,
        )

        count_after_first = duck_conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchone()[0]
        assert count_after_first == 1

        duck_conn.execute(
            """
            INSERT OR IGNORE INTO bronze.raw_html (ingestion_run_id, source_url, raw_html, content_hash)
            VALUES ('run_002', 'https://gob.mx/art', '<html>a</html>', 'hash_unique')
            """,
        )

        count_after_second = duck_conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchone()[0]
        assert count_after_second == 1


class TestSilverIdempotency:
    def test_insert_or_ignore_prevents_duplicate_intervention_key(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:

        ensure_silver_tables(duck_conn)

        record = InterventionRecord(
            intervention_key="interv_001",
            conference_id="conf_001",
            participant="PRESIDENTA",
            text="Texto de prueba.",
            pregunta_activa="",
            chunk_index=0,
        )

        merge_intervention(duck_conn, record)
        count_first = duck_conn.execute("SELECT COUNT(*) FROM silver.interventions").fetchone()[0]
        assert count_first == 1

        merge_intervention(duck_conn, record)
        count_second = duck_conn.execute("SELECT COUNT(*) FROM silver.interventions").fetchone()[0]
        assert count_second == 1

    def test_second_parse_does_not_add_duplicates(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:

        ensure_silver_tables(duck_conn)

        records = [
            InterventionRecord(
                intervention_key=f"interv_00{i}",
                conference_id="conf_001",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
            )
            for i in range(3)
        ]

        for r in records:
            merge_intervention(duck_conn, r)

        first_count = duck_conn.execute("SELECT COUNT(*) FROM silver.interventions").fetchone()[0]
        assert first_count == 3

        for r in records:
            merge_intervention(duck_conn, r)

        second_count = duck_conn.execute("SELECT COUNT(*) FROM silver.interventions").fetchone()[0]
        assert second_count == 3

    def test_different_interventions_insert_normally(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:

        ensure_silver_tables(duck_conn)

        r1 = InterventionRecord(
            intervention_key="key_a",
            conference_id="conf_001",
            participant="PRESIDENTA",
            text="Primera intervención.",
            pregunta_activa="",
            chunk_index=0,
        )
        r2 = InterventionRecord(
            intervention_key="key_b",
            conference_id="conf_001",
            participant="SECRETARIO",
            text="Segunda intervención.",
            pregunta_activa="",
            chunk_index=1,
        )

        merge_intervention(duck_conn, r1)
        merge_intervention(duck_conn, r2)

        count = duck_conn.execute("SELECT COUNT(*) FROM silver.interventions").fetchone()[0]
        assert count == 2

    def test_merge_conference_idempotent(
        self,
        duck_conn: duckdb.DuckDBPyConnection,
    ) -> None:
        ensure_silver_tables(duck_conn)

        record = ConferenceRecord(
            conference_id="conf_test_001",
            date="2024-10-01",
            title="Conferencia de prueba",
            url="https://example.com/test",
        )

        merge_conference(duck_conn, record)
        first = duck_conn.execute("SELECT COUNT(*) FROM silver.conferences").fetchone()[0]
        assert first == 1

        merge_conference(duck_conn, record)
        second = duck_conn.execute("SELECT COUNT(*) FROM silver.conferences").fetchone()[0]
        assert second == 1

        row = duck_conn.execute(
            "SELECT conference_id, date, title, url FROM silver.conferences"
        ).fetchone()
        assert row[0] == "conf_test_001"
        assert row[1] == "2024-10-01"
        assert row[2] == "Conferencia de prueba"
        assert row[3] == "https://example.com/test"


class TestGoldIdempotency:
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    @patch("lakehouse.pipeline.enrichment.embed_text")
    def test_on_conflict_do_nothing_in_sql(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
        sample_interventions: list[InterventionRecord],
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        first = enrich_interventions(
            interventions=sample_interventions,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert first["total"] == 2
        assert first["embedded"] == 2
        assert first["failed"] == 0

        insert_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "ON CONFLICT" in insert_sql.upper()

    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    @patch("lakehouse.pipeline.enrichment.embed_text")
    def test_same_chunk_key_skips_on_second_run(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        dup_record = InterventionRecord(
            intervention_key="dup_key_001",
            conference_id="conf_dup",
            participant="PRESIDENTA",
            text="Texto duplicado.",
            pregunta_activa="",
            chunk_index=0,
        )

        first = enrich_interventions(
            interventions=[dup_record],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert first["total"] == 1
        assert first["embedded"] == 1

        second = enrich_interventions(
            interventions=[dup_record],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert second["total"] == 1
        assert second["embedded"] == 1

    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    @patch("lakehouse.pipeline.enrichment.embed_text")
    def test_total_rows_same_after_second_run(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        records = [
            InterventionRecord(
                intervention_key=f"gold_key_{i}",
                conference_id="conf_gold",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto Gold {i}",
                pregunta_activa="",
                chunk_index=i,
            )
            for i in range(3)
        ]

        first = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert first["total"] == 3
        assert first["embedded"] == 3

        mock_cursor.reset_mock()

        second = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert second["total"] == 3
        assert second["embedded"] == 3
