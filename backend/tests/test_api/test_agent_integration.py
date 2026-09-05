"""Integracion real del agente: autenticacion + memoria + ejecucion del ciclo completo
contra PostgreSQL real. UNICA simulacion: la llamada HTTP externa a llamacpp (llm._post),
que es una entidad externa. Nada interno se mockea: el validador, el ejecutor, las tools,
la consulta SQL real y la persistencia corren tal cual."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.main import app
from lakehouse.pipeline.clustering import ensure_clustering_schema
from lakehouse.services.agent.synthesizer import REFUSAL_TEXT

if TYPE_CHECKING:
    from collections.abc import Callable

PLAN_EXPLORAR = (
    '{"tool_name": "explorar_temas", "arguments": {"texto": null, "limite": 5}, '
    '"motivo": "temas generales"}'
)
PLAN_CLUSTER_INEXISTENTE = (
    '{"tool_name": "consultar_cluster", "arguments": {"cluster_id": 99999, "limite": 4}, '
    '"motivo": "cluster"}'
)
FOLLOWUP_NONE = '{"tool_name": null}'


def _fake_llamacpp(plan_first: str) -> Callable[..., str]:
    """Simula SOLO el servidor externo llamacpp (frontera HTTP).

    - Llamada JSON de planificacion inicial -> plan_first.
    - Llamada JSON de seguimiento (contiene 'Resultado de la primera') -> sin segunda tool.
    - Llamada de texto (sintesis) -> respuesta con cita.
    """

    def _post(settings, messages, *, json_mode, max_tokens) -> str:
        last_user = ""
        for m in messages:
            if m["role"] == "user":
                last_user = m["content"]
        if json_mode:
            if "Resultado de la primera" in last_user:
                return FOLLOWUP_NONE
            return plan_first
        return "Respuesta integrada citando la evidencia recuperada."

    return _post


def _login() -> tuple[TestClient, str]:
    client = TestClient(app)
    resp = client.post(
        "/auth/login", json={"username": "testuser1", "password": "test-password-1"}
    )
    assert resp.status_code == 200, resp.text
    return client, resp.json()["csrf_token"]


@pytest.fixture
def seeded_clusters(pg_conn_str: str):
    run_id = str(uuid.uuid4())
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        conn.execute(
            "INSERT INTO gold.clustering_runs (run_id, status, cluster_count, noise_count) "
            "VALUES (%s, 'completed', 1, 0)",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO gold.cluster_labels "
            "(clustering_run_id, cluster_id, cluster_label, label_status) "
            "VALUES (%s, 0, 'energia', 'completed')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date, "
            "participant, chunk_text, url, cluster_id, cluster_pertenencia, clustering_run_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "itg_k1",
                "c1",
                "2025-01-01",
                "PARTICIPANTE A",
                "texto largo suficiente sobre energia electrica y reforma",
                "u1",
                0,
                0.9,
                run_id,
            ),
        )
        conn.commit()
    yield
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.cluster_labels WHERE clustering_run_id = %s", (run_id,))
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key = 'itg_k1'")
        conn.execute("DELETE FROM gold.clustering_runs WHERE run_id = %s", (run_id,))
        conn.commit()


def test_agent_turn_real_flow_with_evidence(real_auth, demo_users, seeded_clusters) -> None:
    client, csrf = _login()
    created = client.post(
        "/conversations/", json={"title": "integ"}, headers={"X-CSRF-Token": csrf}
    ).json()
    conv_id = created["id"]

    fake = _fake_llamacpp(PLAN_EXPLORAR)
    with patch("lakehouse.services.agent.llm._post", side_effect=fake) as mock:
        resp = client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "cuales son los temas del corpus?"},
            headers={"X-CSRF-Token": csrf},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["refusal"] is False
    assert body["answer"] == "Respuesta integrada citando la evidencia recuperada."
    assert body["model_used"] == "gemma-4-12b"
    tools = [t["tool_name"] for t in body["tool_executions"]]
    assert tools == ["explorar_temas"]
    assert body["tool_executions"][0]["result_count"] == 1
    # el planificador se llamo (json inicial) + seguimiento + sintesis (texto)
    assert mock.call_count >= 3

    detail = client.get(f"/conversations/{conv_id}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_agent_turn_real_flow_refuses_without_evidence(
    real_auth, demo_users, seeded_clusters
) -> None:
    client, csrf = _login()
    created = client.post(
        "/conversations/", json={"title": "refusal"}, headers={"X-CSRF-Token": csrf}
    ).json()
    conv_id = created["id"]

    fake = _fake_llamacpp(PLAN_CLUSTER_INEXISTENTE)
    with patch("lakehouse.services.agent.llm._post", side_effect=fake) as mock:
        resp = client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "algo sin respaldo en ningun cluster"},
            headers={"X-CSRF-Token": csrf},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["refusal"] is True
    assert body["answer"] == REFUSAL_TEXT
    assert [t["tool_name"] for t in body["tool_executions"]] == ["consultar_cluster"]
    # sintesis = negativa sin llamada de texto al LLM
    text_calls = [c for c in mock.call_args_list if c.kwargs.get("json_mode") is False]
    assert text_calls == []


def test_conversation_isolated_between_users(real_auth, demo_users) -> None:
    client1, csrf1 = _login()
    conv = client1.post(
        "/conversations/", json={"title": "privada"}, headers={"X-CSRF-Token": csrf1}
    ).json()
    conv_id = conv["id"]

    client2 = TestClient(app)
    login2 = client2.post(
        "/auth/login", json={"username": "testuser2", "password": "test-password-2"}
    )
    csrf2 = login2.json()["csrf_token"]
    assert client2.get(f"/conversations/{conv_id}").status_code == 404
    resp = client2.post(
        f"/conversations/{conv_id}/messages",
        json={"question": "intento ajeno"},
        headers={"X-CSRF-Token": csrf2},
    )
    assert resp.status_code == 404
