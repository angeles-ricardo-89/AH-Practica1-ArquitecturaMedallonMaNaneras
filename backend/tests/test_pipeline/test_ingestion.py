from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lakehouse.pipeline.ingestion import Ingestor
from lakehouse.pipeline.interrupt import interrupt_state


def _mock_response(html: str) -> MagicMock:
    response = MagicMock()
    response.text = html
    response.raise_for_status = MagicMock()
    return response


class TestIngestorRun:
    @pytest.mark.asyncio
    async def test_run_async_inserts_records(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1", "http://test.com/2"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=True,
            ),
        ):
            mock_get.return_value = _mock_response("<html>test</html>")

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=2,
            )
            result = await ingestor.run()

        assert result["html_count"] == 2
        assert result["records_inserted"] == 2
        assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_run_retries_then_succeeds(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch(
                "lakehouse.pipeline.ingestion.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=True,
            ),
        ):
            mock_get.side_effect = [
                httpx.ConnectError("down"),
                _mock_response("<html>ok</html>"),
            ]

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=1,
                max_retries=3,
            )
            result = await ingestor.run()

        assert result["records_inserted"] == 1
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_exhausts_retries(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch(
                "lakehouse.pipeline.ingestion.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=True,
            ),
        ):
            mock_get.side_effect = httpx.ConnectError("always down")

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=1,
                max_retries=2,
            )
            result = await ingestor.run()

        assert result["records_inserted"] == 0
        mock_sleep.assert_awaited()

    @pytest.mark.asyncio
    async def test_run_skips_duplicate_records(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=False,
            ),
        ):
            mock_get.return_value = _mock_response("<html>test</html>")

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=1,
            )
            result = await ingestor.run()

        assert result["records_inserted"] == 0

    @pytest.mark.asyncio
    async def test_run_dry_run_counts_without_db(self):
        with patch(
            "lakehouse.pipeline.ingestion.fetch_article_list",
            return_value=["http://test.com/1", "http://test.com/2"],
        ):
            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=2,
            )
            result = await ingestor.run(dry_run=True)

        assert result["html_count"] == 2
        assert result["records_inserted"] == 2


class TestIngestorInterrupt:
    @pytest.mark.asyncio
    async def test_worker_stops_taking_new_urls_on_interrupt(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1", "http://test.com/2"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=True,
            ),
            patch.object(interrupt_state, "requested", side_effect=[False, True]),
        ):
            mock_get.return_value = _mock_response("<html>test</html>")

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=2,
            )
            result = await ingestor.run()

        assert result["records_inserted"] == 1
        assert mock_get.call_count == 1
