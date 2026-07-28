from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.enrich_service import EnrichService
from lakehouse.schemas.silver import InterventionRecord


class TestEnrichService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = EnrichService(
            settings=settings, duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        result = service.run(dry_run=True)
        assert result["total"] == 0

    def test_run_no_dry_run_calls_enrich(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("k1", "c1", "P", "t", "", 0, "https://example.com"),
        ]
        service = EnrichService(
            settings=settings, duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables") as mock_ensure,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(dry_run=False)
        assert result["embedded"] == 1
        mock_ensure.assert_called_once()
        mock_enrich.assert_called_once()
