from __future__ import annotations

from lakehouse.config import Settings


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
