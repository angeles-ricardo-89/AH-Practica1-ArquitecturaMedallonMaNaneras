import duckdb

from lakehouse.schemas.silver import DLQRejectRecord, InterventionRecord


def ensure_silver_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS silver")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver.interventions (
            intervention_key VARCHAR PRIMARY KEY,
            conference_id VARCHAR NOT NULL,
            participant VARCHAR NOT NULL,
            text VARCHAR NOT NULL,
            pregunta_activa VARCHAR DEFAULT '',
            chunk_index INTEGER NOT NULL,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver.conferences (
            conference_id VARCHAR PRIMARY KEY,
            date VARCHAR NOT NULL,
            url VARCHAR NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver.dlq (
            rejection_id INTEGER PRIMARY KEY,
            source_record_id VARCHAR NOT NULL,
            rejection_reason VARCHAR NOT NULL,
            raw_data VARCHAR NOT NULL,
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def merge_intervention(conn: duckdb.DuckDBPyConnection, record: InterventionRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO silver.interventions
            (intervention_key, conference_id, participant, text, pregunta_activa, chunk_index)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record.intervention_key,
            record.conference_id,
            record.participant,
            record.text,
            record.pregunta_activa,
            record.chunk_index,
        ),
    )


def insert_dlq_record(conn: duckdb.DuckDBPyConnection, record: DLQRejectRecord) -> None:
    conn.execute(
        """
        INSERT INTO silver.dlq (source_record_id, rejection_reason, raw_data)
        VALUES (?, ?, ?)
        """,
        (record.source_record_id, record.rejection_reason, record.raw_data),
    )
