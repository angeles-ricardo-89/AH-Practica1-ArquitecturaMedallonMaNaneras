# Especificación de diseño — Endurecimiento de seguridad, gate perpetuo e inspector

**Fecha:** 2026-09-05
**Fuente:** `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` §13 y `docs/superpowers/specs/2026-09-05-agentic-memory-auth-design.md` §15
**Estado:** Especificación en revisión (spec-review-loop)
**Alcance:** diseño, no implementación

---

## 1. Problema

El PRD 3.0 (§13) y la spec de diseño agéntico (§15) enumeran amenazas y controles basados en OWASP Top 10:2025 y OWASP Top 10 for LLM Applications 2026. Esos controles quedaron como promesas aspiracionales: no existe un gate perpetuo que los vigile, no existe un inspector de seguridad que los materialice, y varios controles nunca se implementaron en código. Concretamente, hoy:

- No hay middleware de headers seguros (`X-Content-Type-Options`, `Referrer-Policy`, CSP, HSTS).
- `/docs`, `/redoc` y `/openapi.json` quedan expuestos en cualquier `APP_ENV`.
- No existe middleware CORS alguno.
- El handler global de `RuntimeError` (`main.py:54`) devuelve `str(exc)`, filtrando detalle interno al cliente.
- No hay límite global de tamaño de body ni timeouts de base de datos explícitos.
- No hay escaneo de secretos automatizado.
- No hay skill de seguridad, gate de seguridad ni inspector que mapee amenaza→control→prueba.

**Objetivo:** (1) crear un gate perpetuo de seguridad que bloquee cuando un control materializado carezca de prueba que lo ejercite; (2) crear un inspector determinista que reporte el cumplimiento OWASP por control; (3) implementar los controles que hoy son promesas; (4) crear las skills atómicas de seguridad; (5) crear el set de pruebas de seguridad (unit→integración→e2e) estrictamente acotado al diseño de este sistema.

---

## 2. Estado actual comprobado (verificado contra el código)

### 2.1 Controles ya materializados (se preservan y se vigilan)

| Control | Dónde | Evidencia |
|---|---|---|
| JWT HS256 con claims `sub/iat/exp/iss/aud` | `services/security.py:44-73` | `create_access_token` / `decode_access_token` |
| Secreto JWT/CSRF ≥32 chars exigido en producción | `services/security.py:20-33` | `resolve_jwt_secret` / `resolve_csrf_secret` lanzan `RuntimeError` en prod |
| Argon2 vía `pwdlib` | `services/security.py:36-41` | `hash_password` / `verify_password` |
| Cookie `HttpOnly` + `SameSite=Strict` + `Secure`(prod) | `api/routers/auth.py:91-99` | `response.set_cookie(...)` |
| Mensaje genérico en login fallido | `api/routers/auth.py:72` | `HTTPException(401, "Invalid credentials")` |
| CSRF por HMAC (`user_id:iat`) + header `X-CSRF-Token` | `services/security.py:76-83` + `api/deps.py:92-100` | `require_csrf` |
| Rate limits (login 5/min, chat 10/min, daily 100) en PostgreSQL atómico | `services/rate_limit.py` + `api/routers/auth.py:49-62` + `conversations.py:144-153` | `INSERT ... ON CONFLICT DO UPDATE` |
| IP guardada como HMAC, no en claro | `api/routers/auth.py:37-38` | `hmac_digest(...)` |
| Todos los routers protegidos salvo `health` y `auth` | `main.py:32-45` | `dependencies=protected` |
| Sanitización de salida Markdown con DOMPurify | `frontend/src/utils/markdown.ts` + `frontend/tests/utils/markdown.test.ts` | `DOMPurify.sanitize(marked.parse(...))` |
| IDs públicos deterministas (HMAC), sin UUID | `services/security.py:86-88` | `generate_public_id` |

### 2.2 Controles prometidos pero NO materializados (a implementar)

