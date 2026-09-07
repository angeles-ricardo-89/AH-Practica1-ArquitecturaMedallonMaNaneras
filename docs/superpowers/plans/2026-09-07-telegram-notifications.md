# Telegram Chat Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notificar por bot de Telegram (best-effort) cada turno agéntico del chat, enviando pregunta y respuesta al chat del operador.

**Architecture:** Un servicio `TelegramNotifier` (httpx → `api.telegram.org`) desacoplado del flujo crítico. El endpoint `/conversations/{id}/messages` encola la notificación vía `BackgroundTasks` tras persistir la respuesta. Config vía `Settings` (`telegram_bot_token`, `telegram_chat_id`), secretos expuestos desde Secret Manager en Cloud Run (Terraform).

**Tech Stack:** Python 3.13, FastAPI, pydantic-settings, httpx, pytest, Terraform (GCP Secret Manager + Cloud Run).

**Spec:** `docs/superpowers/specs/2026-09-07-telegram-notifications-design.md`

---

## File Structure

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `backend/src/lakehouse/config.py` | Modificar | Campos `telegram_bot_token`, `telegram_chat_id` |
| `backend/src/lakehouse/services/telegram_notifier.py` | Crear | `TelegramNotifier` + `build_notification` |
| `backend/src/lakehouse/api/routers/conversations.py` | Modificar | Hook de notificación en `send_message` |
| `backend/tests/test_telegram_notifier.py` | Crear | Tests unitarios del notificador + config |
| `backend/tests/test_api/test_telegram_notifications.py` | Crear | Integración HTTP (mock solo en la frontera HTTP de Telegram) |
| `.env.template` | Modificar | Placeholders `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` |
| `infra/terraform/variables.tf` | Modificar | Ampliar `existing_secrets` |
| `infra/terraform/main.tf` | Modificar | `data` de los 2 secretos + env vars Cloud Run |
| `infra/terraform/terraform.tfvars.example` | Modificar | Nuevas claves de `existing_secrets` |

---

## Task 1: Campos de configuración

**Files:**
- Modify: `backend/src/lakehouse/config.py:72-78`
- Test: `backend/tests/test_telegram_notifier.py` (clase `TestSettings`)

- [ ] **Step 1: Escribir el test que falla**

Crear `backend/tests/test_telegram_notifier.py` con la parte de config:

```python
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
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd backend && uv run pytest tests/test_telegram_notifier.py -xvs`
Expected: FAIL — `Settings` no tiene el atributo `telegram_bot_token` (ValidationError/AttributeError en el import o en la construcción).

- [ ] **Step 3: Implementar los campos**

En `backend/src/lakehouse/config.py`, tras `frontend_dist_dir: str = ""` (línea 78) añadir:

```python
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd backend && uv run pytest tests/test_telegram_notifier.py::TestSettings -xvs`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/mydata/projects/proyecto1_diplo
git add backend/src/lakehouse/config.py backend/tests/test_telegram_notifier.py
git commit -m "agrega configuracion de telegram para notificaciones"
```

---

## Task 2: Servicio TelegramNotifier

**Files:**
- Create: `backend/src/lakehouse/services/telegram_notifier.py`
- Test: `backend/tests/test_telegram_notifier.py` (clases `TestBuildNotification` y `TestTelegramNotifier`)

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `backend/tests/test_telegram_notifier.py` (debajo de `TestSettings`):

```python
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

        def fake_client(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("no debe contactar la red")

        monkeypatch.setattr(telegram_notifier.httpx, "Client", fake_client)
        assert TelegramNotifier("", "").send("hola") is False
        assert called is False

    def _install_transport(self, monkeypatch, handler):
        monkeypatch.setattr(
            telegram_notifier.httpx,
            "Client",
            lambda timeout=None, **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler), timeout=timeout
            ),
        )

    def test_send_ok_builds_url_and_body(self, monkeypatch) -> None:
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True})

        self._install_transport(monkeypatch, handler)
        assert TelegramNotifier("tok", "123").send("hola") is True
        assert captured["url"] == "https://api.telegram.org/bottok/sendMessage"
        assert captured["body"] == {"chat_id": "123", "text": "hola"}

    def test_send_returns_false_on_ok_false(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda request: httpx.Response(200, json={"ok": False})
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_http_error(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda request: httpx.Response(500, json={"ok": False})
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_non_json_200(self, monkeypatch) -> None:
        self._install_transport(
            monkeypatch, lambda request: httpx.Response(200, content=b"no json")
        )
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_returns_false_on_network_error(self, monkeypatch) -> None:
        def fake_client(*args, **kwargs):
            raise httpx.ConnectError("sin red")

        monkeypatch.setattr(telegram_notifier.httpx, "Client", fake_client)
        assert TelegramNotifier("tok", "123").send("hola") is False

    def test_send_does_not_log_token(self, monkeypatch) -> None:
        captured = []

        class FakeLogger:
            def warning(self, msg, *args, **kwargs):
                captured.append(msg)

            def exception(self, msg, *args, **kwargs):
                captured.append(msg)

        monkeypatch.setattr(telegram_notifier, "logger", FakeLogger())
        self._install_transport(
            monkeypatch, lambda request: httpx.Response(401, json={"ok": False})
        )
        TelegramNotifier("secret-token", "999").send("hola")
        assert captured
        assert all("secret-token" not in m for m in captured)
        assert all("999" not in m for m in captured)
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd backend && uv run pytest tests/test_telegram_notifier.py -xvs`
Expected: FAIL — `ModuleNotFoundError: No module named 'lakehouse.services.telegram_notifier'`.

- [ ] **Step 3: Implementar el servicio**

Crear `backend/src/lakehouse/services/telegram_notifier.py`:

```python
from __future__ import annotations

import httpx

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="service")

_TELEGRAM_API = "https://api.telegram.org"
_QUESTION_LIMIT = 500
_ANSWER_LIMIT = 3000


def build_notification(question: str, answer: str) -> str:
    question = question[:_QUESTION_LIMIT]
    answer = answer[:_ANSWER_LIMIT]
    return (
        "Nueva consulta en el chat\n\n"
        f"Pregunta: {question}\n"
        f"Respuesta: {answer}"
    )


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    @property
    def is_enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def send(self, text: str) -> bool:
        if not self.is_enabled:
            return False
        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text}
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
        except Exception:
            logger.exception("Telegram: error de red enviando notificacion")
            return False

        if resp.status_code != 200:
            logger.warning("Telegram: envio fallido (status=%s)", resp.status_code)
            return False

        try:
            ok = bool(resp.json().get("ok"))
        except ValueError:
            logger.warning("Telegram: respuesta no JSON")
            return False

        if not ok:
            logger.warning("Telegram: devolvio ok=false")
        return ok
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd backend && uv run pytest tests/test_telegram_notifier.py -xvs`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/mydata/projects/proyecto1_diplo
git add backend/src/lakehouse/services/telegram_notifier.py backend/tests/test_telegram_notifier.py
git commit -m "agrega notificador de telegram best-effort"
```

---

## Task 3: Hook en el turno agéntico

**Files:**
- Modify: `backend/src/lakehouse/api/routers/conversations.py:3` (imports), `:19` (import servicio), `:125-130` (firma), `:180-182` (antes del return)
- Test: `backend/tests/test_api/test_telegram_notifications.py`

- [ ] **Step 1: Escribir los tests de integración que fallan**

Crear `backend/tests/test_api/test_telegram_notifications.py`:

```python
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
    resp = client.post(
        "/conversations/", json={"title": "notif"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _turn_result() -> AgentTurnResult:
    return AgentTurnResult(
        question="que dijo sobre energia?",
        answer="La presidenta dijo que la reforma avanza.",
        model_used="gemma-4-12b",
    )


def _enable_telegram(monkeypatch, handler):
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_bot_token="test-token", telegram_chat_id="12345"
    )
    monkeypatch.setattr(
        telegram_notifier.httpx,
        "Client",
        lambda timeout=None, **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler), timeout=timeout
        ),
    )


def _post_message(client, csrf, conv_id):
    with patch(
        "lakehouse.api.routers.conversations.run_agent_turn", return_value=_turn_result()
    ):
        return client.post(
            f"/conversations/{conv_id}/messages",
            json={"question": "que dijo sobre energia?"},
            headers={"X-CSRF-Token": csrf},
        )


def test_agent_turn_sends_telegram_notification(real_auth, demo_users, monkeypatch) -> None:
    captured = {}

    def handler(request):
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
    _enable_telegram(
        monkeypatch, lambda request: httpx.Response(500, json={"ok": False})
    )
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
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd backend && uv run pytest tests/test_api/test_telegram_notifications.py -xvs`
Expected: FAIL — `test_agent_turn_sends_telegram_notification` falla porque `captured` queda vacío (no existe el hook). `test_agent_turn_without_telegram_config_is_noop` debería pasar desde el inicio.

- [ ] **Step 3: Implementar el hook**

En `backend/src/lakehouse/api/routers/conversations.py`:

Cambiar la línea 3:

```python
from fastapi import APIRouter, Depends, HTTPException
```

por:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
```

Tras la línea 37 (`from lakehouse.services.security import resolve_jwt_secret`), añadir:

```python
from lakehouse.services.telegram_notifier import TelegramNotifier, build_notification
```

Cambiar la firma de `send_message` (líneas 125-130), añadiendo el parámetro `background_tasks`:

```python
def send_message(
    conversation_id: str,
    payload: AgentMessageRequest,
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
    background_tasks: BackgroundTasks,
) -> AgentMessageResponse:
```

(FastAPI inyecta `BackgroundTasks` por su anotación de tipo; no lleva valor por defecto.)

Justo antes del `return AgentMessageResponse(...)` (tras `touch_conversation(conn_str, conv_id)`, línea 180), insertar:

```python
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    if notifier.is_enabled:
        background_tasks.add_task(
            notifier.send, build_notification(result.question, result.answer)
        )
```

- [ ] **Step 4: Ejecutar y verificar que pasa**

Run: `cd backend && uv run pytest tests/test_api/test_telegram_notifications.py -xvs`
Expected: PASS (3 passed).

- [ ] **Step 5: Ejecutar la suite de chat existente (regresión)**

Run: `cd backend && uv run pytest tests/test_api/test_agent_turn.py tests/test_api/test_conversations.py -xvs`
Expected: PASS — sin regresiones.

- [ ] **Step 6: Commit**

```bash
cd /mnt/mydata/projects/proyecto1_diplo
git add backend/src/lakehouse/api/routers/conversations.py backend/tests/test_api/test_telegram_notifications.py
git commit -m "notifica por telegram pregunta y respuesta del turno agentico"
```

---

## Task 4: Plantilla `.env.template` y Terraform

**Files:**
- Modify: `.env.template`
- Modify: `infra/terraform/variables.tf`
- Modify: `infra/terraform/main.tf`
- Modify: `infra/terraform/terraform.tfvars.example`

- [ ] **Step 1: Añadir placeholders a `.env.template`**

Al final de `.env.template`, añadir:

```
# Telegram (notificaciones best-effort). Token y chat id desde Secret Manager en prod.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 2: Ampliar `existing_secrets` en `variables.tf`**

Reemplazar el bloque `variable "existing_secrets"` (líneas 66-72) por:

```hcl
variable "existing_secrets" {
  type = object({
    gemini_api_key     = string
    neon_db_url        = string
    telegram_bot_token = string
    telegram_chat_id   = string
  })
  description = "Nombres de secretos existentes en Secret Manager"
}
```

- [ ] **Step 3: Añadir `data` de los dos secretos en `main.tf`**

Tras el bloque `data "google_secret_manager_secret" "neon_db_url"` (líneas 56-58), añadir:

```hcl
data "google_secret_manager_secret" "telegram_bot_token" {
  secret_id = var.existing_secrets.telegram_bot_token
}

data "google_secret_manager_secret" "telegram_chat_id" {
  secret_id = var.existing_secrets.telegram_chat_id
}
```

