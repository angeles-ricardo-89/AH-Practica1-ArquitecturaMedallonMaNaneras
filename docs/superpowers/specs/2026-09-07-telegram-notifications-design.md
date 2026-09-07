# Especificación de diseño — Notificaciones de chat por bot de Telegram

**Fecha:** 2026-09-07
**Fuente:** petición directa del operador (dueño de la demo)
**Estado:** Especificación en revisión (spec-review-loop)
**Alcance:** diseño, no implementación

---

## 1. Problema

El operador de la demo quiere recibir notificaciones en su Telegram cada vez que un usuario
hace una consulta en el chat (pregunta + respuesta sintetizada). Hoy no existe ningún canal de
notificación: el operador solo se entera de la actividad si revisa los logs o abre la UI.

**Objetivo:** agregar un notificador de Telegram *best-effort* que envíe la pregunta y la respuesta
de cada turno agéntico al chat del operador, sin acoplar el flujo crítico del chat a la disponibilidad
de Telegram y sin filtrar el token del bot.

---

## 2. Estado actual comprobado (verificado contra el código)

### 2.1 Flujo de chat objetivo

El chat que usa la UI (con login y memoria) es el turno agéntico:

- `api/routers/conversations.py::send_message` (líneas 118-200) orquesta: rate limits,
  persistencia del mensaje del usuario, `run_agent_turn(...)`, persistencia de respuesta y
  `tool_execution`, y retorno de `AgentMessageResponse`.
- `services/agent/executor.py::run_agent_turn` produce `AgentTurnResult` con `question`,
  `answer`, `refusal`, `model_used`, `sources`, `token_usage`, `latency_ms`.
- El endpoint es síncrono (`def`, no `async def`), por lo que FastAPI lo ejecuta en un threadpool
  y soporta `BackgroundTasks` para trabajo posterior a la respuesta.

### 2.2 Configuración

- `config.py::Settings` (pydantic-settings, `env_file=".env"`) concentra toda la configuración.
- Los secretos productivos llegan por env vars inyectadas desde Secret Manager vía Cloud Run
  (ver `infra/terraform/main.tf`).
- `.env.template` y `.env.production.example` ya tienen placeholders `TELEGRAM_BOT_TOKEN=` y
  `TELEGRAM_CHAT_ID=` (commit `e46c820`).

### 2.3 Infraestructura

- `infra/terraform/main.tf` referencia secretos externos con `data "google_secret_manager_secret"`
  y los expone al contenedor Cloud Run con `env { value_source { secret_key_ref {...} } }`.
- `variables.tf` define `existing_secrets` como objeto `{ gemini_api_key, neon_db_url }`.
- `TELEGRAM_BOT_TOKEN` ya existe en Secret Manager; `TELEGRAM_CHAT_ID` es un secreto nuevo que
  el operador debe crear a mano (es su id numérico de chat, obtenible con @userinfobot).

### 2.4 Dependencias

- `httpx>=0.28` ya es dependencia del backend (`backend/pyproject.toml:12`); se reutiliza para
  la llamada a `api.telegram.org`.

---

## 3. Alcance y no alcance

### 3.1 Alcance (se construye en esta fase)

1. Campos `telegram_bot_token` y `telegram_chat_id` en `Settings`.
2. Servicio `services/telegram_notifier.py` con `TelegramNotifier`.
3. Hook en `conversations.py::send_message` que encola la notificación vía `BackgroundTasks`.
4. Placeholders en `.env.template` (ya presentes en `.env.production.example`).
5. Cableado Terraform: referencia a los dos secretos existentes + env vars en Cloud Run.
6. Tests unitarios e integración (mock solo en la frontera HTTP de Telegram).

### 3.2 No alcance

- No se notifica el endpoint RAG legacy `/chat` (solo el turno agéntico de la UI actual).
- No hay webhook, comandos interactivos (`/start`, `/stop`), ni suscripción por usuario.
- No se notifican otros eventos (pipeline, login, errores).
- No se persisten estados de envío ni se reintenta ante fallo (best-effort puro).
- No se cambia el prompt del parser temporal (`temporal_parser.py`), ajeno a esta feature.

---

## 4. Diseño

### 4.1 Configuración (`config.py`)

```python
telegram_bot_token: str = ""
telegram_chat_id: str = ""
```

Ambos vacíos por defecto → notificador deshabilitado (no-op) en local sin configuración.

### 4.2 Servicio `services/telegram_notifier.py`

Clase `TelegramNotifier`:

- `__init__(self, token: str, chat_id: str)`.
- `is_enabled -> bool`: `token and chat_id` no vacíos.
- `send(self, text: str) -> bool`:
  - Si `not is_enabled`, retorna `False` sin llamar a la red.
  - `POST https://api.telegram.org/bot{token}/sendMessage` con `json={"chat_id": chat_id, "text": text}`,
    usando `httpx.Client(timeout=5.0)`.
  - Retorna `True` si `resp.status_code == 200` y `resp.json()["ok"] is True`; en cualquier otro caso
    (error HTTP, timeout, `ok=False`, excepción) loggea `warning` **sin el token ni el chat_id en claro**
    y retorna `False`.
  - Nunca lanza. El token solo aparece en la URL de la petición, jamás en logs.