| # | Control prometido | Fuente | Gap |
|---|---|---|---|
| H1 | Headers seguros (`X-Content-Type-Options`, `Referrer-Policy`, CSP, HSTS en prod) | spec §13.1 "controles complementarios" | No existe middleware |
| H2 | OpenAPI/Swagger deshabilitados en producción | spec §9.3 | `/docs`/`/redoc`/`/openapi.json` abiertos siempre |
| H3 | CORS de origen exacto | spec §13.1 A02 | No existe middleware CORS |
| H4 | Errores saneados (sin stack traces ni detalle interno) | spec §13.1 A10/LLM08 | `main.py:54` devuelve `str(exc)` |
| H5 | Límites de tamaño + timeouts de BD/modelo | spec §10, §13.1 A10/LLM06 | Sin límite global de body; `psycopg.connect` sin timeouts |
| H6 | Escaneo de secretos pre-publicación | spec §13 "escaneo de secretos antes de publicar" | No existe |

### 2.3 Timeouts existentes (contexto para H5)

- `services/agent/llm.py:22` usa `httpx.Client(timeout=60.0)`.
- `services/temporal_parser.py:94` usa `httpx.Client(timeout=30.0)`.
- `services/rag_search.py:28` usa `httpx.Client()` (timeout por defecto de httpx, 5s).
- `psycopg.connect(...)` en `services/memory.py`, `services/agent/tools.py`, `services/rate_limit.py`, `api/routers/auth.py` **sin** `connect_timeout` ni `statement_timeout`.

### 2.4 Cobertura de pruebas de seguridad actual

- `backend/tests/test_security.py`: 7 tests unitarios (JWT roundtrip/expiry, CSRF roundtrip, secretos en prod, hash/verify). **Sin** tests de headers, de error sanitizado, de body size, ni de CSRF a nivel HTTP.
- `backend/tests/test_api/test_auth.py`, `test_conversations.py`: cubren auth/aislamiento a nivel HTTP+Postgres.
- `backend/tests/e2e/test_e2e_smoke.py`: smoke E2E (login→turno), con `pytest.mark.e2e`.
- `frontend/tests/utils/markdown.test.ts`: sanitización de salida.

---

## 3. Alcance y no alcance

### 3.1 Alcance (se construye en esta fase)

1. Gate perpetuo `GATE-SEC` con catálogo de controles y regla de bloqueo.
2. Inspector determinista `backend/scripts/security_check.py` + reporte.
3. Implementación de controles H1–H6.
4. Skills atómicas de seguridad (6 de dominio + 2 técnicas).
5. Set de pruebas de seguridad unit→integración→e2e, cada una ligada a un control vía marcador.
6. Escáner de secretos determinista `scripts/scan_secrets.py`.

### 3.2 No alcance

- No se cambia la arquitectura agéntica ni los flujos existentes.
- No se añaden frameworks de seguridad nuevos (se usa el stack existente: FastAPI/Starlette, Pydantic, psycopg, vitest).
- No se introducen pruebas de amenazas que no aplican al diseño (p. ej. SSRF a internet — el sistema no busca en la web; SQL injection vía tools — las tools no aceptan SQL; búsqueda web — rechazada en PRD §7.4).
- No se implementan WAF, IDS, ni infraestructura de red (fuera de alcance de un MVP de demo).
- No se modifica el modelo de datos ni las migraciones existentes.

---

## 4. Decisiones de diseño (confirmadas con el usuario)

1. **Gate perpetuo nuevo `GATE-SEC`** (no plegado a Gate Q), con comando `make security` (bloquea) y `make security:report` (informa).
2. **Regla de bloqueo:** el gate bloquea si existe un control materializado sin una prueba que lo ejercite, documentada en el catálogo. **Sin umbral numérico de cobertura propio** para el código de seguridad (se hereda el ≥90% global de Gate Q).
3. **Catálogo de controles como fuente de verdad:** `governance/security-controls.yaml` (no hardcodeado en el script).
4. **Inspector determinista:** `backend/scripts/security_check.py`, corre con `uv run`.
5. **Marcadores explícitos de trazabilidad prueba↔control:**
   - Backend: `pytest.mark.security("<ID>")` (registrado en `pyproject.toml` para evitar warnings).
   - Frontend: comentario `// security: <ID>` en el archivo de test.
6. **Skills atómicas:** 6 skills de amenaza en `domain/` que referencian skills técnicas existentes + 2 skills técnicas nuevas (`security_headers.md`, `security_testing.md`).
7. **Escáner de secretos:** `scripts/scan_secrets.py` determinista (regex + lista de patrones + chequeo de archivos rastreados por git).
8. **CORS cerrado por defecto:** el middleware solo permite orígenes listados explícitamente en configuración; vacío → sin acceso cross-origin (fail-closed). No se usa `*`.
9. **CSP en producción únicamente:** los headers no rompen el dev de Vite (HMR/inline). En local se aplican `nosniff` + `Referrer-Policy`; en producción se añaden CSP + HSTS.

