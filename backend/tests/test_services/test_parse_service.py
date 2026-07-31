from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.schemas.silver import DLQRejectRecord, InterventionRecord
from lakehouse.services.parse_service import ParseService


class TestParseService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert result == {"interventions": 0, "dlq": 0}

    def test_run_with_data_returns_counts(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse:
            mock_parse.return_value = [
                InterventionRecord(
                    intervention_key="k_000_abc",
                    conference_id="cid",
                    participant="P",
                    text="t",
                    chunk_index=0,
                    url="u",
                ),
            ]
            result = service.run(dry_run=True)
        assert result["interventions"] == 1
        assert result["dlq"] == 0

    def test_unknown_date_sends_to_dlq(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/no-date", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.parse_conference_date") as mock_date:
            mock_date.return_value = None
            result = service.run(dry_run=True)
        assert result["interventions"] == 0
        assert result["dlq"] == 1

    def test_run_no_dry_run_calls_merge(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse,
            patch("lakehouse.services.parse_service.build_conference_record") as mock_build,
            patch("lakehouse.services.parse_service.merge_conference") as mock_merge_conf,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_merge_int,
            patch("lakehouse.services.parse_service.ensure_silver_tables") as mock_ensure,
        ):
            mock_parse.return_value = [
                InterventionRecord(
                    intervention_key="k_000_abc",
                    conference_id="cid",
                    participant="P",
                    text="t",
                    chunk_index=0,
                    url="u",
                ),
            ]
            mock_build.return_value = MagicMock()
            result = service.run(dry_run=False)
        assert result["interventions"] == 1
        mock_ensure.assert_called_once()
        mock_merge_conf.assert_called_once()
        mock_merge_int.assert_called_once()

    def test_unknown_date_non_dry_run_inserts_dlq(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/no-date", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch(
                "lakehouse.services.parse_service.parse_conference_date",
                return_value=None,
            ),
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
        ):
            result = service.run(dry_run=False)
        assert result["dlq"] == 1
        mock_dlq.assert_called_once()

    def test_run_dry_run_counts_dlq_record(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse:
            mock_parse.return_value = [
                DLQRejectRecord(
                    source_record_id="x",
                    rejection_reason="bad_format",
                    raw_data="y",
                ),
            ]
            result = service.run(dry_run=True)
        assert result["interventions"] == 0
        assert result["dlq"] == 1

    def test_run_non_dry_run_inserts_dlq_record(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse,
            patch("lakehouse.services.parse_service.build_conference_record") as mock_build,
            patch("lakehouse.services.parse_service.merge_conference"),
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
        ):
            mock_parse.return_value = [
                DLQRejectRecord(
                    source_record_id="x",
                    rejection_reason="bad_format",
                    raw_data="y",
                ),
            ]
            mock_build.return_value = MagicMock()
            result = service.run(dry_run=False)
        assert result["interventions"] == 0
        assert result["dlq"] == 1
        mock_dlq.assert_called_once()


class TestParseServiceClean:
    def test_run_clean_drops_silver_tables(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.drop_silver_tables") as mock_drop:
            result = service.run(clean=True)
        assert result == {"interventions": 0, "dlq": 0}
        mock_drop.assert_called_once()

    def test_run_clean_ignored_in_dry_run(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.drop_silver_tables") as mock_drop:
            service.run(clean=True, dry_run=True)
        mock_drop.assert_not_called()
