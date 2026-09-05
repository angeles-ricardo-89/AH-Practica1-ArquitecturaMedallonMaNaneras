# Plan de implementación — Agente de investigación, memoria conversacional y autenticación

**Fecha:** 2026-09-05
**Spec:** `docs/superpowers/specs/2026-09-05-agentic-memory-auth-design.md`
**PRD:** `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (agregado al PRD 2.0)
**Estado:** Plan propuesto, pendiente de aprobación explícita del usuario

> **Para workers agénticos:** implementar tarea por tarea, en orden, sin saltar dependencias. Cada tarea termina con un checkpoint verificable antes de avanzar.

**Objetivo:** convertir el chat RAG actual en un agente de investigación acotado (3 tools de solo lectura) con autenticación JWT por cookie, memoria conversacional aislada y despliegue mínimo GCP, entregando evidencia real.

**Arquitectura:** capa agéntica pequeña sobre FastAPI/Pydantic (plan JSON validado + ejecutor seguro), memoria en PostgreSQL con propiedad por usuario, auth con PyJWT+Argon2, y despliegue IaC con Terraform (Cloud Run + Neon + Gemini). Sin frameworks agénticos.

**Tech Stack:** Python 3.13 (uv), FastAPI, Pydantic v2, Typer, psycopg + pgvector, PyJWT, pwdlib[argon2], Vue 3 + Pinia, Terraform, google-genai (solo producción).

---

## Línea de corte

| Nivel | Contenido | Condición |
|---|---|---|
| **P0 (no negociable)** | T1–T13 completos y probados | Entrega. Nunca se recorta autenticación, aislamiento, negativa, 3 tools, memoria, Docker verificable, URL activa o pruebas mínimas |
| **P1 (solo tras P0 verde)** | Dominio personalizado; línea de tiempo/comparación; pipeline completo en GCP; segunda instancia + pruebas distribuidas | Opcional si sobra tiempo |
| **P2 (tras la entrega)** | Registro público; bot de Telegram; administración/revocación de usuarios | Con aprobación explícita |

---

## Checkpoints obligatorios (correr al cierre de cada tarea aplicable)

1. Backend: `uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90` (cobertura ≥90%).
2. `uv run ruff check src/ tests/` sin errores.
3. `uv run ty check` sin errores.
4. Frontend: `pnpm typecheck` y `pnpm test:unit` sin errores.
5. Pruebas con PostgreSQL/pgvector vivo (`docker compose up -d postgres`).
6. Matriz 2 usuarios × 2 conversaciones (leer/continuar/borrar).
7. Prueba local del agente sin acceso a Gemini (offline).
8. Smoke test productivo (T12).
9. Verificación de que no hay secretos comprometidos (`git grep` de credenciales reales).

---

## Restricciones de implementación (vigentes en todo el plan)

1. No usar UUID4 ni identificadores aleatorios que contradigan la regla del proyecto (HMAC deterministas).
2. No guardar JWT en `localStorage`; solo cookie `HttpOnly`.
3. No confiar en `user_id` enviado por el navegador; siempre del JWT validado.
4. No enviar el historial completo desde el frontend; cargarlo del servidor.
5. No exponer las tools como endpoints públicos.
6. No ejecutar la salida del modelo (ni SQL, ni código, ni URLs libres).
7. No mezclar corpus local y productivo.
8. No aplicar filtros después de descartar candidatos relevantes (prefiltrado SQL).
9. No usar rate limiter solo en memoria para producción (contador atómico en PostgreSQL).
10. No añadir registro público ni Telegram en P0.
11. No publicar documentación que afirme resultados no obtenidos.

---

## Tareas

### T1 — Verdad del proyecto (P0.1): corregir inconsistencias y fijar línea base

- **Archivos probables:** `backend/src/lakehouse/config.py`, `frontend/src/stores/chat.ts`, `frontend/src/api/chat.ts`, `.env.template`, `README.md`, `IMPLEMENTATION_PLAN.md`, `backend/tests/test_schemas/test_config.py`, `backend/tests/test_api/test_chat.py`, `backend/tests/test_evaluate_rag.py`, `backend/src/lakehouse/api/routers/chat.py`.
- **Prueba primero:** actualizar `test_config.py::test_default_values` y `test_chat.py::test_chat_populates_model_latency_and_tokens`/`test_evaluate_rag.py::test_call_llamacpp_returns_content` para que exijan el valor canónico; verificar que fallan antes del cambio y pasan después.
- **Cambio mínimo:** fijar como canónico `max_context_tokens = 10000` y `llamacpp_model = "gemma-4-12b"` (confirmados por el usuario); alinear frontend (`MAX_CONTEXT_TOKENS = 10000`) y `.env.template`/README (`gemma-4-12b`, `embeddinggemma`); unificar contrato `token_usage` (`total`, no `total_tokens`) en `chat.py` y `stores/chat.ts`; marcar la evaluación como pendiente o regenerar; quitar el código comentado de `pipeline/clustering.py:350` (ruff).
- **Comando de validación:** `make test-backend && make lint && make typecheck-backend && make typecheck-frontend`.
- **Criterio de terminado:** suite verde (0 fallas), `ruff`/`ty`/`pnpm typecheck` sin errores, README e `IMPLEMENTATION_PLAN.md` sincronizados (sin afirmar CP-16 ni evaluación como concluidos).
- **Dependencia:** ninguna (base).
- **Rollback:** revertir valores de `config.py` y mensajes de doc; no hay migraciones.

### T2 — Migraciones y repositorios de datos

- **Archivos probables:** `backend/src/lakehouse/db/migrations/002_auth_memory.sql` (up/down), `backend/src/lakehouse/db/observability_conn.py` (o un `migrations.py`), `backend/src/lakehouse/services/memory.py`, `backend/tests/test_db/test_migrations.py`.
- **Prueba primero:** test que aplica `002_auth_memory.sql` sobre `mananeras_test` y verifica las tablas `app_user`, `conversation`, `message`, `tool_execution` + claves y cascada; test de `down` que revierte.
- **Cambio mínimo:** añadir (no modificar tablas existentes) el esquema de la spec §5; borrado en cascada; `public_id` calculado como HMAC determinista.
- **Comando de validación:** `uv run pytest tests/test_db/test_migrations.py --cov=src --cov-fail-under=90` (requiere postgres vivo).
- **Criterio de terminado:** migración idempotente (re-aplicable sin error) y reversible; cascada verificada en test.
- **Dependencia:** T1.
- **Rollback:** `down` de la migración; tablas nuevas, sin impacto en el pipeline.

### T3 — Autenticación, cookies y CSRF

- **Archivos probables:** `backend/src/lakehouse/services/security.py`, `backend/src/lakehouse/api/routers/auth.py`, `backend/src/lakehouse/schemas/auth.py`, `backend/src/lakehouse/api/deps.py` (`get_current_user`), `backend/src/lakehouse/main.py` (guard global + CORS/headers), `backend/tests/test_api/test_auth.py`, `backend/tests/test_security.py`.
- **Prueba primero:** `test_login_valido_fija_cookie_httponly`, `test_login_invalido_mensaje_generico`, `test_endpoint_protegido_sin_cookie_401`, `test_cookie_prod_secure_samesite`, `test_csrf_requerido_en_mutacion`, `test_usuarios_demo_idempotentes`.
- **Cambio mínimo:** PyJWT (HS256, claims `sub/iat/exp/iss/aud`, 60 min) + `pwdlib[argon2]`; 2 usuarios demo idempotentes desde env; token CSRF firmado ligado al `jti`; guard global que protege todo salvo `GET /health` y login.
- **Comando de validación:** `uv run pytest tests/test_api/test_auth.py tests/test_security.py --cov=src --cov-fail-under=90`.
- **Criterio de terminado:** CA-A01…CA-A06; ningún secreto en respuestas/logs.
- **Dependencia:** T2.
- **Rollback / feature flag:** guard global conmutado por `APP_ENV`/flag; con el guard desactivado, los endpoints legacy responden como hoy.

### T4 — Aislamiento y memoria conversacional

- **Archivos probables:** `backend/src/lakehouse/api/routers/conversations.py`, `backend/src/lakehouse/schemas/conversation.py`, `backend/src/lakehouse/services/memory.py`, `backend/tests/test_api/test_conversations.py`.
- **Prueba primero:** matriz 2×2 (`test_usuario_a_no_lee_conversacion_de_b_404`, `test_historial_aislado_entre_conversaciones`, `test_borrado_cascada`).
- **Cambio mínimo:** endpoints crear/listar/retomar/borrar con filtro `conversation_id`+`owner_id`; carga de historial desde servidor; retención 30 días (`last_activity_at`/`expires_at`) + limpieza oportunista.
- **Comando de validación:** `uv run pytest tests/test_api/test_conversations.py --cov=src --cov-fail-under=90`.
- **Criterio de terminado:** CA-M01…CA-M06; matriz 2×2 verde.
- **Dependencia:** T3.
- **Rollback:** deshabilitar el router de conversaciones; `/chat` legacy intacto.

### T5 — Rate limits

- **Archivos probables:** `backend/src/lakehouse/services/rate_limit.py`, `backend/src/lakehouse/db/migrations/003_rate_limits.sql`, `backend/src/lakehouse/api/deps.py`, `backend/tests/test_rate_limit.py`.
- **Prueba primero:** `test_login_5_por_minuto`, `test_chat_10_por_minuto`, `test_cuota_diaria_100`, `test_429_con_retry_after`.
- **Cambio mínimo:** ventanas atómicas `INSERT ... ON CONFLICT DO UPDATE` en PostgreSQL; IP como HMAC; depuración automática; aplicar a login y al turno del agente.
- **Comando de validación:** `uv run pytest tests/test_rate_limit.py --cov=src --cov-fail-under=90`.
- **Criterio de terminado:** límites de la spec §11 verificados; sin contador solo-en-memoria en producción.
- **Dependencia:** T3.
- **Rollback:** límites configurables a 0/deshabilitados vía settings.

### T6 — Implementación individual de cada tool

- **Archivos probables:** `backend/src/lakehouse/services/agent/tools.py`, `backend/src/lakehouse/schemas/agent.py`, `backend/tests/test_agent/test_tools.py`.
- **Prueba primero:** una prueba por tool (`buscar_declaraciones` prefiltra por fecha/participante antes del ranking; `explorar_temas` por tamaño/calidad; `consultar_cluster` devuelve evidencias con pertenencia).
- **Cambio mínimo:** tres funciones internas (allowlist) sobre `rag_search.py` y `clusters.py`; rangos y errores de la spec §9; sin endpoint público.
- **Comando de validación:** `uv run pytest tests/test_agent/test_tools.py --cov=src --cov-fail-under=90`.
- **Criterio de terminado:** contratos de la spec §9 con estados de error verificados (422/503/`[]`).
- **Dependencia:** T4.
- **Rollback:** módulo autocontenido; sin cambios en endpoints existentes.

### T7 — Planificador y ejecutor agéntico

- **Archivos probables:** `backend/src/lakehouse/services/agent/planner.py`, `executor.py`, `backend/src/lakehouse/schemas/agent.py`, `backend/tests/test_agent/test_planner.py`.
- **Prueba primero:** `test_plan_valido_se_ejecuta`, `test_plan_nombre_no_permitido_rechazado`, `test_plan_invalido_un_reintento_y_fallback`, `test_max_dos_tools`.
- **Cambio mínimo:** Gemma local devuelve plan JSON → Pydantic valida (allowlist, rangos) → ejecutor llama tools internas; máx. 2 ejecuciones; 10 s por tool; fallback trazable a `buscar_declaraciones`.
- **Comando de validación:** `uv run pytest tests/test_agent/test_planner.py --cov=src --cov-fail-under=90` + prueba offline sin red.
- **Criterio de terminado:** CA-T04, CA-T05; nunca se ejecuta SQL/URL/`user_id` del modelo.
- **Dependencia:** T6.
- **Rollback:** el turno agéntico convive con `/chat` legacy; ante fallo se redirige a `/chat`.

### T8 — Síntesis, evidencia y negativa

- **Archivos probables:** `backend/src/lakehouse/services/agent/synthesizer.py`, `backend/src/lakehouse/api/routers/conversations.py`, `backend/tests/test_agent/test_synthesizer.py`.
- **Prueba primero:** `test_negativa_sin_evidencia`, `test_respuesta_con_evidencias_y_traza`, `test_cluster_no_presentado_como_hecho`.
- **Cambio mínimo:** sintetizador redacta solo con memoria autorizada + resultados; umbral de negativa (spec §20.1); traza `tool_executions` en la respuesta; guardar turno.
- **Comando de validación:** `uv run pytest tests/test_agent/test_synthesizer.py --cov=src --cov-fail-under=90`.
- **Criterio de terminado:** CA-T07, CA-T08; negativa correcta verificada.
- **Dependencia:** T7.
- **Rollback:** sin efectos externos; revertir umbral a valor previo.

### T9 — Interfaz de login y conversaciones

- **Archivos probables:** `frontend/src/stores/auth.ts`, `frontend/src/api/auth.ts`, `frontend/src/api/conversations.ts`, `frontend/src/components/auth/LoginView.vue`, `frontend/src/components/chat/ConversationList.vue`, `frontend/src/router.ts`, `frontend/src/components/chat/TokenBar.vue` (usar `total`), `frontend/src/utils/markdown.ts` (sanitizar), `frontend/tests/**`.
- **Prueba primero:** `LoginView` redirige sin sesión; lista/crea/retoma/borra conversaciones; `TokenBar` consume `total`; test de sanitización de salida (I8).
- **Cambio mínimo:** route guards por sesión; pantalla de login; menú de conversaciones; indicador de conversación activa; tarjeta "Cómo investigó"; sanitizar Markdown (DOMPurify) y validar URLs de enlaces.
- **Comando de validación:** `pnpm typecheck && pnpm test:unit`.
- **Criterio de terminado:** flujo de la demo §18 del PRD operable; contrato backend–frontend verde.
- **Dependencia:** T3, T4, T8.
- **Rollback:** guard de rutas desactivable; componentes nuevos no tocan el flujo legacy.

### T10 — Docker y verificación del pipeline

- **Archivos probables:** `docker-compose.yml` (servicio/perfil `pipeline`), `Dockerfile.pipeline`, `Makefile` (`docker-verify`), fixture de muestra Bronze congelada, `backend/tests/test_pipeline/`.
- **Prueba primero:** fixture que corre Bronze→Silver→Gold→clustering→etiquetado y valida salidas por capa.
- **Cambio mínimo:** servicio `pipeline` en contenedor con el mismo código; health checks y dependencias explícitas de Ollama/llamacpp (host); `make docker-verify`.
- **Comando de validación:** `make docker-verify` y comando documentado de pipeline completo.
- **Criterio de terminado:** CA-D01…CA-D03; evidencia reproducible en contenedor.
- **Dependencia:** T1.
- **Rollback:** revertir `docker-compose.yml` y `Makefile`; fixture es aditivo.

### T11 — Adaptadores Gemini y reindexación productiva

- **Archivos probables:** `backend/src/lakehouse/services/gemini_embedding.py`, `gemini_chat.py`, `backend/src/lakehouse/db/pgvector_conn.py`, `backend/src/lakehouse/config.py`, `backend/tests/test_gemini_adapters.py`.
- **Prueba primero:** adaptadores con `google-genai` mockeados (embeddings `gemini-embedding-001` 768 dims, normalización, tareas `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`); validación de metadatos de índice.
- **Cambio mínimo:** adaptadores aislados (solo producción); reindexación TOTAL hacia un índice Neon independiente y versionado; fallar cerrado si la config no coincide con metadatos.
- **Comando de validación:** `uv run pytest tests/test_gemini_adapters.py --cov=src --cov-fail-under=90` + prueba offline sin Gemini.
- **Criterio de terminado:** CA-R05, CA-R06; índices local/productivo físicamente separados.
- **Dependencia:** T1, T2.
- **Rollback:** adaptadores sin efecto en local; índice productivo borrable sin tocar el local.

### T12 — Cloud Run + Neon (Terraform)

- **Archivos probables:** `infra/terraform/*.tf`, `terraform.tfvars.example`, `.gitignore`, `scripts/gcp_cost.py` + `scripts/gcp_cost.example.json`.
- **Prueba primero:** `terraform validate`/`plan` limpios; `gcp_cost.py` determinista (misma entrada → misma salida) y marca excesos de free tier.
- **Cambio mínimo:** IaC Terraform (estado GCS, SA privilegios mínimos, Cloud Run `max-instances=1` escala a cero, Neon TLS+pooling, Secret Manager ≤6 versiones); construir la herramienta de costo definida en `costo_infraestructura_gcp.md`.
- **Comando de validación:** `terraform validate && terraform plan`; `uv run python scripts/gcp_cost.py --config scripts/gcp_cost.example.json`.
- **Criterio de terminado:** URL `run.app` abre login, autentica, conversa, retoma y borra (CA-D04…CA-D08); costo ~USD 0 documentado.
- **Dependencia:** T9, T11.
- **Rollback:** `terraform destroy`; el entorno local nunca se toca.

### T13 — Pruebas finales y evidencia para el PDF

- **Archivos probables:** `docs/prd/...`, `README.md` (resultados reales), `data/lakehouse/logs/evaluate_rag_results.json` (regenerado real), PDF final.
- **Prueba primero:** re-ejecutar `evaluate-rag` con resultado real (sin marcadores); smoke test productivo desde sesión limpia; verificación de secretos.
- **Cambio mínimo:** consolidar evidencia real (login, memoria, tool trace, negativa, aislamiento, capturas), comandos de reproducción y credenciales solo en el PDF.
- **Comando de validación:** `make check` + smoke test + `git grep` de secretos (sin hallazgos).
- **Criterio de terminado:** CA-R02/R03/R04 (evaluación real); PDF accesible centrado en problema/usuario/evidencia; 2 usuarios demo demostrados.
- **Dependencia:** T1–T12.
- **Rollback:** documentación; revertir textos que sobreafirmen.

---

## Registro del spec-review-loop (Gate S)

- **Iteración 1:** revisión de la spec detectó 3 hallazgos menores: (1) ambigüedad en el mecanismo de vinculación del token CSRF; (2) aparente contradicción 5 vs 6 intentos de login (reconciliada: 5 permitidos, 6.º → `429`); (3) conflicto entre "se elimina `total_tokens`" y la columna `total_tokens` de la tabla `message` (aclarado: la columna es persistencia interna, no contrato).
- **Correcciones aplicadas** en la spec (§6, §11, §10) sin re-brainstorming adicional; sin TBD/TODO pendientes.
- **Resultado:** PASS. Procede a `writing-plans`.

## Validación documental de esta fase

- `git diff --check` sin errores de whitespace.
- `rg` de nombres de modelos, límites y `total_tokens` coherente entre PRD, spec, plan y skills.
- Sin contraseñas/secretos reales escritos (solo placeholders y referencias).
- Skills sin duplicación de responsabilidad (matriz de dueñas verificada).
