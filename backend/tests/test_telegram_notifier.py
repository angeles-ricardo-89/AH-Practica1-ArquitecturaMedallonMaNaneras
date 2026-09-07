from __future__ import annotations

import json

import httpx

from lakehouse.config import Settings
from lakehouse.services import telegram_notifier
from lakehouse.services.telegram_notifier import TelegramNotifier, build_notification


class TestSettings:
    def test_telegram_settings_default_empty(self, monkeypatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        settings = Settings(_env_file=None)
        assert settings.telegram_bot_token == ""
        assert settings.telegram_chat_id == ""

    def test_telegram_settings_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
        settings = Settings(_env_file=None)
        assert settings.telegram_bot_token == "tok"
        assert settings.telegram_chat_id == "12345"


class TestBuildNotification:
    def test_format_includes_question_and_answer(self) -> None:
        text = build_notification("que dijo?", "la reforma avanza")
        assert "Nueva consulta en el chat" in text
        assert "que dijo?" in text
        assert "la reforma avanza" in text

    def test_truncates_question_and_answer(self) -> None:
        question = "x" * 2000
        answer = "y" * 5000
        text = build_notification(question, answer)
        assert f"Pregunta: {'x' * 500}\n" in text
        assert "x" * 501 not in text
        assert text.endswith("y" * 3000)
        assert "y" * 3001 not in text
        assert len(text) <= 4096


class TestTelegramNotifier:
    def test_is_enabled_requires_token_and_chat_id(self) -> None:
        assert TelegramNotifier("", "123").is_enabled is False
        assert TelegramNotifier("tok", "").is_enabled is False
        assert TelegramNotifier("tok", "123").is_enabled is True

    def test_send_disabled_returns_false_without_network(self, monkeypatch) -> None:
        called = False

        def fake_client(*args: object, **kwargs: object) -> None:
            nonlocal called
            called = True
            raise AssertionError("no debe contactar la red")

        monkeypatch.setattr(telegram_notifier.httpx, "Client", fake_client)
        assert TelegramNotifier("", "").send("hola") is False
        assert called is False

    def _install_transport(self, monkeypatch, handler) -> None:
        real_client = httpx.Client

        def factory(timeout: float | None = None, **kwargs: object) -> httpx.Client:
            return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

        monkeypatch.setattr(telegram_notifier.httpx, "Client", factory)

    def test_send_ok_builds_url_and_body(self, monkeypatch) -> None:
        captured = {}

        def handler(request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True})

        self._install_transport(monkeypatch, handler)
        assert TelegramNotifier("tok", "123").send("hola") is True
        assert captured["url"] == "https://api.telegram.org/bottok/sendMessage"
        assert captured["body"] == {"chat_id": "123", "text": "hola"}

    def test_send_returns_false_on_ok_false(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda _request: httpx.Response(200, json={"ok": False})
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_http_error(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda _request: httpx.Response(500, json={"ok": False})
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_non_json_200(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda _request: httpx.Response(200, content=b"no json")
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_network_error(self, monkeypatch) -> None:
        def fake_client(*args: object, **kwargs: object) -> None:
            raise httpx.ConnectError("sin red")

        monkeypatch.setattr(telegram_notifier.httpx, "Client", fake_client)
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_does_not_log_token(self, monkeypatch) -> None:
        captured = []

        class FakeLogger:
            def warning(self, msg, *args: object, **kwargs: object) -> None:
                captured.append(msg)

            def exception(self, msg, *args: object, **kwargs: object) -> None:
                captured.append(msg)

        monkeypatch.setattr(telegram_notifier, "logger", FakeLogger())
        self._install_transport(
            monkeypatch, lambda _request: httpx.Response(401, json={"ok": False})
        )
        TelegramNotifier("secret-token", "999").send("hola")
        assert captured
        assert all("secret-token" not in m for m in captured)
        assert all("999" not in m for m in captured)
