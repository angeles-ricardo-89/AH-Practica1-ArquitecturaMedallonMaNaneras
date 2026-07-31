from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from lakehouse.cli import app

runner = CliRunner()


class TestPipelineIngest:
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 0})
        result = runner.invoke(app, ["pipeline", "ingest", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, max_articles=None, clean=False)

    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None, clean=False)

    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_clean(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None, clean=True)


class TestPipelineParse:
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None, clean=False)

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=False)

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_with_date(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--date", "2024-10-01"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date="2024-10-01", clean=False
        )

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_clean(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=True)


class TestPipelineEnrich:
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None, clean=False)

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=False)

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_clean(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=True)


class TestEvaluateRagCommand:
    @patch("lakehouse.cli.evaluate_rag_fn")
    def test_evaluate_rag_success(self, mock_eval):
        mock_eval.return_value = {
            "status": "completed",
            "total": 3,
            "avg_fidelity": 95.0,
            "avg_relevance": 90.0,
        }
        result = runner.invoke(app, ["evaluate-rag"])
        assert result.exit_code == 0
        assert "RAG Evaluation: 3 preguntas" in result.output
        assert "fidelidad=95.0%" in result.output
        assert "relevancia=90.0%" in result.output

    @patch("lakehouse.cli.evaluate_rag_fn")
    def test_evaluate_rag_error(self, mock_eval):
        mock_eval.return_value = {
            "status": "error",
            "message": "Golden dataset not found",
        }
        result = runner.invoke(app, ["evaluate-rag"])
        assert result.exit_code == 1
        assert "RAG Evaluation failed: Golden dataset not found" in result.output
