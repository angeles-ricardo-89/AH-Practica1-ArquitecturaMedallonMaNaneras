from __future__ import annotations

import os
import signal
import threading
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

from lakehouse.log_config import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger(__name__, layer="pipeline")


class InterruptState:
    """Flag thread-safe que registra una solicitud cooperativa de interrupcion."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def requested(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()

    def _request(self) -> None:
        self._event.set()


interrupt_state = InterruptState()


def _handler(signum: int, _frame: object) -> None:
    if interrupt_state.requested():
        os._exit(128 + signum)
    interrupt_state._request()  # noqa: SLF001


@contextmanager
def install_graceful_interrupt() -> Iterator[None]:
    """Instala handlers de SIGINT/SIGTERM que piden cierre cooperativo.

    Primera senal: setea el flag (los loops drenan y el CLI escribe 'interrupted').
    Segunda senal: fuerza ``os._exit(128 + signum)``.
    """
    previous: dict[int, signal._HANDLER] = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.signal(sig, _handler)
            except (ValueError, OSError):
                logger.warning("No se pudo instalar handler de senal", sig=sig)
        yield
    finally:
        for sig, handler in previous.items():
            with suppress(ValueError, OSError):
                signal.signal(sig, handler)
