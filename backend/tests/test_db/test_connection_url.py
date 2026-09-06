from __future__ import annotations

import pytest

from lakehouse.config import Settings
from lakehouse.db.connection import get_database_url, pg_conn_str_with_timeouts


def _prod_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "neon_database_url": "postgresql://user:pass@host-pooler.example.com/db",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestGetDatabaseUrl:
    def test_local_returns_local_url(self) -> None:
        settings = Settings(app_env="local", postgres_host="localhost", postgres_port=5433)
        url = get_database_url(settings)
        assert url.startswith("postgresql://mananeras:mananeras@localhost:5433/mananeras")

    def test_production_adds_sslmode_require(self) -> None:
        url = get_database_url(_prod_settings())
        assert "-pooler" in url
        assert "sslmode=require" in url

    def test_production_keeps_existing_sslmode(self) -> None:
        settings = _prod_settings(
            neon_database_url="postgresql://u:p@h-pooler.example.com/db?sslmode=require"
        )
        assert get_database_url(settings).count("sslmode=require") == 1

    def test_production_without_neon_url_fails_closed(self) -> None:
        with pytest.raises(RuntimeError):
            get_database_url(_prod_settings(neon_database_url=""))

    def test_production_rejects_non_pooled_endpoint(self) -> None:
        settings = _prod_settings(
            neon_database_url="postgresql://u:p@h.example.com/db",
        )
        with pytest.raises(ValueError):
            get_database_url(settings)


class TestPgTimeoutsWithPooler:
    def test_pooler_omits_statement_timeout_startup_option(self) -> None:
        conn = "postgresql://u:p@host-pooler.example.com/db?sslmode=require"
        out = pg_conn_str_with_timeouts(conn, connect_timeout=5, statement_timeout_ms=10000)
        assert "statement_timeout" not in out
        assert "connect_timeout=5" in out

    def test_non_pooled_adds_statement_timeout(self) -> None:
        conn = "postgresql://u:p@host.example.com/db"
        out = pg_conn_str_with_timeouts(conn, connect_timeout=5, statement_timeout_ms=10000)
        assert "statement_timeout" in out
        assert "connect_timeout=5" in out
