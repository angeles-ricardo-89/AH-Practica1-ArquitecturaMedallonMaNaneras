from unittest.mock import patch

from typer.testing import CliRunner

from lakehouse.cli import app

runner = CliRunner()


class TestCliHelp:
    def test_help_shows_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "pipeline" in result.stdout
        assert "evaluate-rag" in result.stdout

    def test_pipeline_help_shows_subcommands(self):
        result = runner.invoke(app, ["pipeline", "--help"])
        assert result.exit_code == 0
        assert "ingest" in result.stdout
        assert "parse" in result.stdout
        assert "enrich" in result.stdout


class TestPipelineIngest:
    @patch("lakehouse.cli.Ingestor")
    def test_ingest_dry_run(self, mock_ingestor_cls):
        mock_ingestor = mock_ingestor_cls.return_value
        mock_ingestor.run.return_value = {
            "ingestion_run_id": "run_test",
            "html_count": 5,
            "records_inserted": 0,
        }
        result = runner.invoke(app, ["pipeline", "ingest", "--dry-run"])
        assert result.exit_code == 0
        mock_ingestor.run.assert_called_once_with(dry_run=True)

    @patch("lakehouse.cli.Ingestor")
    def test_ingest_no_dry_run(self, mock_ingestor_cls):
        mock_ingestor = mock_ingestor_cls.return_value
        mock_ingestor.run.return_value = {
            "ingestion_run_id": "run_test",
            "html_count": 5,
            "records_inserted": 5,
        }
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        mock_ingestor.run.assert_called_once_with(dry_run=False)


class TestPipelineParse:
    @patch("lakehouse.cli.get_connection")
    def test_parse_dry_run(self, mock_conn):
        mock_conn.return_value.execute.return_value.fetchall.return_value = []
        result = runner.invoke(app, ["pipeline", "parse", "--dry-run"])
        assert result.exit_code == 0

    @patch("lakehouse.cli.get_connection")
    def test_parse_no_dry_run(self, mock_conn):
        mock_conn.return_value.execute.return_value.fetchall.return_value = []
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0


class TestPipelineEnrich:
    @patch("lakehouse.cli.get_connection")
    def test_enrich_dry_run(self, mock_conn):
        mock_conn.return_value.execute.return_value.fetchall.return_value = []
        result = runner.invoke(app, ["pipeline", "enrich", "--dry-run"])
        assert result.exit_code == 0

    @patch("lakehouse.cli.get_connection")
    @patch("lakehouse.cli.ensure_gold_tables")
    @patch("lakehouse.cli.enrich_interventions")
    def test_enrich_no_dry_run(self, mock_enrich_fn, mock_ensure, mock_conn):
        mock_conn.return_value.execute.return_value.fetchall.return_value = [
            ("key1", "conf1", "PARTICIPANTE", "texto", "pregunta", 0)
        ]
        mock_enrich_fn.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0


class TestEvaluateRag:
    @patch("lakehouse.cli.evaluate_rag_fn")
    def test_evaluate_rag_command(self, mock_fn):
        mock_fn.return_value = {
            "status": "completed",
            "total": 50,
            "avg_fidelity": 95.0,
            "avg_relevance": 90.0,
        }
        result = runner.invoke(app, ["evaluate-rag"])
        assert result.exit_code == 0

    @patch("lakehouse.cli.evaluate_rag_fn")
    def test_evaluate_rag_shows_message(self, mock_fn):
        mock_fn.return_value = {
            "status": "completed",
            "total": 50,
            "avg_fidelity": 95.0,
            "avg_relevance": 90.0,
        }
        result = runner.invoke(app, ["evaluate-rag"])
        assert "RAG" in result.stdout or "evaluate" in result.stdout.lower()
