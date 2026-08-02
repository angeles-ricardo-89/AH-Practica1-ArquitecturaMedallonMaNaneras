from __future__ import annotations

import os

import psycopg

TEST_DB = "mananeras_test"


def pytest_configure(config) -> None:  # noqa: ARG001
    """Crea la base de datos de pruebas y la activa para todos los tests."""
    os.environ["POSTGRES_DB"] = TEST_DB

    admin_conn = "postgresql://mananeras:mananeras@localhost:5433/postgres"
    try:
        with psycopg.connect(admin_conn) as conn:
            conn.autocommit = True
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.errors.DuplicateDatabase:
        pass
    except psycopg.Error:
        raise SystemExit(
            "No se pudo crear la base de datos de pruebas mananeras_test. "
            "Asegurate de que PostgreSQL este corriendo (docker compose up -d postgres)."
        ) from None

    test_conn = f"postgresql://mananeras:mananeras@localhost:5433/{TEST_DB}"
    try:
        with psycopg.connect(test_conn) as conn:
            conn.autocommit = True
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("CREATE SCHEMA IF NOT EXISTS gold")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gold.rag_corpus (
                    chunk_key VARCHAR PRIMARY KEY,
                    conference_id VARCHAR,
                    conference_date DATE,
                    participant VARCHAR,
                    chunk_text TEXT,
                    payload TEXT,
                    url VARCHAR,
                    embedding vector(768),
                    ingested_at TIMESTAMPTZ DEFAULT now(),
                    pregunta_activa VARCHAR DEFAULT '',
                    embedding_3d DOUBLE PRECISION[3]
                )
            """)
    except psycopg.Error as e:
        raise SystemExit(
            f"No se pudo inicializar la base de datos de pruebas: {e}"
        ) from None
