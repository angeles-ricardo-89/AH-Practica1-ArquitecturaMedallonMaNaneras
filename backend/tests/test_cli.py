import hashlib
from unittest.mock import AsyncMock, patch

import psycopg
import pytest
from typer.testing import CliRunner

import lakehouse.config
from lakehouse.cli import _write_pipeline_run, app
from lakehouse.config import Settings
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.pipeline.interrupt import interrupt_state

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
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_no_dry_run(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None, clean=False)
        mock_ensure.assert_called_once()
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_clean(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None, clean=True)
        assert mock_write.call_count == 2


class TestPipelineParse:
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=True, conference_date=None, clean=False, workers=1
        )

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_parse_no_dry_run(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=False, workers=1
        )
        mock_ensure.assert_called_once()
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_parse_with_date(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--date", "2024-10-01"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date="2024-10-01", clean=False, workers=1
        )
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_parse_clean(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=True, workers=1
        )
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_parse_with_workers(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 5, "dlq": 1}
        result = runner.invoke(app, ["pipeline", "parse", "--workers", "4"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=False, workers=4
        )
        assert mock_write.call_count == 2


class TestPipelineEnrich:
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=True, conference_date=None, clean=False, workers=1
        )

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_no_dry_run(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=False, workers=1
        )
        mock_ensure.assert_called_once()
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_clean(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich", "--clean"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=True, workers=1
        )
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_with_workers(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich", "--workers", "4"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False, conference_date=None, clean=False, workers=4
        )
        assert mock_write.call_count == 2


