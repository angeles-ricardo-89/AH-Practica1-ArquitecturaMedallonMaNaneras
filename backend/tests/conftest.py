from __future__ import annotations

import os

import psycopg
import pytest

from lakehouse.api.deps import CurrentUser, get_current_user
from lakehouse.db.auth_memory import ensure_auth_memory_tables
from lakehouse.db.rate_limit import ensure_rate_limit_tables
from lakehouse.main import app
from lakehouse.services.demo_users import ensure_demo_users

TEST_DB = "mananeras_test"
TEST_USERS = [("testuser1", "test-password-1"), ("testuser2", "test-password-2")]


@pytest.fixture
def pg_conn_str() -> str:
    """Cadena de conexion a la base de datos de pruebas."""
    return f"postgresql://mananeras:mananeras@localhost:5433/{TEST_DB}"


@pytest.fixture
def real_auth():
    """Desactiva temporalmente el override de get_current_user para probar auth real."""
    saved = app.dependency_overrides.pop(get_current_user, None)
    yield
    if saved is not None:
        app.dependency_overrides[get_current_user] = saved


@pytest.fixture
def demo_users(pg_conn_str: str):
    ensure_demo_users(pg_conn_str, TEST_USERS)
    yield
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM app_user WHERE username IN ('testuser1', 'testuser2')")
        conn.commit()


def pytest_configure(config) -> None:
    """Crea la base de datos de pruebas y la activa para todos los tests."""
    os.environ["POSTGRES_DB"] = TEST_DB
    os.environ["LOGIN_RATE_LIMIT"] = "10000"
    os.environ["CHAT_RATE_LIMIT"] = "10000"
    os.environ["DAILY_RATE_LIMIT"] = "10000"

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
        ensure_auth_memory_tables(test_conn)
        ensure_rate_limit_tables(test_conn)
        with psycopg.connect(test_conn) as conn:
            conn.autocommit = True
            conn.execute("TRUNCATE rate_limit_counter")
    except psycopg.Error as e:
        raise SystemExit(f"No se pudo inicializar la base de datos de pruebas: {e}") from None

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1, username="test", role="demo", iat=0
    )
