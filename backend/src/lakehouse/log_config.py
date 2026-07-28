import logging
import sys

import structlog


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
