from unittest.mock import patch

import pytest

from lakehouse.pipeline.ingestion import Ingestor


@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.duckdb")


class TestIngestor:
    @patch("lakehouse.pipeline.ingestion.fetch_article_list")
    @patch("lakehouse.pipeline.ingestion.fetch_article_html")
    @patch("lakehouse.pipeline.ingestion.compute_content_hash")
    def test_dry_run_does_not_write(self, mock_hash, mock_fetch_html, mock_fetch_list, temp_db):
        mock_fetch_list.return_value = ["https://example.com/a"]
        mock_fetch_html.return_value = "<html><body><main>Test</main></body></html>"
        mock_hash.return_value = "a" * 64

        ingestor = Ingestor(
            db_path=temp_db,
            source_archive_url="https://example.com",
        )
        result = ingestor.run(dry_run=True)

        assert result["html_count"] == 1
        assert result["records_inserted"] == 0

    @patch("lakehouse.pipeline.ingestion.fetch_article_list")
    @patch("lakehouse.pipeline.ingestion.fetch_article_html")
    @patch("lakehouse.pipeline.ingestion.compute_content_hash")
    def test_ingest_stores_records(self, mock_hash, mock_fetch_html, mock_fetch_list, temp_db):
        mock_fetch_list.return_value = [
            "https://example.com/a",
            "https://example.com/b",
        ]
        mock_fetch_html.return_value = "<html><body><main>Test</main></body></html>"
        mock_hash.side_effect = ["a" * 64, "b" * 64]

        ingestor = Ingestor(
            db_path=temp_db,
            source_archive_url="https://example.com",
        )
        result = ingestor.run(dry_run=False)

        assert result["html_count"] == 2
        assert result["records_inserted"] == 2

    @patch("lakehouse.pipeline.ingestion.fetch_article_list")
    @patch("lakehouse.pipeline.ingestion.fetch_article_html")
    @patch("lakehouse.pipeline.ingestion.compute_content_hash")
    def test_idempotent_second_run(self, mock_hash, mock_fetch_html, mock_fetch_list, temp_db):
        mock_fetch_list.return_value = ["https://example.com/a"]
        mock_fetch_html.return_value = "<html><body><main>Test</main></body></html>"
        mock_hash.return_value = "a" * 64

        ingestor = Ingestor(
            db_path=temp_db,
            source_archive_url="https://example.com",
        )
        r1 = ingestor.run(dry_run=False)
        r2 = ingestor.run(dry_run=False)

        assert r1["records_inserted"] == 1
        assert r2["records_inserted"] == 0
