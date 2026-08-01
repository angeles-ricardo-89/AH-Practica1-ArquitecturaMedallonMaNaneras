from concurrent.futures import Future
from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.parse_service import ParseService, _parse_one_row


class TestParseService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert result == {"interventions": 0, "dlq": 0}

    def test_run_sequential_counts_correctly(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(3, 1)),
        ):
            result = service.run(dry_run=False)
        assert result["interventions"] == 3
        assert result["dlq"] == 1

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


class TestParseServiceWorkers:
    def test_run_dispatches_to_sequential_when_workers_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(0, 0)) as mock_seq,
            patch.object(service, "_run_parallel") as mock_par,
        ):
            result = service.run(dry_run=False, workers=1)
        assert result == {"interventions": 0, "dlq": 0}
        mock_seq.assert_called_once()
        mock_par.assert_not_called()

    def test_run_dispatches_to_parallel_when_workers_gt_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.ProcessPoolExecutor"),
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential") as mock_seq,
            patch.object(service, "_run_parallel", return_value=(0, 0)) as mock_par,
        ):
            result = service.run(dry_run=False, workers=4)
        assert result == {"interventions": 0, "dlq": 0}
        mock_par.assert_called_once()
        mock_seq.assert_not_called()

    def test_run_workers_0_clamped_to_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(0, 0)) as mock_seq,
            patch.object(service, "_run_parallel") as mock_par,
        ):
            result = service.run(dry_run=False, workers=0)
        assert result == {"interventions": 0, "dlq": 0}
        mock_seq.assert_called_once()
        mock_par.assert_not_called()

    def test_run_workers_dry_run_no_write_conn(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection") as mock_get_conn,
            patch.object(service, "_run_sequential", return_value=(1, 0)),
        ):
            result = service.run(dry_run=True, workers=1)
        assert result == {"interventions": 1, "dlq": 0}
        mock_get_conn.assert_not_called()


class _FakePool:
    def __init__(self, futures: list[Future]) -> None:
        self._futures = list(futures)
        self.submit_calls: list[tuple[object, tuple]] = []

    def submit(self, fn: object, *args: object) -> Future:
        self.submit_calls.append((fn, args))
        return self._futures.pop(0)


class TestRunSequential:
    @staticmethod
    def _service() -> ParseService:
        return ParseService(settings=Settings(), duckdb_conn=MagicMock())

    def test_writes_conference_and_interventions(self):
        service = self._service()
        conference = MagicMock()
        intervention = MagicMock()
        rows = [("https://example.com/a", "<html></html>")]
        reporter = MagicMock()
        with (
            patch(
                "lakehouse.services.parse_service._parse_one_row",
                return_value=(conference, [intervention], []),
            ) as mock_parse,
            patch("lakehouse.services.parse_service.merge_conference") as mock_mc,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_mi,
        ):
            total_int, total_dlq = service._run_sequential(
                rows=rows,
                write_conn=MagicMock(),
                conference_date=None,
                reporter=reporter,
            )
        assert total_int == 1
        assert total_dlq == 0
        mock_parse.assert_called_once_with("https://example.com/a", "<html></html>", None)
        mock_mc.assert_called_once()
        mock_mi.assert_called_once()
        reporter.tick.assert_called_once()

    def test_writes_dlq_and_logs_warning(self):
        service = self._service()
        dlq = MagicMock()
        rows = [("https://example.com/a", "<html></html>")]
        with (
            patch(
                "lakehouse.services.parse_service._parse_one_row",
                return_value=(None, [], [dlq]),
            ),
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch.object(service, "_logger") as mock_logger,
        ):
            total_int, total_dlq = service._run_sequential(
                rows=rows,
                write_conn=MagicMock(),
                conference_date=None,
                reporter=MagicMock(),
            )
        assert total_int == 0
        assert total_dlq == 1
        mock_dlq.assert_called_once()
        mock_logger.warning.assert_called_once()

    def test_dry_run_skips_writes_and_warnings(self):
        service = self._service()
        conference = MagicMock()
        intervention = MagicMock()
        dlq = MagicMock()
        rows = [("https://example.com/a", "<html></html>")]
        with (
            patch(
                "lakehouse.services.parse_service._parse_one_row",
                return_value=(conference, [intervention], [dlq]),
            ),
            patch("lakehouse.services.parse_service.merge_conference") as mock_mc,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_mi,
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch.object(service, "_logger") as mock_logger,
        ):
            total_int, total_dlq = service._run_sequential(
                rows=rows,
                write_conn=None,
                conference_date=None,
                reporter=MagicMock(),
            )
        assert total_int == 1
        assert total_dlq == 1
        mock_mc.assert_not_called()
        mock_mi.assert_not_called()
        mock_dlq.assert_not_called()
        mock_logger.warning.assert_not_called()


