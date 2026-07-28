from unittest.mock import patch

from typer.testing import CliRunner

from lakehouse.cli import app

runner = CliRunner()


class TestPipelineIngest:
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"html_count": 5, "records_inserted": 0}
        result = runner.invoke(app, ["pipeline", "ingest", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, max_articles=None)

    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"html_count": 5, "records_inserted": 5}
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None)


class TestPipelineParse:
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None)

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None)

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_with_date(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--date", "2024-10-01"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date="2024-10-01")


class TestPipelineEnrich:
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None)

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None)
