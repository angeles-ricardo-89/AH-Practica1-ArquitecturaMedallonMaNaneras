from __future__ import annotations

from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from lakehouse.main import app
from lakehouse.schemas.agent import AgentTurnResult, ToolExecutionTrace


def _login(username: str, password: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return client, resp.json()["csrf_token"]


def _create_conversation(client: TestClient, csrf: str) -> str:
    resp = client.post(
        "/conversations/", json={"title": "investigacion"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _turn_result() -> AgentTurnResult:
    return AgentTurnResult(
        question="que dijo sobre energia?",
        answer="La presidenta dijo que la reforma avanza.",
        refusal=False,
        model_used="gemma-4-12b",
        tool_executions=[
            ToolExecutionTrace(
                tool_name="buscar_declaraciones",
                arguments={"consulta": "energia", "top_k": 8},
                result_count=3,
                duration_ms=120,
                status="ok",
            )
        ],
    )


def test_agent_turn_persists_messages_and_traces(real_auth, demo_users, pg_conn_str) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv_id = _create_conversation(client, csrf)

    with patch(
        "lakehouse.api.routers.conversations.run_agent_turn", return_value=_turn_result()
    ):
        resp = client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "que dijo sobre energia?"},
            headers={"X-CSRF-Token": csrf},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "La presidenta dijo que la reforma avanza."
    assert body["refusal"] is False
    assert len(body["tool_executions"]) == 1
    assert body["tool_executions"][0]["tool_name"] == "buscar_declaraciones"

    detail = client.get(f"/conversations/{conv_id}").json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "que dijo sobre energia?"
    assert detail["messages"][1]["content"] == "La presidenta dijo que la reforma avanza."

    with psycopg.connect(pg_conn_str) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM tool_execution WHERE conversation_id = "
            "(SELECT id FROM conversation WHERE public_id = %s)",
            (conv_id,),
        ).fetchone()[0]
    assert count == 1


def test_agent_turn_requires_csrf(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv_id = _create_conversation(client, csrf)
    resp = client.post(
        f"/conversations/{conv_id}/messages", json={"question": "hola"}
    )
    assert resp.status_code == 403


def test_agent_turn_other_user_404(real_auth, demo_users) -> None:
    client1, csrf1 = _login("testuser1", "test-password-1")
    conv_id = _create_conversation(client1, csrf1)
    client2, csrf2 = _login("testuser2", "test-password-2")
    resp = client2.post(
        f"/conversations/{conv_id}/messages",
        json={"question": "hola"},
        headers={"X-CSRF-Token": csrf2},
    )
    assert resp.status_code == 404


def test_agent_turn_model_error_returns_503(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv_id = _create_conversation(client, csrf)
    with patch(
        "lakehouse.api.routers.conversations.run_agent_turn",
        side_effect=RuntimeError("modelo no disponible"),
    ):
        resp = client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "hola"},
            headers={"X-CSRF-Token": csrf},
        )
    assert resp.status_code == 503
