from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lakehouse.main import app

pytestmark = [pytest.mark.security("A01")]


def _login(username: str, password: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return client, resp.json()["csrf_token"]


def test_create_and_list_conversations(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    r1 = client.post("/conversations/", json={"title": "energia"}, headers={"X-CSRF-Token": csrf})
    r2 = client.post("/conversations/", json={"title": "salud"}, headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len({r1.json()["id"], r2.json()["id"]}) == 2

    listing = client.get("/conversations/")
    assert listing.status_code == 200
    titles = {c["title"] for c in listing.json()["conversations"]}
    assert titles == {"energia", "salud"}


def test_cross_user_isolation(real_auth, demo_users) -> None:
    client1, csrf1 = _login("testuser1", "test-password-1")
    conv = client1.post(
        "/conversations/", json={"title": "privada"}, headers={"X-CSRF-Token": csrf1}
    ).json()
    conv_id = conv["id"]

    client2, _ = _login("testuser2", "test-password-2")
    assert client2.get(f"/conversations/{conv_id}").status_code == 404
    own_ids = [c["id"] for c in client2.get("/conversations/").json()["conversations"]]
    assert conv_id not in own_ids
    assert client1.get(f"/conversations/{conv_id}").status_code == 200


def test_delete_cascades(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv = client.post(
        "/conversations/", json={"title": "x"}, headers={"X-CSRF-Token": csrf}
    ).json()
    conv_id = conv["id"]
    assert client.get(f"/conversations/{conv_id}").status_code == 200
    assert (
        client.delete(f"/conversations/{conv_id}", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert client.get(f"/conversations/{conv_id}").status_code == 404
    ids = [c["id"] for c in client.get("/conversations/").json()["conversations"]]
    assert conv_id not in ids


def test_delete_requires_csrf(real_auth, demo_users) -> None:
    client, csrf = _login("testuser1", "test-password-1")
    conv = client.post(
        "/conversations/", json={"title": "x"}, headers={"X-CSRF-Token": csrf}
    ).json()
    assert client.delete(f"/conversations/{conv['id']}").status_code == 403


def test_create_requires_csrf(real_auth, demo_users) -> None:
    client, _ = _login("testuser1", "test-password-1")
    assert client.post("/conversations/", json={"title": "x"}).status_code == 403
