from __future__ import annotations

import os
import signal
from unittest.mock import patch

import pytest

from lakehouse.pipeline.interrupt import InterruptState, install_graceful_interrupt, interrupt_state


@pytest.fixture
def clean_state() -> None:
    interrupt_state.reset()
    yield
    interrupt_state.reset()


class TestInterruptState:
    def test_starts_not_requested(self) -> None:
        assert InterruptState().requested() is False

    def test_request_and_reset(self) -> None:
        state = InterruptState()
        state._request()
        assert state.requested() is True
        state.reset()
        assert state.requested() is False


class TestInstallGracefulInterrupt:
    def test_sigterm_sets_flag_then_restores_handler(self, clean_state: None) -> None:
        previous = signal.getsignal(signal.SIGTERM)
        with install_graceful_interrupt():
            os.kill(os.getpid(), signal.SIGTERM)
            assert interrupt_state.requested() is True
        assert signal.getsignal(signal.SIGTERM) is previous

    def test_second_signal_force_exits(self, clean_state: None) -> None:
        with (
            patch("lakehouse.pipeline.interrupt.os._exit") as mock_exit,
            install_graceful_interrupt(),
        ):
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGINT)
        mock_exit.assert_called_once_with(130)

    def test_restores_original_handlers(self) -> None:
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)
        with install_graceful_interrupt():
            pass
        assert signal.getsignal(signal.SIGINT) is previous_int
        assert signal.getsignal(signal.SIGTERM) is previous_term

    def test_install_failure_is_tolerated(self, clean_state: None) -> None:
        with (
            patch("lakehouse.pipeline.interrupt.signal.signal", side_effect=OSError("no")),
            install_graceful_interrupt(),
        ):
            pass
        assert interrupt_state.requested() is False

    def test_restore_failure_is_ignored(self, clean_state: None) -> None:
        calls = {"count": 0}

        def flaky(_sig: int, _handler: object) -> object:
            calls["count"] += 1
            if calls["count"] > 2:
                raise OSError("restore failed")
            return signal.SIG_DFL

        with (
            patch("lakehouse.pipeline.interrupt.signal.signal", side_effect=flaky),
            install_graceful_interrupt(),
        ):
            pass
