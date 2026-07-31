from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lakehouse.config import Settings
from lakehouse.services.ingest_service import IngestService


@pytest.mark.asyncio
async def test_ingest_service_run_async():
    # Mocking Ingestor to avoid full pipeline run
    with patch("lakehouse.services.ingest_service.Ingestor", autospec=True) as mock_ingestor_cls:
        mock_ingestor_inst = mock_ingestor_cls.return_value
        mock_ingestor_inst.run = AsyncMock(return_value={"status": "ok"})

        settings = Settings()
        # Use a MagicMock for the connection to avoid AttributeError
        mock_conn = MagicMock()
        service = IngestService(settings, mock_conn)

        result = await service.run()

        assert result["status"] == "ok"
        mock_ingestor_inst.run.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_service_clean_drops_tables():
    with (
        patch("lakehouse.services.ingest_service.Ingestor", autospec=True) as mock_ingestor_cls,
        patch("lakehouse.services.ingest_service.drop_bronze_tables") as mock_drop,
    ):
        mock_ingestor_inst = mock_ingestor_cls.return_value
        mock_ingestor_inst.run = AsyncMock(return_value={"status": "ok"})
        service = IngestService(Settings(), MagicMock())

        result = await service.run(clean=True)

        assert result["status"] == "ok"
        mock_drop.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_service_clean_ignored_in_dry_run():
    with (
        patch("lakehouse.services.ingest_service.Ingestor", autospec=True) as mock_ingestor_cls,
        patch("lakehouse.services.ingest_service.drop_bronze_tables") as mock_drop,
    ):
        mock_ingestor_inst = mock_ingestor_cls.return_value
        mock_ingestor_inst.run = AsyncMock(return_value={"status": "ok"})
        service = IngestService(Settings(), MagicMock())

        result = await service.run(clean=True, dry_run=True)

        assert result["status"] == "ok"
        mock_drop.assert_not_called()
