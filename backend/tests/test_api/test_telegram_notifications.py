from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from lakehouse.api.deps import get_settings
from lakehouse.config import Settings
from lakehouse.main import app
from lakehouse.schemas.agent import AgentTurnResult
from lakehouse.services import telegram_notifier


def _login(username: str, password: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return client, resp.json()["csrf_token"]


def _create_conversation(client: TestClient, csrf: str) -> str:
    resp = client.post("/conversations/", json={"title": "notif"}, headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    return resp.json()["id"]


def _turn_result() -> AgentTurnResult:
    return AgentTurnResult(
        question="que dijo sobre energia?",
        answer="La presidenta dijo que la reforma avanza.",
        model_used="gemma-4-12b",
    )


def _post_message(client: TestClient, csrf: str, conv_id: str) -> httpx.Response:
    with patch("lakehouse.api.routers.conversations.run_agent_turn", return_value=_turn_result()):
        return client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "que dijo sobre energia?"},
            headers={"X-CSRF-Token": csrf},
        )


def _enable_telegram(monkeypatch, handler) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_bot_token="test-token", telegram_chat_id="12345"
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        telegram_notifier.httpx,
        "Client",
        lambda timeout=None, **_unused: real_client(
            transport=httpx.MockTransport(handler), timeout=timeout
        ),
    )


def test_agent_turn_sends_telegram_notification(real_auth, demo_users, monkeypatch) -> None:
    captured = {}

    def handler(request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _enable_telegram(monkeypatch, handler)
    try:
        client, csrf = _login("testuser1", "test-password-1")
        conv_id = _create_conversation(client, csrf)
        resp = _post_message(client, csrf, conv_id)
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert captured["url"] == "https://api.telegram.org/bottest-token/sendMessage"
    assert captured["body"]["chat_id"] == "12345"
    assert "que dijo sobre energia?" in captured["body"]["text"]
    assert "La presidenta dijo que la reforma avanza." in captured["body"]["text"]


def test_agent_turn_telegram_failure_does_not_break(real_auth, demo_users, monkeypatch) -> None:
    _enable_telegram(monkeypatch, lambda _request: httpx.Response(500, json={"ok": False}))
    try:
        client, csrf = _login("testuser1", "test-password-1")
        conv_id = _create_conversation(client, csrf)
        resp = _post_message(client, csrf, conv_id)
        assert resp.status_code == 200
        assert resp.json()["answer"] == "La presidenta dijo que la reforma avanza."
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_agent_turn_without_telegram_config_is_noop(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv_id = _create_conversation(client, csrf)
    resp = _post_message(client, csrf, conv_id)
    assert resp.status_code == 200
    assert resp.json()["answer"] == "La presidenta dijo que la reforma avanza."