---

## 5. Gate de seguridad (GATE-SEC)

### 5.1 Documento de criterios

`governance/GATE-SEC-SECURITY.md` define (estructura análoga a `GATE-S-SPEC-QUALITY.md`):

- **Propósito:** ningún control OWASP materializado queda sin prueba que lo vigile.
- **Activación:** todo commit/checkpoint de feature que toque auth, memoria, agente, UI, config, o que introduzca un control de seguridad nuevo.
- **Criterio de salida:** `make security` sale con código 0 (catálogo completo y marcadores presentes en todos los stacks).
- **Regla de bloqueo:**
  ```
  [BLOQUEO] → si un control listado en governance/security-controls.yaml no tiene al menos
              una prueba/chequeo que lo ejercite y que esté registrada en el catálogo.
  [BLOQUEO] → si algún archivo de prueba referenciado en el catálogo no existe.
  [BLOQUEO] → si un archivo backend referenciado no contiene pytest.mark.security("<ID>").
  [BLOQUEO] → si un archivo frontend referenciado no contiene "// security: <ID>".
  [BLOQUEO] → si scripts/scan_secrets.py encuentra un secreto rastreado por git.
  ```
- **Relación con otros gates:** GATE-SEC se ejecuta dentro del ciclo de Gate Q; `make lint`/`make test-backend` no sustituyen a `make security`.

### 5.2 Catálogo de controles

`governance/security-controls.yaml` declara, por control:

```yaml
controls:
  - id: "A07"                       # identificador canónico OWASP
    title: "Authentication Failures"
    family: "security-auth-jwt"     # referencia a la skill de dominio
    control: "mensaje genérico, límite de login, expiración JWT"
    backend_tests: ["tests/test_api/test_auth.py"]
    frontend_tests: []
    checks: []
  ...
```

- `backend_tests`: rutas relativas a `backend/` que deben contener `pytest.mark.security("<ID>")`.
- `frontend_tests`: rutas relativas a `frontend/` que deben contener `// security: <ID>`.
- `checks`: chequeos estáticos (ej. `secrets-scan`, `lockfiles`, `docs-disabled-prod`) que el inspector ejecuta directamente.

### 5.3 Controles materializados (catálogo final, no exagerado)

Solo se listan controles que aplican al diseño y quedan materializados en código. Los IDs siguen a OWASP; se añaden dos IDs propios (`CSRF`, `HDRS`) para controles que no tienen ID OWASP único.

| ID | Control | Prueba/chequeo que lo vigila |
|---|---|---|
| A07 | Autenticación: mensaje genérico, límite login 5/min, expiración JWT | `tests/test_api/test_auth.py` (HTTP real + Postgres) |
| A04 | Criptografía: secreto fuerte en prod, Argon2, flags de cookie | `tests/test_security.py` + `tests/test_api/test_auth.py` |
| CSRF | Token CSRF obligatorio en operaciones con estado | `tests/test_api/test_auth.py` (403 sin/wrong token) |
| A01 | Control de acceso: propiedad por JWT, 404 en conversación ajena, aislamiento | `tests/test_api/test_conversations.py` + matriz de aislamiento |
| A05 | Inyección: SQL parametrizado, tools sin SQL | `tests/test_agent/test_tools.py` (rechazo de entradas inválidas) |
| LLM01 | Prompt injection: corpus como dato, allowlist de 3 tools | `tests/test_agent/test_planner.py` / `test_executor.py` (tool no permitida → rechazo) |
| LLM03 | Agencia excesiva: máx. 2 tools, parámetros estrictos | `tests/test_agent/test_executor.py` |
| LLM10 | Manejo de salida: sanitización Markdown/HTML | `frontend/tests/utils/markdown.test.ts` |
| LLM08 | Exposición de contexto: errores saneados, sin `str(exc)` | `tests/test_security.py` (handler sin detalle interno) |
| A02/HDRS | Configuración: headers seguros, docs deshabilitadas en prod, CORS exacto | `tests/test_security.py` (headers + docs prod + CORS) |
| A10/LLM06 | Condiciones excepcionales: límite de body, timeouts BD/modelo | `tests/test_security.py` (413 por body, timeouts configurados) |
| A09 | Logging: sin secretos ni contenido en logs | `tests/test_api/test_auth.py` (nuevo test: login fallido no loguea/ecolea la contraseña) |
| A03 | Cadena de suministro: lockfiles presentes, dependencias fijadas | chequeo estático `lockfiles` |
| H6 | Secretos: no rastreados por git | chequeo estático `secrets-scan` |

