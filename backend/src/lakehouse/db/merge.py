import duckdb

from lakehouse.schemas.silver import ConferenceRecord, DLQRejectRecord, InterventionRecord


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
            url VARCHAR DEFAULT '',
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver.conferences (
            conference_id VARCHAR PRIMARY KEY,
            date VARCHAR NOT NULL,
            title VARCHAR DEFAULT '',
            url VARCHAR NOT NULL
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS silver.dlq_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver.dlq (
            rejection_id BIGINT PRIMARY KEY DEFAULT nextval('silver.dlq_seq'),
            source_record_id VARCHAR NOT NULL,
            rejection_reason VARCHAR NOT NULL,
            raw_data VARCHAR NOT NULL,
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def drop_silver_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS silver.interventions")
    conn.execute("DROP TABLE IF EXISTS silver.conferences")
    conn.execute("DROP TABLE IF EXISTS silver.dlq")


def merge_intervention(conn: duckdb.DuckDBPyConnection, record: InterventionRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO silver.interventions
            (intervention_key, conference_id, participant, text, pregunta_activa, chunk_index, url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.intervention_key,
            record.conference_id,
            record.participant,
            record.text,
            record.pregunta_activa,
            record.chunk_index,
            record.url,
        ),
    )


def merge_conference(conn: duckdb.DuckDBPyConnection, record: ConferenceRecord) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO silver.conferences
            (conference_id, date, title, url)
        VALUES (?, ?, ?, ?)
        """,
        (record.conference_id, record.date, record.title, record.url),
    )


def insert_dlq_record(conn: duckdb.DuckDBPyConnection, record: DLQRejectRecord) -> None:
    conn.execute(
        """
        INSERT INTO silver.dlq (source_record_id, rejection_reason, raw_data)
        VALUES (?, ?, ?)
        """,
        (record.source_record_id, record.rejection_reason, record.raw_data),
    )