class TestRunParallel:
    @staticmethod
    def _service() -> ParseService:
        return ParseService(settings=Settings(), duckdb_conn=MagicMock())

    def test_writes_conference_interventions_and_dlq(self):
        service = self._service()
        conference = MagicMock()
        intervention = MagicMock()
        dlq = MagicMock()
        future_ok = Future()
        future_ok.set_result((conference, [intervention], [dlq]))
        pool = _FakePool([future_ok])
        with (
            patch("lakehouse.services.parse_service.merge_conference") as mock_mc,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_mi,
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch.object(service, "_logger") as mock_logger,
        ):
            total_int, total_dlq = service._run_parallel(
                rows=[("https://example.com/a", "<html></html>")],
                write_conn=MagicMock(),
                conference_date=None,
                reporter=MagicMock(),
                pool=pool,
            )
        assert total_int == 1
        assert total_dlq == 1
        mock_mc.assert_called_once()
        mock_mi.assert_called_once()
        mock_dlq.assert_called_once()
        mock_logger.warning.assert_called_once()
        assert pool.submit_calls[0][1] == ("https://example.com/a", "<html></html>", None)

    def test_worker_exception_logs_and_continues(self):
        service = self._service()
        future_ok = Future()
        future_ok.set_result((MagicMock(), [], []))
        future_err = Future()
        future_err.set_exception(RuntimeError("boom"))
        pool = _FakePool([future_ok, future_err])
        reporter = MagicMock()
        with (
            patch.object(service, "_logger") as mock_logger,
            patch("lakehouse.services.parse_service.merge_conference") as mock_mc,
        ):
            total_int, total_dlq = service._run_parallel(
                rows=[("a", "x"), ("b", "y")],
                write_conn=MagicMock(),
                conference_date=None,
                reporter=reporter,
                pool=pool,
            )
        assert total_int == 0
        assert total_dlq == 0
        assert reporter.tick.call_count == 2
        mock_logger.warning.assert_called_once()
        mock_mc.assert_called_once()

    def test_dry_run_skips_writes(self):
        service = self._service()
        conference = MagicMock()
        intervention = MagicMock()
        dlq = MagicMock()
        future_ok = Future()
        future_ok.set_result((conference, [intervention], [dlq]))
        pool = _FakePool([future_ok])
        with (
            patch("lakehouse.services.parse_service.merge_conference") as mock_mc,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_mi,
            patch("lakehouse.services.parse_service.insert_dlq_record") as mock_dlq,
            patch.object(service, "_logger") as mock_logger,
        ):
            total_int, total_dlq = service._run_parallel(
                rows=[("https://example.com/a", "<html></html>")],
                write_conn=None,
                conference_date=None,
                reporter=MagicMock(),
                pool=pool,
            )
        assert total_int == 1
        assert total_dlq == 1
        mock_mc.assert_not_called()
        mock_mi.assert_not_called()
        mock_dlq.assert_not_called()
        mock_logger.warning.assert_not_called()


class TestParseOneRow:
    def test_returns_conference_and_interventions(self):
        conference, interventions, dlq = _parse_one_row(
            source_url="https://example.com/27-de-julio-de-2026",
            raw_html=(
                "<html><title>Titulo</title><main>"
                "<strong>PERIODISTA:</strong> Buenos dias.</p>"
                "</main></html>"
            ),
            conference_date=None,
        )
        assert conference is not None
        assert conference.date == "2026-07-27"
        assert len(interventions) >= 1
        assert dlq == []

    def test_unknown_date_returns_dlq(self):
        conference, interventions, dlq = _parse_one_row(
            source_url="https://example.com/no-date",
            raw_html="<html></html>",
            conference_date=None,
        )
        assert conference is None
        assert interventions == []
        assert len(dlq) == 1
        assert dlq[0].rejection_reason == "unknown_date"

    def test_respects_conference_date_override(self):
        conference, _interventions, _dlq = _parse_one_row(
            source_url="https://example.com/articulo",
            raw_html="<html><title>T</title><main></main></html>",
            conference_date="2026-01-15",
        )
        assert conference is not None
        assert conference.date == "2026-01-15"
