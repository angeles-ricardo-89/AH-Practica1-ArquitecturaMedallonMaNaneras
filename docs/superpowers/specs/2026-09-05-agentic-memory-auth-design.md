# Especificación de diseño — Agente de investigación, memoria conversacional y autenticación

**Fecha:** 2026-09-05
**PRD fuente:** `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (agregado al PRD 2.0, que prevalece como antecedente)
**Estado:** Especificación aprobada, pendiente de plan de implementación
**Alcance:** diseño, no implementación

---

## 1. Problema y usuarios

**Problema.** Las transcripciones de las conferencias matutinas contienen declaraciones dispersas entre fechas, participantes y temas. El chat RAG actual (flujo fijo de búsqueda + generación) no permite: continuar una investigación entre turnos, distinguir una sesión de otra, explorar temas emergentes del corpus, explicar qué herramienta se usó ni negarse a concluir cuando el corpus no respalda una afirmación.

**Usuarios.** Periodistas y analistas que necesitan localizar evidencia verificable y entender su procedencia. En esta entrega son dos usuarios demo (no hay registro público).

**Valor.** Reducir el tiempo para localizar declaraciones y convertir resultados dispersos en una respuesta rastreable. El agente no sustituye el criterio periodístico: organiza evidencia, cita procedencia y se niega a concluir sin respaldo.

---

## 2. Estado actual comprobado (verificado contra el código)

Las siguientes afirmaciones se verificaron directamente sobre el repositorio en la fecha de corte.

### 2.1 Lo que ya funciona (se preserva)

- Pipeline medallón Bronze→Silver→Gold (ingesta, parsing determinista, enriquecimiento con embeddings).
- FastAPI + Vue 3 + Pinia; PostgreSQL + pgvector con índice HNSW.
- Búsqueda RAG con filtro temporal por lenguaje natural (`TemporalParser`).
- Clustering UMAP + HDBSCAN y etiquetado de clusters (`/clusters/latest`, `/clusters/{run_id}`).
- Embeddings locales vía Ollama (`embeddinggemma`), generación vía llama.cpp.
- Suite de pruebas con cobertura **97.27%** (ver §2.3).

### 2.2 Inconsistencias confirmadas (a corregir en P0.1)

| # | Hallazgo | Evidencia | Riesgo |
|---|----------|-----------|--------|
| I1 | Contrato `token_usage` roto: backend devuelve `{prompt, completion, total}`; frontend lee `total_tokens` | `backend/.../api/routers/chat.py:147-151` vs `frontend/src/stores/chat.ts:59` | UI reporta consumo 0/vacío |
| I2 | Límite de contexto divergente: `config.py` usa 10000; UI/docs usan 8192 | `backend/.../config.py:24` (`max_context_tokens=10000`) vs `frontend/src/stores/chat.ts:22` (`MAX_CONTEXT_TOKENS=8192`) | Expectativa falsa al usuario |
| I3 | `conversation_id` aceptado pero no usado; no se carga historial | `schemas/chat.py:6` acepta el campo; `chat.py` nunca lo lee; `ContextBuilder` soporta `history` pero `chat.py` no lo pasa | Memoria inexistente |
| I4 | Modelo generativo nombrado de 3 formas: `gemma-4-12b` (config default), `gemma4` (template), `Gemma4-26B` (README); embedding `embeddinggemma` vs `nomic-embed-text` (template/skills) | `config.py:21,18`; `.env.template:13,16`; `README.md:128,142` | Ejecución no reproducible |
| I5 | Evaluación RAG con respuestas de marcador (`"Respuesta."`) y puntuaciones 0.0, presentada como "Completo" | `backend/data/lakehouse/logs/evaluate_rag_results.json` (`avg_fidelity=0.0`, `answer="Respuesta."`) vs `README.md:111` | Evidencia académica inválida |
| I6 | README declara "Interrupcion graceful | Completo | CP-16 completado" pero el plan lo tiene pendiente | `README.md:113` vs `IMPLEMENTATION_PLAN.md:438` (CP-16 `[ ]`) | Estado del proyecto no confiable |
| I7 | Filtros aplicados DESPUÉS del top-k vectorial en `/search` | `backend/.../api/deps.py:23-34` (busca primero, filtra en Python después) | Pérdida de evidencia relevante |
| I8 | Markdown renderizado sin sanitizar (XSS) | `frontend/src/utils/markdown.ts` usa `marked.parse` sin limpieza | Inyección de HTML/JS vía salida del modelo |

### 2.3 Línea base de pruebas (ejecutada en esta fase)

| Chequeo | Resultado |
|---------|-----------|
| Backend `pytest` | **3 failed, 531 passed**, cobertura **97.27%** |
| Backend `ruff check` | 1 error (código comentado en `pipeline/clustering.py:350`) |
| Backend `ty check` | OK |
| Frontend `pnpm typecheck` | OK |
| Frontend `pnpm test:unit` | 43 passed (7 archivos) |

Las 3 fallas provienen todas del desajuste de configuración I2/I4: `test_config.py::test_default_values` (espera `max_context_tokens==8192`), `test_chat.py::test_chat_populates_model_latency_and_tokens` y `test_evaluate_rag.py::test_call_llamacpp_returns_content` (esperan `gemma4`, el default actual es `gemma-4-12b`).

### 2.4 Ausencias confirmadas

- Sin autenticación (solo `GET /health` público; ningún router exige identidad).
- Sin CSRF, sin rate limits, sin `app_user`/`conversation`/`message`/`tool_execution` en la base.
- Sin catálogo de tools ni ciclo de decisión del agente.
- Sin servicio `pipeline` en Docker Compose (solo postgres/backend/frontend); Ollama y llama.cpp corren en el host.
- Sin infraestructura GCP ni Terraform en el repositorio.

---

## 3. Alcance y no alcance

### 3.1 Alcance (P0, no negociable)

1. Corrección de inconsistencias (I1–I8) y línea base verde.
2. Autenticación JWT en cookie `HttpOnly` + CSRF + 2 usuarios demo idempotentes.
3. Memoria conversacional aislada (crear/listar/retomar/borrar, retención 30 días).
4. Agente con exactamente 3 tools de solo lectura y ciclo plan→ejecutar→sintetizar, con negativa sin evidencia.
5. Rate limits compartidos y atómicos en PostgreSQL.
6. Separación estricta de corpus local (EmbeddingGemma) y productivo (Gemini).
7. Pipeline medallón ejecutable y verificable en Docker.
8. Despliegue mínimo Cloud Run + Neon + Gemini mediante Terraform; URL `run.app`.
9. Evidencia académica real (PDF final).

### 3.2 No alcance (P1/P2 o rechazado)

- Registro público, bot de Telegram, búsqueda web, SQL libre, ejecución del pipeline desde el chat, memoria global/perfil permanente, dominio personalizado (P1), pipeline productivo completo en GCP (P1), administración de usuarios (P2).

---

## 4. Decisiones de arquitectura

1. **Sin frameworks agénticos.** Se mantienen FastAPI, Pydantic, Vue, PostgreSQL/pgvector, Ollama/EmbeddingGemma y llama.cpp. No se introducen LangChain, LangGraph, Google ADK ni PydanticAI (ver PRD 3.0 §12).
2. **Agente = capa pequeña de planificación + ejecución segura** sobre los servicios existentes (`rag_search.py`, `clustering`).
3. **Plan JSON validado por Pydantic**, no tool calling nativo del servidor local.
4. **Auth propia con PyJWT + `pwdlib[argon2]`** (patrón FastAPI), sin ORM.
5. **Rate limits en PostgreSQL** (`INSERT ... ON CONFLICT DO UPDATE`), sin Redis.
6. **IaC con Terraform** para el despliegue GCP (decisión nueva de esta fase; no estaba en el PRD 3.0). Herramienta determinista de costo definida en esta fase, construida en P0.6.
7. **IDs deterministas** (HMAC de id interno + secreto servidor) para conversaciones; sin UUID4 (regla del proyecto).
8. **Build único web+API** en Cloud Run bajo el mismo origen (reduce CORS, simplifica cookies).
9. **Nombres canónicos (confirmados por el usuario, 2026-09-05):** modelo generativo local `gemma-4-12b`; `MAX_CONTEXT_TOKENS = 10000`; embedding local `embeddinggemma`. La UI y los docs que aún muestren `8192`, `gemma4` o `Gemma4-26B` se alinean en P0.1.

---

## 5. Modelo de datos

Nuevas tablas (se añaden, no se tocan las existentes):

```
app_user(
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,          -- Argon2
    role TEXT NOT NULL DEFAULT 'demo',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

conversation(
    id BIGSERIAL PRIMARY KEY,
    public_id TEXT UNIQUE NOT NULL,        -- HMAC(id + secreto servidor), determinista
    owner_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL        -- last_activity_at + 30 dias
)

message(
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,  -- redundante para control
    role TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
    content TEXT NOT NULL,
    prompt_tokens INT, completion_tokens INT, total_tokens INT,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

tool_execution(
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    turn_id BIGINT NOT NULL,               -- vincula al message del turno
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL,              -- saneados, sin SQL/URLs libres
    result_count INT NOT NULL,
    duration_ms INT NOT NULL,
    status TEXT NOT NULL,                  -- 'ok' | 'error' | 'fallback'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Reglas de propiedad:** toda lectura/escritura filtra por `conversation_id` + `owner_id`. Conversación ajena → `404`.

---

## 6. Flujo de autenticación

1. Dos usuarios demo se crean de forma idempotente al arrancar (variables de entorno protegidas; nunca en Git/logs).
2. `POST /auth/login` valida con Argon2 y, si es válido, emite:
   - JWT HS256 (secreto ≥ 256 bits), claims `sub`, `iat`, `exp` (60 min), `iss`, `aud`.
   - Token CSRF: valor firmado (HMAC del `jti`/identificador de sesión con el secreto servidor) entregado en el cuerpo del login; se envía en un header dedicado en cada operación con estado y se valida contra la sesión activa.
   - Cookie JWT `HttpOnly`, `Path=/`, sin `Domain`; `Secure` + `SameSite=Strict` en producción, `Secure=false` en local.
3. Login inválido devuelve el mismo mensaje genérico (no distingue usuario inexistente vs contraseña incorrecta).
4. `GET /auth/me` devuelve identidad mínima; `POST /auth/logout` (autenticado + CSRF) borra la cookie.
5. Protección global: todo `/api`, dashboard, clusters, métricas y logs exigen JWT; solo login y `GET /health` son públicos. En producción OpenAPI/Swagger se deshabilitan o requieren auth.
6. CSRF: toda operación con estado valida origen + token CSRF en header; `SameSite` es defensa adicional, no única.

**Criterios:** CA-A01…CA-A06 (PRD §15.1).

---

## 7. Carga y aislamiento de memoria

1. El frontend solo envía `question` + `conversation_id`; el servidor carga el historial autorizado desde la base.
2. El historial se convierte al prompt solo después de comprobar `conversation_id` + `user_id` (del JWT).
3. El `ContextBuilder` recibe el historial cargado del servidor y aplica truncado FIFO contra el límite unificado de contexto (I2).
4. Toda traza/evidencia hereda el propietario de la conversación.
5. Retención 30 días desde `last_activity_at`; cada turno válido renueva `last_activity_at` y `expires_at`. Limpieza programada u oportunista elimina vencidas.
6. Borrado en cascada inmediato; sin residuo en logs de aplicación.

**Criterios:** CA-M01…CA-M06 (PRD §15.2).

---

## 8. Ciclo del agente

```
Pregunta autenticada → cargar memoria propia → plan JSON validado → ejecutar tool → (máx. 1 tool más) → responder con evidencia → guardar turno y traza
```

- **Planificador:** Gemma local (offline) o Gemini (producción) devuelve JSON `{tool_name, arguments, motivo}`.
- **Validador:** Pydantic rechaza nombres/tipos/rangos/filtros no permitidos (allowlist de 3 tools).
- **Ejecutor:** llama servicios internos existentes; nunca ejecuta código/SQL/URL del modelo.
- **Sintetizador:** redacta solo con memoria autorizada + resultados de tools.
- **Guardas:** máx. 2 ejecuciones por mensaje, 10 s por tool, límite de filas, límite total de contexto.
- **Reparación:** si el plan no valida → 1 reintento con instrucciones de reparación → fallback seguro a `buscar_declaraciones` (trazable, no simulado).
- **Negativa:** sin evidencia que supere el umbral, responde "No encontré evidencia suficiente…" sin completar con conocimiento general ni web.

**Criterios:** CA-T01…CA-T08 (PRD §15.3).

---

## 9. Contratos exactos de las tres tools

Todas son **funciones internas**, no endpoints públicos. Entradas siempre validadas por Pydantic; nunca SQL, URL, `user_id` ni nombres de tool libres provenientes del modelo.

### 9.1 `buscar_declaraciones`

- **Entrada:** `{ "consulta": str (1..2000), "fecha_inicio": date|null, "fecha_fin": date|null, "participante": str|null (1..200), "top_k": int (1..8) }`
- **Salida:** `{ "evidencias": [ { "evidence_id": str, "texto": str, "fecha": date, "participante": str, "conferencia": str, "url": str, "similitud": float(0..1) } ] }`
- **Regla:** filtros relacionales (fecha/participante) se aplican ANTES del ranking vectorial (corrige I7).
- **Errores:** entrada inválida → `422`; corpus vacío → `evidencias: []`; error de BD → `503`.

### 9.2 `explorar_temas`

- **Entrada:** `{ "texto": str|null (0..2000), "limite": int (1..5) }`
- **Salida:** `{ "clusters": [ { "cluster_id": int, "etiqueta": str|null, "terminos": [str], "tamano": int, "cohesion": float|null, "fecha_inicio": date|null, "fecha_fin": date|null } ] }`
- **Regla:** sin `texto`, devuelve clusters por tamaño/calidad; nunca presenta ruido como tema.

### 9.3 `consultar_cluster`

- **Entrada:** `{ "cluster_id": int (>=0), "limite": int (1..8) }`
- **Salida:** `{ "cluster": { "cluster_id": int, "etiqueta": str|null, "tamano": int }, "evidencias": [ { "evidence_id": str, "texto": str, "fecha": date, "participante": str, "url": str, "pertenencia": float|null } ] }`
- **Regla:** cluster se presenta como agrupación algorítmica acompañada de evidencia, nunca como hecho.

**Estado del agente (trace):** cada turno devuelve `tool_executions: [ { tool, arguments, result_count, duration_ms, status } ]` junto con la respuesta.

---

## 10. API propuesta

| Método y ruta | Uso | Acceso |
|---|---|---|
| `GET /health` | Disponibilidad mínima | Público |
| `POST /auth/login` | Cookie JWT + CSRF | Público (limitado) |
| `POST /auth/logout` | Borra cookie | Auth + CSRF |
| `GET /auth/me` | Identidad activa | Auth |
| `GET /config` | Config + límite de contexto unificado (I2) | Auth (antes público) |
| `GET /conversations` | Lista propias no vencidas | Auth |
| `POST /conversations` | Crear | Auth + CSRF |
| `GET /conversations/{id}` | Historial propio | Auth |
| `DELETE /conversations/{id}` | Borrado cascada | Auth + CSRF |
| `POST /conversations/{id}/messages` | Turno del agente | Auth + CSRF + límites |

**Contrato de tokens (unifica I1):** la API devuelve `token_usage: { prompt: int, completion: int, total: int }`; el frontend consume `total`. El campo `total_tokens` se elimina de la **respuesta** de la API (la columna `total_tokens` de la tabla `message` es persistencia interna, no parte del contrato). Se añade una prueba de contrato backend–frontend.

**Cuerpo de pregunta:** máx. 2000 caracteres (PRD §10). Errores saneados: `401`, `403`→`404` (propiedad), `422`, `429` (con `Retry-After`), `503` (modelo no disponible), sin stack traces.

---

## 11. Rate limits

Backend, configurables, contadores compartidos y atómicos en PostgreSQL (sin Redis).

| Recurso | Límite |
|---|---|
| Login | 5 intentos permitidos por minuto por IP+usuario; el 6.º intento en la ventana activa `429` (CA-A05), con bloqueo progresivo |
| Chat/agente | 10/min por usuario |
| Cuota diaria | 100 solicitudes de agente por usuario |
| Tools | 2 ejecuciones por mensaje |
| Búsqueda | 8 evidencias por ejecución |
| Exploración | 5 clusters por ejecución |
| Cuerpo de pregunta | 2000 caracteres |
| Tiempo de tool | 10 s |
| Tiempo total de respuesta | 60 s |

- Ventanas de consumo en PostgreSQL vía `INSERT ... ON CONFLICT DO UPDATE`; IP guardada como HMAC (no en claro); depuración automática.
- `429` con `Retry-After`; ningún reintento interno consume llamadas ilimitadas. Cloud Run `max-instances=1`.

---

## 12. Separación de proveedores e índices

- **Local:** EmbeddingGemma (Ollama) para desarrollo/demo.
- **Productivo:** `gemini-embedding-001` (768 dims, normalización, tareas `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`).
- **Nunca mezclar** espacios vectoriales, aunque compartan 768 dims.
- Metadatos obligatorios por índice: proveedor+modelo, dimensión, tipo de tarea, versión de formato, fecha de construcción, hash del corpus.
- Producción = reindexación TOTAL hacia Neon; el servicio falla al iniciar si la config de consulta no coincide con los metadatos (fallar cerrado).

**Criterios:** CA-R05, CA-R06.

---

## 13. Docker local

- Docker Compose orquesta frontend, backend, PostgreSQL y un servicio/perfil `pipeline`.
- El servicio `pipeline` ejecuta Bronze→Silver→Gold→clustering→etiquetado con el mismo código.
- Ollama/llama.cpp permanecen como runtimes locales del host (GPU/pesos) con dependencias y health checks explícitos.
- `make docker-verify`: verificación única con muestra Bronze congelada, validando salidas por capa.
- Comando documentado para pipeline completo contra corpus real.
- La demo local del agente no llama a Gemini ni a servicios externos.

**Criterios:** CA-D01…CA-D03.

---

## 14. Producción mínima (Terraform)

- Cloud Run único (build web+API, mismo origen), 1 vCPU, concurrencia 10, `max-instances=1`, escala a cero, facturación por solicitud.
- Neon con pgvector, conexión agrupada + TLS.
- Gemini Flash-Lite (generación) y `gemini-embedding-001` (embeddings).
- Secret Manager: `DATABASE_URL`, `GEMINI_API_KEY`, secreto JWT, credenciales demo (≤6 versiones activas).
- Terraform como IaC: estado remoto en GCS, service account con privilegios mínimos, `terraform.tfvars` no commiteado.
- Herramienta determinista de costo (definida en `costo_infraestructura_gcp.md`, construida en P0.6) valida ~USD 0 antes de cada cambio de despliegue.
- URL `run.app` es el entregable; dominio propio pasa a P1.

**Criterios:** CA-D04…CA-D08.

---

## 15. Amenazas y controles

Cada control tiene prueba o criterio asociado. Fuentes: OWASP Top 10:2025, OWASP LLM 2025, OWASP Agentic 2026 (referencia).

| # | Amenaza | Control | Prueba / criterio |
|---|---|---|---|
| 1 | Broken Access Control (A01) | Propiedad derivada del JWT; consultas por `user_id`+`conversation_id`; ajena→404 | CA-M03, CA-M04, matriz 2×2 |
| 2 | Security Misconfiguration (A02) | Config local/prod separada, docs/Swagger deshabilitados en prod, CORS origen exacto, headers seguros | test de headers; `APP_ENV=prod` sin `/docs` |
| 3 | Supply Chain (A03) | `uv.lock`/`pnpm-lock.yaml`, versiones fijadas, imagen base fijada | `make lint` + revisión de dependencias |
| 4 | Cryptographic Failures (A04) | TLS, cookies seguras, secretos fuera del repo, Argon2, JWT secreto fuerte | CA-A02, CA-A06 |
| 5 | Injection (A05) | SQL parametrizado; ninguna tool acepta SQL; corpus como dato | CA-T05, pruebas de prompt malicioso |
| 6 | Insecure Design (A06) | Tools solo lectura, 2 pasos máx., sin efectos externos | CA-T04, CA-T05 |
| 7 | Auth Failures (A07) | Mensajes genéricos, límite de login, expiración | CA-A01, CA-A05 |
| 8 | Data Integrity (A08) | Hashes/metadatos de corpus/modelo; pipeline idempotente | CA-R05, re-ejecución idempotente |
| 9 | Logging Failures (A09) | Eventos de login, 401/403/429, tool, errores; sin secretos ni texto completo | test de logs sin secretos |
| 10 | Exceptional Conditions (A10) | Fallar cerrado, timeouts, 429/503 claros, sin fallback sin evidencia | CA-T07, pruebas de timeout |
| 11 | Prompt Injection (LLM01) | Separar instrucciones/memoria/corpus/resultados; allowlist | CA-T06 |
| 12 | Sensitive Info Disclosure (LLM02) | Sin secretos en prompts; historial por propietario; logs sin contenido; aviso Gemini gratuito | CA-A06, test de aislamiento |
| 13 | Excessive Agency (LLM06) | 3 tools lectura, params estrictos, 2 ejecuciones, sin efectos externos | CA-T04, CA-T05 |
| 14 | Data/Model Poisoning (LLM05) | Bronze inmutable, hashes, procedencia, reconstrucción controlada de Gold | CA-R05, re-construcción |
| 15 | Unbounded Consumption (LLM06) | Rate limits, cuotas, top-k, tokens, timeouts, reintentos, max-instances | pruebas de límites (login/chat/cuota) |
| 16 | Misinformation (LLM07) | Respuesta ligada a evidencia; negativa explícita; cluster ≠ hecho | CA-T07, CA-T08 |
| 17 | Sensitive Information Disclosure (LLM02) | No revela prompts/secretos/memoria ajena; errores saneados | test de 404 + errores sin detalle |
| 18 | Vector Weaknesses (LLM09) | Índices separados, metadatos, filtros previos, umbral y evaluación | CA-R01, CA-R05, CA-R06 |
| 19 | Improper Output Handling (LLM05) | UI escapa Markdown/HTML; URLs validadas contra orígenes permitidos; salida nunca ejecutada | test de sanitización de salida (I8) |

Controles complementarios: CSP restrictiva, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, HSTS en prod, límites de tamaño, timeouts de BD, respuestas sin stack traces, escaneo de secretos pre-publicación.

---

## 16. Migración compatible

- Las nuevas tablas (`app_user`, `conversation`, `message`, `tool_execution`, tablas de rate limits) se **añaden**; no se modifican las tablas existentes de pipeline/medallón.
- Los endpoints existentes (`/search`, `/chat`, `/clusters`, `/embeddings`, `/observability`, `/config`) mantienen sus rutas y respuestas; se les **añade** autenticación (y a `/config` la exposición del límite unificado).
- El endpoint `/chat` legado se conserva durante la transición; el turno agéntico se expone en `POST /conversations/{id}/messages`. Rollback = desactivar el guard global y mantener `/chat` intacto.
- La reindexación productiva crea un índice **nuevo** en Neon; el índice local permanece intacto hasta verificar conteos y checksum.

---

## 17. Observabilidad

- Eventos estructurados con `logging` (niveles por `APP_ENV`), sin `print`.
- Registro de: login correcto/fallido, `401`/`403`/`429`, ejecución de cada tool (nombre, duración, conteo, estado), errores de modelo.
- Prohibido loguear: contraseñas, JWTs, API keys, contenido completo de mensajes o conversaciones, IP en claro (solo HMAC).
- Semaforos/estado del pipeline ya existentes se conservan y quedan tras autenticación.

---

## 18. Estrategia de pruebas

- **Unidad:** claims JWT, expiración, Argon2, CSRF, validación de tools (allowlist), HMAC de IP/conversación.
- **Integración con PostgreSQL vivo:** propiedad y borrado en cascada de conversaciones.
- **Matriz de aislamiento:** 2 usuarios × 2 conversaciones × leer/continuar/borrar.
- **Contrato backend–frontend:** tokens (`total`, no `total_tokens`), errores, respuestas del agente.
- **Prompt injection:** en pregunta, memoria y corpus recuperado.
- **Rate limits:** login, chat, cuota diaria, resultados y pasos.
- **Offline:** agente local sin red hacia Gemini.
- **Smoke test productivo** desde sesión limpia.
- **Negativa sin evidencia** (CA-T07) y **sanitización de salida** (I8).
- Gates: cobertura backend ≥90% (ya en 97.27%), `ruff`, `ty`, `pnpm typecheck`, `pnpm test:unit`.

---

## 19. Rollback

- **Autenticación:** guard global activable/desactivable por `APP_ENV` o feature flag; los endpoints legacy siguen respondiendo si se desactiva el guard.
- **Memoria:** tablas nuevas independientes; borrar tablas o deshabilitar el router de conversaciones no afecta el pipeline.
- **Agente:** el turno agéntico convive con `/chat` legacy; si falla, se redirige a `/chat` sin agente.
- **Terraform/Cloud Run:** `terraform destroy` (o no aplicar) deja intacto el entorno local; el índice local nunca se toca.
- **Todas las migraciones SQL** se escriben reversibles (up/down).

---

## 20. Preguntas o riesgos abiertos

1. **Umbral de evidencia mínima** para la negativa: el PRD dice "umbral definido" sin valor numérico. Propuesta inicial: rechazar la conclusión si ninguna evidencia supera similitud 0.40 (coincide con el ejemplo del README) y requiere validación empírica en la re-evaluación.
2. ~~Identificador canónico del modelo generativo local~~ → **RESUELTO:** `gemma-4-12b`.
3. ~~Valor unificado de `MAX_CONTEXT_TOKENS`~~ → **RESUELTO:** `10000` (se expondrá por `/config` autenticado).
4. **Terraform:** es una herramienta nueva no contemplada en el PRD 3.0; se incorpora por directiva del usuario. Se asume región fija y nivel gratuito; la región concreta queda como variable (default por confirmar).
5. **Mecanismo de limpieza de conversaciones vencidas:** se propone limpieza oportunista + un job simple (cron/Cloud Scheduler) en producción; pendiente de confirmar si basta la oportunista para la demo.
6. **Aviso de nivel gratuito Gemini:** se muestra en la UI; se asume aceptado por el usuario para esta demo (PRD §20).
7. **Prueba "offline" reproducible:** la prueba sin red hacia Gemini se implementará con mock/feature flag; queda definir cómo se aísla sin tocar el runtime de red local.

Ninguno de estos puntos bloquea el plan; los items 2 y 3 están resueltos y el resto se resuelve durante la implementación, reportando al usuario antes de cerrar cada checkpoint.

---

## Referencia a Gate S

- Brainstorming/socrático: ejecutado como diálogo de preguntas (una a una) antes de esta especificación.
- `spec-review-loop`: ejecutado (ver sección de historial en el plan de implementación, registro de observaciones).
- Sin TBD/TODO/placeholders sin resolver en secciones de diseño; los puntos abiertos están explícitos en §20.
