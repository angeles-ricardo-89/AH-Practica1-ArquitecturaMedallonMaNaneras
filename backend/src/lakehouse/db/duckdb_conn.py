import duckdb


def get_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path)


def ensure_bronze_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bronze.raw_html (
            ingestion_run_id VARCHAR NOT NULL,
            source_url VARCHAR NOT NULL,
            raw_html VARCHAR NOT NULL,
            content_hash VARCHAR NOT NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (content_hash)
        )
    """)


def insert_bronze_record(
    conn: duckdb.DuckDBPyConnection,
    ingestion_run_id: str,
    source_url: str,
    raw_html: str,
    content_hash: str,
) -> bool:
    before = conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchall()[0][0]
    conn.execute(
        """
        INSERT OR IGNORE INTO bronze.raw_html (ingestion_run_id, source_url, raw_html, content_hash)
        VALUES (?, ?, ?, ?)
    """,
        (ingestion_run_id, source_url, raw_html, content_hash),
    )
    after = conn.execute("SELECT COUNT(*) FROM bronze.raw_html").fetchall()[0][0]
    return after > before
