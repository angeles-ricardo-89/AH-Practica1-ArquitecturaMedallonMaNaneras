from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.ingest_service import IngestService


class TestIngestService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        service = IngestService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert isinstance(result, dict)
        assert "html_count" in result
        assert "records_inserted" in result

    def test_run_no_dry_run_ensures_table_and_inserts(self):
        settings = Settings()
        conn = MagicMock()
        service = IngestService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.ingest_service.ensure_bronze_table") as mock_ensure,
            patch("lakehouse.services.ingest_service.Ingestor") as mock_ingestor_cls,
        ):
            mock_ingestor = mock_ingestor_cls.return_value
            mock_ingestor.run.return_value = {"html_count": 3, "records_inserted": 3}
            result = service.run(dry_run=False)
        assert result["records_inserted"] == 3
        mock_ensure.assert_called_once_with(conn)
        mock_ingestor.run.assert_called_once_with(dry_run=False)
