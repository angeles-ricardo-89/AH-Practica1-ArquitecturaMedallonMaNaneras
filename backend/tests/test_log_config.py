from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

import pytest
import structlog

import lakehouse.log_config as lc
from lakehouse.log_config import (
    ProgressReporter,
    _console_level_filter,
    _pipeline_file_processor,
    configure_logging,
    get_logger,
)


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[tuple, dict]] = []

    def info(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))


class TestFileProcessor:
    def test_writes_all_layers_to_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PIPELINE_LOGS", str(tmp_path))
        event = {
            "timestamp": "2026-07-31T10:00:00.000000Z",
            "event": "evento de capa service",
            "layer": "service",
        }
        result = _pipeline_file_processor(object(), "info", event)
        assert result is event
        files = list(tmp_path.rglob("service_*.log"))
        assert len(files) == 1
        assert "evento de capa service" in files[0].read_text()

    def test_defaults_to_app_layer_without_layer(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PIPELINE_LOGS", str(tmp_path))
        event = {"timestamp": "2026-07-31T10:00:00.000000Z", "event": "sin capa"}
        _pipeline_file_processor(object(), "info", event)
        files = list(tmp_path.rglob("app_*.log"))
        assert len(files) == 1
        assert "sin capa" in files[0].read_text()

    def test_accepts_datetime_timestamp(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PIPELINE_LOGS", str(tmp_path))
        event = {
            "timestamp": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
            "event": "timestamp datetime",
            "layer": "bronze",
        }
        _pipeline_file_processor(object(), "info", event)
        files = list(tmp_path.rglob("bronze_*.log"))
        assert len(files) == 1

    def test_uses_pipeline_logs_env_when_set(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("PIPELINE_LOGS", str(tmp_path))
        event = {"timestamp": "2026-07-31T10:00:00.000000Z", "event": "x", "layer": "gold"}
        _pipeline_file_processor(object(), "info", event)
        assert len(list(tmp_path.rglob("gold_*.log"))) == 1


class TestConsoleLevelFilter:
    @pytest.mark.parametrize("level", ["debug", "info"])
    def test_drops_below_warning(self, level: str) -> None:
        with pytest.raises(structlog.DropEvent):
            _console_level_filter(object(), level, {"level": level})

    @pytest.mark.parametrize("level", ["warning", "error", "critical"])
    def test_keeps_warning_and_above(self, level: str) -> None:
        event = {"level": level}
        result = _console_level_filter(object(), level, event)
        assert result is event

    def test_uses_method_name_when_level_missing(self) -> None:
        with pytest.raises(structlog.DropEvent):
            _console_level_filter(object(), "info", {})
        assert _console_level_filter(object(), "warning", {}) == {}


class TestConfigureLogging:
    def test_is_idempotent(self) -> None:
        configure_logging()
        configure_logging(logging.DEBUG)
        assert lc._state.configured

    def test_get_logger_returns_bound_logger(self) -> None:
        log = get_logger("test_module", layer="bronze")
        assert callable(log.info)


class TestProgressReporter:
    def test_reports_with_total(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=10, interval=0.0, label="gold", logger=FakeLogger(), stream=stream
        )
        reporter.update(5)
        assert stream.getvalue() == "Progreso [gold]: 5/10 (50%)\n"

    def test_reports_without_total(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=None, interval=0.0, label="qa", logger=FakeLogger(), stream=stream
        )
        reporter.update(7)
        assert stream.getvalue() == "Progreso [qa]: 7 registros\n"

    def test_tick_increments_and_logs_event(self) -> None:
        stream = io.StringIO()
        logger = FakeLogger()
        reporter = ProgressReporter(
            total=4, interval=0.0, label="bronze", logger=logger, stream=stream
        )
        reporter.tick()
        reporter.tick(2)
        assert stream.getvalue() == ("Progreso [bronze]: 1/4 (25%)\nProgreso [bronze]: 3/4 (75%)\n")
        _, kwargs = logger.events[-1]
        assert kwargs["procesados"] == 3
        assert kwargs["total"] == 4
        assert kwargs["pct"] == 75
        assert kwargs["etapa"] == "bronze"

    def test_update_clamps_negative(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=10, interval=0.0, label="x", logger=FakeLogger(), stream=stream
        )
        reporter.update(-5)
        assert reporter.processed == 0
        assert stream.getvalue() == "Progreso [x]: 0/10 (0%)\n"

    def test_percentage_caps_at_100(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=10, interval=0.0, label="x", logger=FakeLogger(), stream=stream
        )
        reporter.update(12)
        assert "100%" in stream.getvalue()

    def test_finish_forces_final_report_without_duplicate(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=3, interval=0.0, label="x", logger=FakeLogger(), stream=stream
        )
        reporter.update(3)
        reporter.finish()
        assert stream.getvalue() == "Progreso [x]: 3/3 (100%)\n"

    def test_total_property(self) -> None:
        reporter = ProgressReporter(total=5, logger=FakeLogger(), stream=io.StringIO())
        assert reporter.total == 5
        assert reporter.processed == 0

    def test_finish_skips_when_total_is_zero(self) -> None:
        stream = io.StringIO()
        reporter = ProgressReporter(
            total=0, interval=0.0, label="silver", logger=FakeLogger(), stream=stream
        )
        reporter.finish()
        assert stream.getvalue() == ""

    def test_reports_every_interval(self, monkeypatch) -> None:
        clock = {"t": 0.0}
        monkeypatch.setattr(lc.time, "monotonic", lambda: clock["t"])
        stream = io.StringIO()
        reporter = lc.ProgressReporter(
            total=10, interval=2.0, label="bronze", logger=FakeLogger(), stream=stream
        )
        reporter.update(1)
        clock["t"] = 1.5
        reporter.update(2)
        clock["t"] = 2.0
        reporter.update(3)
        clock["t"] = 4.0
        reporter.update(4)
        assert stream.getvalue().splitlines() == [
            "Progreso [bronze]: 1/10 (10%)",
            "Progreso [bronze]: 3/10 (30%)",
            "Progreso [bronze]: 4/10 (40%)",
        ]

    def test_default_interval_is_two_seconds(self) -> None:
        reporter = ProgressReporter(total=10, logger=FakeLogger(), stream=io.StringIO())
        assert reporter._interval == 2.0

    def test_default_logger_uses_get_logger(self, monkeypatch) -> None:
        fake = FakeLogger()

        def fake_get_logger(*args: object, **kwargs: object) -> FakeLogger:
            return fake

        monkeypatch.setattr(lc, "get_logger", fake_get_logger)
        reporter = lc.ProgressReporter(total=1, interval=0.0, stream=io.StringIO())
        reporter.update(1)
        assert fake.events
