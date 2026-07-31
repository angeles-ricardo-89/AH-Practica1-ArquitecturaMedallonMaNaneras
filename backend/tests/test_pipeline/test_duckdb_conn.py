import pytest

from lakehouse.db.duckdb_conn import (
    drop_bronze_tables,
    ensure_bronze_table,
    get_connection,
    insert_bronze_record,
)


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.duckdb")


class TestDuckdbConn:
    def test_get_connection(self, tmp_db):
        conn = get_connection(tmp_db)
        assert conn is not None
        conn.close()

    def test_ensure_bronze_table_creates_schema(self, tmp_db):
        conn = get_connection(tmp_db)
        ensure_bronze_table(conn)
        result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'bronze'"
        ).fetchall()
        tables = [r[0] for r in result]
        assert "raw_html" in tables
        conn.close()

    def test_insert_and_count(self, tmp_db):
        conn = get_connection(tmp_db)
        ensure_bronze_table(conn)
        insert_bronze_record(
            conn,
            ingestion_run_id="run_001",
            source_url="https://example.com",
            raw_html="<html><body><main>Content</main></body></html>",
            content_hash="a" * 64,
        )
        count = conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchone()[0]
        assert count == 1
        conn.close()

    def test_idempotent_insert(self, tmp_db):
        conn = get_connection(tmp_db)
        ensure_bronze_table(conn)
        for _ in range(2):
            insert_bronze_record(
                conn,
                ingestion_run_id="run_001",
                source_url="https://example.com",
                raw_html="<html><body><main>Content</main></body></html>",
                content_hash="a" * 64,
            )
        count = conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchone()[0]
        assert count == 1
        conn.close()

    def test_drop_bronze_tables_removes_table(self, tmp_db):
        conn = get_connection(tmp_db)
        ensure_bronze_table(conn)
        insert_bronze_record(
            conn,
            ingestion_run_id="run_001",
            source_url="https://example.com",
            raw_html="<html>",
            content_hash="a" * 64,
        )
        drop_bronze_tables(conn)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'bronze'"
            ).fetchall()
        ]
        assert tables == []
        conn.close()
