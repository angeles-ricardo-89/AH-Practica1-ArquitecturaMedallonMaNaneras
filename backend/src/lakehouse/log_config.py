import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

_PIPELINE_LAYERS = frozenset({"bronze", "silver", "gold", "qa"})
_file_renderer = structlog.dev.ConsoleRenderer(colors=False)


def _pipeline_file_processor(
    logger: structlog.stdlib.BoundLogger,
    method_name: str,
    event_dict: dict,
) -> dict:
    layer = event_dict.get("layer")
    if layer not in _PIPELINE_LAYERS:
        return event_dict
    base_dir = os.environ.get("PIPELINE_LOGS", "logs")
    ts = event_dict.get("timestamp", datetime.now(UTC).isoformat())
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    file_dir = Path(base_dir) / dt.strftime("%Y-%m-%d")
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / f"{layer}_{dt.strftime('%Y%m%d%H')}_{os.getpid()}.log"
    rendered = _file_renderer(logger, method_name, event_dict)
    with Path.open(file_path, "a") as f:
        f.write(rendered + "\n")
    return event_dict


def configure_logging(level: int = logging.INFO) -> None:
    if getattr(configure_logging, "configured", False):
        return
    configure_logging.configured = True

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    logging.getLogger().setLevel(level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.stdlib.ExtraAdder(),
            structlog.processors.StackInfoRenderer(),
            _pipeline_file_processor,
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