class TestWritePipelineRun:
    @pytest.fixture
    def conn_str(self, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        settings = Settings()
        return (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )

    def _clean_bronze_runs(self, conn_str: str) -> None:
        with psycopg.connect(conn_str) as conn:
            conn.execute("DELETE FROM observability.pipeline_runs WHERE capa = 'bronze'")
            conn.commit()

    def test_running_to_ok_updates_same_row(self, conn_str: str) -> None:
        ensure_observability_tables(conn_str)
        self._clean_bronze_runs(conn_str)
        try:
            started_at = "2026-08-01T10:00:00Z"
            expected_run_id = hashlib.sha256(f"bronze:{started_at}".encode()).hexdigest()
            _write_pipeline_run(conn_str, "bronze", "running", started_at)
            _write_pipeline_run(
                conn_str,
                "bronze",
                "ok",
                started_at,
                records_in=150,
                records_out=150,
            )
            with psycopg.connect(conn_str) as conn:
                rows = conn.execute(
                    """SELECT status, records_in, records_out, error_message, finished_at
                    FROM observability.pipeline_runs WHERE run_id = %s""",
                    (expected_run_id,),
                ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "ok"
            assert rows[0][1] == 150
            assert rows[0][2] == 150
            assert rows[0][3] is None
            assert rows[0][4] is not None
        finally:
            self._clean_bronze_runs(conn_str)

    def test_repeated_upsert_does_not_duplicate(self, conn_str: str) -> None:
        ensure_observability_tables(conn_str)
        self._clean_bronze_runs(conn_str)
        try:
            started_at = "2026-08-01T10:30:00Z"
            expected_run_id = hashlib.sha256(f"bronze:{started_at}".encode()).hexdigest()
            _write_pipeline_run(
                conn_str,
                "bronze",
                "ok",
                started_at,
                records_in=150,
                records_out=150,
            )
            _write_pipeline_run(
                conn_str,
                "bronze",
                "ok",
                started_at,
                records_in=150,
                records_out=150,
            )
            with psycopg.connect(conn_str) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM observability.pipeline_runs WHERE run_id = %s",
                    (expected_run_id,),
                ).fetchone()[0]
            assert count == 1
        finally:
            self._clean_bronze_runs(conn_str)

    def test_write_error_record_sets_message(self, conn_str: str) -> None:
        ensure_observability_tables(conn_str)
        self._clean_bronze_runs(conn_str)
        try:
            started_at = "2026-08-01T11:00:00Z"
            expected_run_id = hashlib.sha256(f"bronze:{started_at}".encode()).hexdigest()
            _write_pipeline_run(
                conn_str,
                "bronze",
                "error",
                started_at,
                error_message="boom",
            )
            with psycopg.connect(conn_str) as conn:
                row = conn.execute(
                    "SELECT status, error_message FROM observability.pipeline_runs WHERE run_id = %s",
                    (expected_run_id,),
                ).fetchone()
            assert row[0] == "error"
            assert row[1] == "boom"
        finally:
            self._clean_bronze_runs(conn_str)

    def test_does_not_raise_on_db_error(self) -> None:
        _write_pipeline_run(
            "postgresql://invalid:invalid@localhost:1/invalid",
            "bronze",
            "ok",
            "2026-08-01T12:00:00Z",
        )


class TestPipelineRunTracking:
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_writes_running_then_ok(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        assert mock_write.call_count == 2
        running, ok = mock_write.call_args_list
        assert running.args[1] == "bronze"
        assert running.args[2] == "running"
        assert ok.args[1] == "bronze"
        assert ok.args[2] == "ok"
        assert ok.kwargs["records_in"] == 5
        assert ok.kwargs["records_out"] == 5

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_writes_error_on_failure(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(side_effect=RuntimeError("boom"))
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code != 0
        assert mock_write.call_count == 2
        running, error = mock_write.call_args_list
        assert running.args[2] == "running"
        assert error.args[2] == "error"
        assert error.kwargs["error_message"] == "boom"

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_writes_running_then_ok(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 10, "dlq": 2}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        assert mock_write.call_count == 2
        running, ok = mock_write.call_args_list
        assert running.args[1] == "silver"
        assert running.args[2] == "running"
        assert ok.args[1] == "silver"
        assert ok.args[2] == "ok"
        assert ok.kwargs["records_in"] == 10
        assert ok.kwargs["records_out"] == 10
        assert ok.kwargs["dlq_count"] == 2

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_continues_when_observability_setup_fails(
        self, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_ensure.side_effect = RuntimeError("pg down")
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 10, "dlq": 2}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        assert "Parsing completado" in result.output
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_writes_error_on_failure(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.side_effect = RuntimeError("boom")
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code != 0
        assert mock_write.call_count == 2
        running, error = mock_write.call_args_list
        assert running.args[2] == "running"
        assert error.args[2] == "error"
        assert error.kwargs["error_message"] == "boom"

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_writes_running_then_ok(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 7, "failed": 1, "total": 8}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        assert mock_write.call_count == 2
        running, ok = mock_write.call_args_list
        assert running.args[1] == "gold"
        assert running.args[2] == "running"
        assert ok.args[1] == "gold"
        assert ok.args[2] == "ok"
        assert ok.kwargs["records_in"] == 8
        assert ok.kwargs["records_out"] == 7

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_continues_when_observability_setup_fails(
        self, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_ensure.side_effect = RuntimeError("pg down")
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 7, "failed": 1, "total": 8}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        assert "Enriquecimiento completado" in result.output
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_writes_error_on_failure(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.side_effect = RuntimeError("boom")
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code != 0
        assert mock_write.call_count == 2
        running, error = mock_write.call_args_list
        assert running.args[2] == "running"
        assert error.args[2] == "error"
        assert error.kwargs["error_message"] == "boom"

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_continues_when_observability_setup_fails(
        self, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_ensure.side_effect = RuntimeError("pg down")
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 5})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        assert "Ingesta completada" in result.output
        assert mock_write.call_count == 2

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_dry_run_skips_tracking(self, mock_conn, mock_svc_cls, mock_write, mock_ensure):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 0})
        result = runner.invoke(app, ["pipeline", "ingest", "--dry-run"])
        assert result.exit_code == 0
        mock_write.assert_not_called()
        mock_ensure.assert_not_called()

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_ingest_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 3})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 3
        assert interrupted.kwargs["records_out"] == 3

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_parse_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 4, "dlq": 1}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 4
        assert interrupted.kwargs["records_out"] == 4
        assert interrupted.kwargs["dlq_count"] == 1

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_enrich_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 2, "failed": 1, "total": 3}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 3
        assert interrupted.kwargs["records_out"] == 2


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