### 5.4 Mecanismo de marcadores

- **Backend:** registrar en `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  markers = ["security: prueba de control de seguridad OWASP", "e2e: ..."]
  ```
  Cada archivo de test de seguridad declara al inicio `pytestmark = pytest.mark.security("<ID>")`.
- **Frontend:** cada archivo de test de seguridad incluye `// security: <ID>` como primera línea o en el bloque `describe`.
- **Inspector:** carga el YAML; para cada control verifica (a) que los archivos existan y (b) que contengan el marcador correspondiente; ejecuta los `checks`; recolecta el resultado en el reporte.

---

## 6. Inspector determinista

### 6.1 `backend/scripts/security_check.py`

- Argumentos: `--report` (solo reporta, exit 0 siempre), `--check` (default: bloquea con exit 1 si hay huecos).
- Lógica:
  1. Cargar `governance/security-controls.yaml`.
  2. Por control: validar existencia de cada `backend_tests`/`frontend_tests` y presencia del marcador correcto (lectura de texto; no requiere levantar Postgres).
  3. Ejecutar `checks` estáticos: `secrets-scan` (invoca `scripts/scan_secrets.py`) y `lockfiles` (verifica `backend/uv.lock` y `frontend/pnpm-lock.yaml`). El control de "docs deshabilitadas en prod" se vigila con test de pytest (A02/HDRS), no con chequeo estático.
  4. Emitir reporte en texto: matriz `ID | título | control | prueba | estado (OK/FAIL)`.
- **Determinista:** sin heurísticas de nombres; solo catálogo + marcadores + existencia de archivos + checks.
- **Sin red ni Postgres:** el inspector no levanta el stack; los `checks` y la verificación de marcadores son estáticos.

### 6.2 Comandos Makefile

```make
security:          # = uv run python scripts/security_check.py --check  (bloquea)
security-report:   # = uv run python scripts/security_check.py --report (informa)
```

Ambos hacen `cd backend` (misma regla que el resto de targets por el `.env` relativo al CWD).

---

## 7. Skills atómicas de seguridad

### 7.1 Skills de dominio (`domain/`, 6 archivos)

Cada skill sigue el formato de las skills de dominio existentes (responsabilidad + referencia a la tech skill que usa). Contienen: amenaza OWASP concreta, control específico, cómo se materializa en este código, y **la prueba/chequeo que lo vigila**.

| Skill | Amenazas | Control materializado | Prueba que lo vigila |
|---|---|---|---|
| `security-auth-jwt.md` | A07, A04 | JWT HS256, Argon2, cookie HttpOnly+SameSite+Secure, mensaje genérico, login rate-limit | `test_auth.py`, `test_security.py` |
| `security-csrf.md` | CSRF | token HMAC `user_id:iat` en header, `require_csrf`, SameSite como defensa en profundidad | `test_auth.py` |
| `security-access-control.md` | A01 | propiedad derivada del JWT, filtros `user_id`+`conversation_id`, ajena→404 | `test_conversations.py`, matriz aislamiento |
| `security-injection.md` | A05, LLM01, LLM03 | SQL parametrizado, allowlist de 3 tools, plan JSON validado, máx. 2 ejecuciones, corpus como dato | `test_agent/*` |
| `security-output-handling.md` | LLM10, LLM08 | DOMPurify en frontend, errores saneados sin `str(exc)` | `markdown.test.ts`, `test_security.py` |
| `security-headers-config.md` | A02, A06, A10, LLM06, A09, A03 | headers seguros, docs deshabilitadas en prod, CORS exacto, límite de body, timeouts, logging sin secretos, lockfiles | `test_security.py`, checks estáticos |

### 7.2 Skills técnicas (`tech/`, 2 archivos nuevos)