- [ ] **Step 4: Añadir env vars en el contenedor Cloud Run**

En `main.tf`, tras el bloque `env` de `NEON_DATABASE_URL` (líneas 231-239) y antes del cierre de `containers {`, añadir:

```hcl
      env {
        name  = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.telegram_bot_token.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "TELEGRAM_CHAT_ID"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.telegram_chat_id.secret_id
            version = "latest"
          }
        }
      }
```

- [ ] **Step 5: Actualizar `terraform.tfvars.example`**

Reemplazar el bloque `existing_secrets` por:

```hcl
existing_secrets = {
  gemini_api_key     = "GEMINI_API_KEY"
  neon_db_url        = "NEON_DATABASE_URL"
  telegram_bot_token = "TELEGRAM_BOT_TOKEN"
  telegram_chat_id   = "TELEGRAM_CHAT_ID"
}
```

- [ ] **Step 6: Validar formato y plan de Terraform**

Run: `cd infra/terraform && terraform fmt -check && terraform validate`
Expected: sin errores de formato ni de validación.

> Nota: `terraform plan` requiere credenciales GCP reales y que el secreto `TELEGRAM_CHAT_ID`
> exista en Secret Manager. El operador debe (1) crear el secreto `TELEGRAM_CHAT_ID` en GCP con su
> chat id numérico y (2) añadir `telegram_bot_token`/`telegram_chat_id` a su `terraform.tfvars` real
> (gitignored). No se ejecuta `apply` en este plan.

- [ ] **Step 7: Commit**

```bash
cd /mnt/mydata/projects/proyecto1_diplo
git add .env.template infra/terraform/variables.tf infra/terraform/main.tf infra/terraform/terraform.tfvars.example
git commit -m "expone secretos de telegram en cloud run via terraform"
```

---

## Task 5: Verificación final (Gate Q + Gate SEC)

- [ ] **Step 1: Suite completa + coverage**

Run: `cd backend && uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90`
Expected: PASS con cobertura >= 90%.

- [ ] **Step 2: Lint y formato**

Run: `cd backend && uv run ruff check --fix && uv run ruff format`
Expected: sin errores.

- [ ] **Step 3: Typecheck estricto**

Run: `cd backend && uv run ty check`
Expected: sin errores.

- [ ] **Step 4: Gate de seguridad**

Run: `cd /mnt/mydata/projects/proyecto1_diplo && make security`
Expected: verde (16/16 controles); el notificador no altera el catálogo de controles.

- [ ] **Step 5: Escáner de secretos**

Run: `cd /mnt/mydata/projects/proyecto1_diplo && python3 scripts/scan_secrets.py`
Expected: exit 0 (los placeholders vacíos no son secretos).

- [ ] **Step 6: Commit final (si hubo ajustes de lint/formato)**

```bash
cd /mnt/mydata/projects/proyecto1_diplo
git status
git add -A
git commit -m "verifica gates de calidad y seguridad para notificaciones de telegram"
```

---

## Self-Review (coverage del spec)

- §4.1 Config → Task 1. ✅
- §4.2 Servicio `TelegramNotifier` → Task 2. ✅
- §4.3 Formato del mensaje → `build_notification` en Task 2. ✅
- §4.4 Hook en `conversations.py` → Task 3. ✅
- §4.5 Plantillas → Task 4 Step 1. ✅
- §4.6 Terraform → Task 4 Steps 2-6. ✅
- §5 Manejo de errores → tests de `ok=false`/HTTP error/no-JSON/red/disabled en Task 2; fallo de Telegram no rompe el turno en Task 3. ✅
- §6 Testing → Tasks 1-3 (unit + integración + config). ✅
- §7 Seguridad (sin token en logs) → `test_send_does_not_log_token` en Task 2. ✅
- §8 Criterios de aceptación → Task 5 (gates) + Task 3 (no-op sin config). ✅

Sin placeholders, tipos consistentes entre tareas (`TelegramNotifier(token, chat_id)`, `send(text) -> bool`, `build_notification(question, answer) -> str`).
