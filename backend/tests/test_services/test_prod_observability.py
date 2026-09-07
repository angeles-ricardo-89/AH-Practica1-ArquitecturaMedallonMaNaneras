from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lakehouse.config import Settings
from lakehouse.services.prod_observability import sync_production_observability

NEON_URL = "postgresql://u:p@ep-demo-pooler.us-east-1.aws.neon.tech/db?sslmode=require"


class TestSyncProductionObservability:
    def test_raises_without_neon_url(self) -> None:
        with pytest.raises(RuntimeError, match="NEON_DATABASE_URL"):
            sync_production_observability(Settings(app_env="local", neon_database_url=""))

    def test_copies_rows_with_upsert(self, monkeypatch) -> None:
        upserts: list[tuple] = []

        source_conn = MagicMock()
        target_conn = MagicMock()
        cursor = MagicMock()
        target_conn.cursor.return_value = cursor

        class _ConnMgr:
            def __init__(self, conn: MagicMock) -> None:
                self._conn = conn

            def __enter__(self) -> MagicMock:
                return self._conn

            def __exit__(self, *exc: object) -> None:
                return None

        source_conn.execute.return_value.fetchall.return_value = [
            ("r1", "gold", "ok", None, None, 10, 10, 0, None),
            ("r2", "silver", "ok", None, None, 20, 20, 0, None),
        ]

        monkeypatch.setattr(
            "lakehouse.services.prod_observability.psycopg",
            MagicMock(
                connect=lambda conn_str: (
                    _ConnMgr(source_conn)
                    if conn_str.startswith("postgresql://") and "-pooler" not in conn_str
                    else _ConnMgr(target_conn)
                )
            ),
        )
        monkeypatch.setattr(
            "lakehouse.services.prod_observability.ensure_observability_tables", lambda _c: None
        )

        def capture_exec(sql: str, params: tuple) -> None:
            upserts.append((sql, params))

        cursor.execute.side_effect = capture_exec

        result = sync_production_observability(
            Settings(app_env="local", neon_database_url=NEON_URL)
        )

        assert result == {"copied": 2}
        assert len(upserts) == 2
        assert "ON CONFLICT (run_id) DO UPDATE" in upserts[0][0]
        assert upserts[0][1][0] == "r1"
        target_conn.commit.assert_called_once()