- `security_headers.md`: cómo implementar el middleware de headers/CSP/CORS y deshabilitar docs en prod en FastAPI/Starlette (con snippet concreto para este repo).
- `security_testing.md`: cómo escribir pruebas de seguridad con marcadores `pytest.mark.security` / `// security:` y cómo declarar controles en el catálogo YAML + correr `make security`.

Las 6 skills de dominio referencian a las skills técnicas existentes (`autenticacion_jwt.md`, `fastapi_pydantic_typer.md`, `vue3_pinia_tailwind.md`, `duckdb_pgvector.md`, `testing_qa.md`) y a las 2 nuevas donde aplica.

---

## 8. Controles de endurecimiento a implementar (H1–H6)

### 8.1 H1 — Middleware de headers seguros

Nuevo middleware (`backend/src/lakehouse/api/security_headers.py` o función en `main.py`) que añade:

- Siempre: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- Producción: `Strict-Transport-Security: max-age=31536000; includeSubDomains` y `Content-Security-Policy` con:
  ```
  default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; connect-src 'self'; font-src 'self';
  frame-ancestors 'none'; base-uri 'self'; form-action 'self'
  ```
- La CSP de producción debe verificarse con un smoke en navegador (el build Vue+ECharts debe seguir funcionando); si un componente requiere un ajuste puntual (p. ej. `style-src` para estilos inline de ECharts), se documenta y se actualiza la política en este mismo control, **sin degradarla a `unsafe-eval` ni `unsafe-inline` en script-src**.

### 8.2 H2 — Docs deshabilitadas en producción

En `main.py`, al construir `FastAPI`, `docs_url`/`redoc_url`/`openapi_url` se anulan cuando `app_env == "production"`. Se añade test: en prod, `GET /docs` y `/openapi.json` → `404`.

### 8.3 H3 — CORS de origen exacto

Middleware CORS con lista explícita `cors_allowed_origins` (nuevo setting, default vacío). Vacío → ningún origen externo habilitado (fail-closed). En local no se necesitan orígenes externos (Vite proxya `/api`); en producción el frontend es mismo origen. Se añade test: un request con `Origin` no permitido no recibe `Access-Control-Allow-Origin`; con origen permitido lo recibe exacto.

### 8.4 H4 — Errores saneados

Sustituir el handler `main.py:54` para que responda con un mensaje genérico (`{"detail": "Internal server error"}`) **tanto en producción como en local**, **sin** incluir `str(exc)` ni el tipo de la excepción. El detalle del error se registra únicamente en `logging` (que a su vez no loguea secretos, ver A09). Se añade test que provoca un `RuntimeError` y verifica que el body no contiene el texto de la excepción.

### 8.5 H5 — Límites de tamaño y timeouts

- **Body size:** middleware que rechaza `Content-Length > max_request_body_bytes` (nuevo setting, default `65536` = 64 KB) con `413`. No aplica a `GET`/`HEAD`.
- **Timeouts de BD:** centralizar la construcción de `psycopg.connect(...)` para incluir `connect_timeout` (nuevo setting, default `5`) y `options='-c statement_timeout=…'` (default `10s`). Aplicar en los puntos de conexión de `memory.py`, `tools.py`, `rate_limit.py`, `auth.py`, `conversations.py`.
- **Timeouts de modelo:** `rag_search.py` pasa de `httpx.Client()` a `httpx.Client(timeout=<setting>)` explícito; `llm.py` y `temporal_parser.py` ya tienen timeout, se mantienen y se hacen configurables si es trivial.
- Se añade test: el middleware devuelve `413` con body grande; el setting de timeout de BD/modelo tiene valor por defecto documentado.

### 8.6 H6 — Escáner de secretos

`scripts/scan_secrets.py` determinista:

- Patrones: claves API conocidas (`GEMINI_API_KEY`, `DATABASE_URL` con credenciales, `jwt_secret`, `csrf_secret`), cadenas largas tipo secreto (≥32 chars hex/base64), `password=`, `-----BEGIN` (claves privadas).
- Recorre archivos rastreados por `git ls-files`, excluye `docs/`, `*.lock`, `.env.template` (con regla específica: verifica que el template no contenga valores reales, solo placeholders).
- Exit 1 si halla un match; el gate lo invoca como `check` `secrets-scan`.

---

