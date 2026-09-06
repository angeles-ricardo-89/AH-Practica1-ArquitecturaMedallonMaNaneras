"""E2E SIN MOCKS contra un backend real en vivo.

Requisitos (igual que la demo):
- Backend corriendo (E2E_BASE_URL, default http://localhost:8001) con 2 usuarios demo.
- Postgres/pgvector real con corpus Gold.
- Ollama (embeddinggemma) y llamacpp reales para el agente.

Si no hay backend o credenciales, se omite (SKIP). No se mockea nada: solo HTTP real.
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8001")
USERNAME = os.environ.get("E2E_USERNAME", "")
PASSWORD = os.environ.get("E2E_PASSWORD", "")
USERNAME2 = os.environ.get("E2E_USERNAME2", "")
PASSWORD2 = os.environ.get("E2E_PASSWORD2", "")

pytestmark = pytest.mark.e2e


def _backend_alive() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def live_client() -> httpx.Client:
    if not (USERNAME and PASSWORD):
        pytest.skip("Definir E2E_USERNAME/E2E_PASSWORD para correr E2E")
    if not _backend_alive():
        pytest.skip(f"Backend E2E no disponible en {BASE_URL}")
    client = httpx.Client(base_url=BASE_URL, timeout=180.0)
    yield client
    client.close()


def test_health_is_public() -> None:
    if not _backend_alive():
        pytest.skip("Backend E2E no disponible")
    resp = httpx.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200


def test_login_and_protected_flow(live_client: httpx.Client) -> None:
    # Sin cookie, un endpoint protegido debe devolver 401
    r = live_client.get("/config")
    assert r.status_code == 401

    # Login real -> cookie + csrf
    r = live_client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    assert csrf

    # Identidad
    r = live_client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == USERNAME

    # /config ahora protegido accesible
    assert live_client.get("/config").status_code == 200


def test_conversation_and_agent_turn_end_to_end(live_client: httpx.Client) -> None:
    # crear conversacion
    r = live_client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    csrf = r.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    r = live_client.post("/conversations/", json={"title": "e2e gate"}, headers=headers)
    assert r.status_code == 200, r.text
    conv_id = r.json()["id"]

    # turno real del agente (llama a llamacpp + Ollama reales, sin mocks)
    r = live_client.post(
        f"/conversations/{conv_id}/messages",
        json={"question": "que se declaro sobre la reforma energetica?"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"], "la respuesta no debe ser vacia"
    assert body["tool_executions"], "el agente debe ejecutar al menos una herramienta"
    assert body["tool_executions"][0]["tool_name"] in {
        "buscar_declaraciones",
        "explorar_temas",
        "consultar_cluster",
    }

    # el historial queda persistido (memoria real)
    detail = live_client.get(f"/conversations/{conv_id}")
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 2

    # borrar conversacion (CSRF)
    r = live_client.delete(f"/conversations/{conv_id}", headers=headers)
    assert r.status_code == 200
    assert live_client.get(f"/conversations/{conv_id}").status_code == 404


def test_cross_user_conversation_isolation(live_client: httpx.Client) -> None:
    if not (USERNAME2 and PASSWORD2):
        pytest.skip("Definir E2E_USERNAME2/E2E_PASSWORD2 para verificar aislamiento entre usuarios")
    login = live_client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    created = live_client.post("/conversations/", json={"title": "privada user1"}, headers=headers)
    assert created.status_code == 200, created.text
    conv_id = created.json()["id"]

    with httpx.Client(base_url=BASE_URL, timeout=180.0) as other:
        login2 = other.post("/auth/login", json={"username": USERNAME2, "password": PASSWORD2})
        assert login2.status_code == 200, login2.text
        headers2 = {"X-CSRF-Token": login2.json()["csrf_token"]}

        assert other.get(f"/conversations/{conv_id}").status_code == 404
        msg = other.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "reforma energetica"},
            headers=headers2,
        )
        assert msg.status_code == 404
        assert other.delete(f"/conversations/{conv_id}", headers=headers2).status_code == 404

    cleanup = live_client.delete(f"/conversations/{conv_id}", headers=headers)
    assert cleanup.status_code == 200