### 4.3 Formato del mensaje

Texto plano, truncado al límite de Telegram (4096 caracteres):

```
Nueva consulta en el chat

Pregunta: {question[:500]}
Respuesta: {answer[:3000]}
```

- Si `refusal` es verdadero, la respuesta es la negativa generada (ya en `answer`).
- Se usa texto plano (sin emojis ni Markdown) para evitar dependencias de `parse_mode`.

### 4.4 Hook en `conversations.py::send_message`

1. Añadir `background_tasks: BackgroundTasks` como parámetro del endpoint.
2. Tras persistir la respuesta del asistente y antes del `return`, construir el texto y encolar:

```python
notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
background_tasks.add_task(notifier.send, _build_notification(result))
```

3. La notificación corre después de enviar la respuesta HTTP, sin sumar latencia al turno.

### 4.5 Plantillas de configuración

- `.env.template`: añadir bloque:

```
# Telegram (notificaciones best-effort). Token y chat id desde Secret Manager en prod.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 4.6 Terraform

- `variables.tf`: ampliar `existing_secrets` a `{ gemini_api_key, neon_db_url, telegram_bot_token, telegram_chat_id }`.
- `main.tf`:
  - `data "google_secret_manager_secret" "telegram_bot_token"` y `"telegram_chat_id"`.
  - Dos bloques `env { name = "TELEGRAM_BOT_TOKEN" ... value_source { secret_key_ref } }` (idem `TELEGRAM_CHAT_ID`).
- Documentar en `terraform.tfvars.example` que `TELEGRAM_CHAT_ID` debe crearse manualmente en
  Secret Manager (valor = id numérico del chat destino).

---

## 5. Manejo de errores y casos borde

| Caso | Comportamiento |
|---|---|
| Sin token o sin chat_id | `is_enabled=False` → no-op silencioso (sin red, sin warning) |
| Telegram caído / timeout / HTTP != 200 / `ok=false` | `warning` en log, `send` retorna `False`, el turno NO se ve afectado |
| Token inválido (401 de Telegram) | `warning` (sin token en claro), `False` |
| Respuesta más larga que el límite | truncada a 3000 + pregunta a 500; nunca excede 4096 |
| `BackgroundTasks` falla al ejecutarse | el error se registra por FastAPI/logs; no afecta la respuesta ya enviada |

---

## 6. Testing (Gate Q / Gate I)

Mocks **solo** en la frontera HTTP de Telegram (servicio externo), nunca de servicios internos.

### 6.1 Unitarios `tests/test_telegram_notifier.py`

- `is_enabled` falso sin token o sin chat_id; `send` retorna `False` sin tocar la red.
- `send` construye la URL y el body correctos (mock de `httpx.Client`/`MockTransport`).
- `send` retorna `True` con `200 {"ok": true}`.
- `send` retorna `False` ante `ok=false`, status != 200, timeout y excepción.
- El log de error no contiene el token ni el chat_id.
- Truncado: pregunta y respuesta respetan los límites y el total <= 4096.

### 6.2 Integración `tests/test_api/test_conversations.py`

- Un turno normal dispara la notificación (Telegram mockeado en su frontera HTTP) con pregunta y respuesta.
- Un fallo de Telegram (mock devuelve 500) NO rompe el turno: la respuesta del agente se devuelve igual.
- Sin credenciales configuradas, el turno corre sin intentar contactar a Telegram.

### 6.3 Config `tests/test_config.py` (o equivalente)

- `telegram_bot_token` y `telegram_chat_id` se leen de env y tienen default vacío.

---

## 7. Seguridad

- **Secreto:** el token vive en Secret Manager; jamás se loggea, se devuelve ni se persiste en BD.
- **Exfiltración:** el contenido (pregunta + respuesta) sale a un servicio externo (Telegram). Es un
  tradeoff consciente solicitado por el operador y queda documentado aquí.
- **SSRF:** la URL destino es fija (`api.telegram.org`); no hay entrada del usuario que construya la URL.
- **Gateway saliente:** Cloud Run con `max-instances=1`; la llamada es saliente por HTTPS, sin cambios
  de ingreso ni de permisos IAM.
- **Escáner de secretos:** `scripts/scan_secrets.py` debe seguir pasando; los placeholders vacíos de
  `.env.template`/`.env.production.example` no contienen secretos reales.

---

## 8. Criterios de aceptación

1. Con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` configurados, cada turno agéntico envía una
   notificación con pregunta y respuesta al chat destino.
2. Sin configuración, el chat funciona idéntico (no-op, sin red).
3. Un fallo de Telegram no altera el turno del chat (best-effort).
4. `make test-backend`, `ruff`, `ty`, `make security` verdes; cobertura >= 90%.
5. `terraform validate`/`plan` limpios con los dos secretos referenciados.