## 9. Estrategia de pruebas de seguridad

### 9.1 Backend — unitarias (`tests/test_security.py`, se amplía)

- Headers presentes (nosniff, Referrer-Policy, X-Frame-Options) en respuesta; HSTS/CSP solo en prod.
- `/docs` y `/openapi.json` → `404` en prod.
- CORS: origen no permitido sin `ACAO`; origen permitido con `ACAO` exacto.
- Handler de `RuntimeError` sin filtrar detalle interno.
- Body size → `413`.
- Secretos en prod (ya existente), JWT/CSRF roundtrip (ya existente).
- Marcador `pytestmark = pytest.mark.security("<ID>")` por familia.

### 9.2 Backend — integración (`tests/test_api/*`, HTTP real + Postgres)

- `test_auth.py`: login genérico, flags de cookie, 429 tras 6 intentos, CSRF 403 sin token, y no-eco de contraseña en logs (A09).
- `test_conversations.py`: aislamiento (ajeno→404), matriz 2×2.
- Se ligan a controles A07/A04/CSRF/A01/A09 con marcadores.

### 9.3 Backend — E2E sin mocks (`tests/e2e/`)

- Smoke actual ya cubre login→turno. Se añade una aserción de aislamiento entre los dos usuarios demo (usuario 2 no lee conversación de usuario 1 → 404) bajo `pytest.mark.e2e`. Se introducen las variables de entorno `E2E_USERNAME2`/`E2E_PASSWORD2` (credenciales del segundo usuario demo); si no están definidas, esa aserción se salta (SKIP) sin afectar el resto del smoke. No se mockea nada interno.

### 9.4 Frontend — unitarias (`frontend/tests/utils/markdown.test.ts`)

- Ya cubre sanitización (script/onerror). Se añade marcador `// security: LLM10` y un caso extra: URL de esquema `javascript:` es eliminada por DOMPurify.

### 9.5 Gates

- `make security` verde (catálogo completo, marcadores presentes, checks OK).
- `make lint`, `make typecheck-backend`, `make test-backend` (cobertura ≥90% global), `pnpm typecheck`, `pnpm test:unit`.

---

## 10. Definición de terminado

La fase se considera completa cuando:

1. `make security` corre verde: todo control del catálogo `security-controls.yaml` tiene prueba/chequeo que lo ejercita y está documentado.
2. `make security-report` emite la matriz completa sin huecos.
3. H1–H6 están implementados con sus pruebas correspondientes.
4. Las 6 skills de dominio y 2 técnicas existen y están referenciadas desde `AGENTS.md` (regla de convivencia: "prohibido modificar archivos de skill sin actualizar AGENTS.md").
5. `GATE-SEC` está documentado en `AGENTS.md` como gate perpetuo.
6. `ruff`, `ty`, `pytest` (≥90%), `pnpm typecheck`, `pnpm test:unit` en verde.
7. `scripts/scan_secrets.py` no reporta secretos en el repo.

---

## 11. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| CSP rompe el frontend Vue/ECharts en producción | Política conservadora + smoke en navegador; ajustes puntuales documentados sin habilitar `unsafe-eval` |
| Headers en local rompen HMR de Vite | Headers estrictos solo en prod; local aplica nosniff+Referrer-Policy (no rompen) |
| Timeouts de BD demasiado agresivos | Valores por defecto documentados y configurables; integración real valida el flujo |
| El inspector es frágil (falsos negativos) | Determinista: catálogo YAML + marcadores + existencia de archivo; sin heurísticas |
| `scan_secrets.py` produce falsos positivos | Lista de exclusiones explícita (`docs/`, locks, placeholders de template) |

---

## 12. Preguntas o riesgos abiertos

Ninguno bloqueante. Todos los puntos de decisión quedaron resueltos en el diálogo socrático previo: opción 3 (gate+inspector+endurecimiento), GATE-SEC nuevo, sin umbral numérico propio, 6 skills de dominio + 2 técnicas, marcadores nativos por stack + catálogo YAML central, y `scripts/scan_secrets.py` determinista.

---

## Referencia a Gate S

- Brainstorming/socrático: ejecutado (diálogo de 7 preguntas, una a una) antes de esta especificación.
- `spec-review-loop`: pendiente de ejecutar sobre este documento.
- Sin TBD/TODO/placeholders sin resolver.
