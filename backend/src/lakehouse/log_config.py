from __future__ import annotations

import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from typing import TextIO

    from structlog.typing import EventDict

_CONSOLE_LEVELS = frozenset({"warning", "error", "critical"})
_PROGRESS_INTERVAL_SECONDS = 2.0
_file_renderer = structlog.dev.ConsoleRenderer(colors=False)
_state = SimpleNamespace(configured=False)


def _pipeline_file_processor(
    logger: structlog.stdlib.BoundLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Escribe todos los eventos structlog en archivos por capa, dia y hora."""
    layer = event_dict.get("layer", "app")
    base_dir = os.environ.get("PIPELINE_LOGS", "logs")
    ts = event_dict.get("timestamp", datetime.now(UTC).isoformat())
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    file_dir = Path(base_dir) / dt.strftime("%Y-%m-%d")
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / f"{layer}_{dt.strftime('%Y%m%d')}_{os.getpid()}.log"
    rendered = _file_renderer(logger, method_name, event_dict)
    with Path.open(file_path, "a") as f:
        f.write(rendered + "\n")
    return event_dict


def _console_level_filter(
    logger: structlog.stdlib.BoundLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Descarta en consola los eventos por debajo de WARNING (se mantienen en archivo)."""
    level = event_dict.get("level", method_name)
    if level not in _CONSOLE_LEVELS:
        raise structlog.DropEvent
    return event_dict


def configure_logging(level: int = logging.INFO) -> None:
    if _state.configured:
        return
    _state.configured = True

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.stdlib.ExtraAdder(),
            structlog.processors.StackInfoRenderer(),
            _pipeline_file_processor,
            _console_level_filter,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(module_name: str, layer: str = "app") -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.stdlib.get_logger(module_name=module_name, layer=layer)


class ProgressReporter:
    """Reporta el avance de un proceso por lotes cada ``interval`` segundos.

    Escribe una linea de progreso en ``stream`` (stdout por defecto) y registra
    el evento en el archivo de logs con nivel INFO. Cuando ``total`` es conocido,
    la linea incluye el par procesados/total y el porcentaje.
    """

    def __init__(
        self,
        total: int | None = None,
        interval: float = _PROGRESS_INTERVAL_SECONDS,
        *,
        label: str = "pipeline",
        logger: structlog.stdlib.BoundLogger | None = None,
        stream: TextIO = sys.stdout,
    ) -> None:
        self._total = total
        self._interval = interval
        self._label = label
        self._logger = logger or get_logger("progress", layer="service")
        self._stream = stream
        self._processed = 0
        self._last_reported = time.monotonic() - interval
        self._last_line: str | None = None

    @property
    def processed(self) -> int:
        """Cantidad de registros procesados hasta el momento."""
        return self._processed

    @property
    def total(self) -> int | None:
        """Total esperado de registros, si se conoce."""
        return self._total

    def tick(self, n: int = 1) -> None:
        """Incrementa el contador de procesados en ``n`` y reporta si corresponde."""
        self._processed += n
        self._maybe_report()

    def update(self, processed: int) -> None:
        """Fija el contador de procesados y reporta si corresponde."""
        self._processed = max(processed, 0)
        self._maybe_report()

    def finish(self) -> None:
        """Fuerza un reporte final con el estado actual del contador."""
        if self._total == 0:
            return
        self.report()

    def _maybe_report(self) -> None:
        now = time.monotonic()
        if now - self._last_reported >= self._interval:
            self._last_reported = now
            self.report()

    def report(self) -> None:
        """Imprime una linea de progreso en ``stream`` y la registra en el archivo."""
        pct = self._percentage()
        processed_msg = (
            f"{self._processed}/{self._total} ({pct}%)"
            if self._total is not None
            else f"{self._processed} registros"
        )
        line = f"Progreso [{self._label}]: {processed_msg}"
        if line == self._last_line:
            return
        self._last_line = line
        self._stream.write(line + "\n")
        self._stream.flush()
        self._logger.info(
            "Progreso",
            etapa=self._label,
            procesados=self._processed,
            total=self._total,
            pct=pct,
        )

    def _percentage(self) -> int:
        if not self._total:
            return 0
        return min(100, round(self._processed / self._total * 100))
