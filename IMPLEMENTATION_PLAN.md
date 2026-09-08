# IMPLEMENTATION PLAN — Lakehouse Mañaneras

## Metadatos

- **Version:** 0.1.0
- **PRD:** `docs/prd/arquitectura_medallon_y_embbeding_CSP.md`
- **Fecha de creacion:** 2026-07-26
- **Estado actual:** PRD 3.0 aprobado (agente/memoria/auth); plan 2026-09-05 en implementacion
- **Ultimo checkpoint completado:** T12 (Cloud Run + Neon via Terraform)
- **Siguiente fase (pendiente):** T13 (pruebas finales y evidencia para el PDF)

## Reglas de Reanudacion

Al comenzar una nueva sesion, el agente debe:

1. Leer este archivo completo.
2. Recorrer los checkpoints en orden secuencial.
3. Identificar el PRIMER checkpoint con `[ ]` (no completado).
4. Ejecutar ese checkpoint y SOLO ese checkpoint.
5. Al completarlo, marcarlo como `[x]` y detenerse para revision del usuario.
6. NO saltar checkpoints. NO avanzar sin aprobacion explicita.

---

## Onboarding: Dominios Afectados

| Dominio | Skills Relevantes |
|---------|-------------------|
| Infraestructura Docker | `docker compose` — sin skill especifica |
| Ingestion Bronze | `arquitectura_medallon.md`, `idempotencia_y_merge.md` |
| Parsing Silver | `arquitectura_medallon.md`, `fastapi_pydantic_typer.md` |
| Enriquecimiento Gold | `arquitectura_medallon.md`, `duckdb_pgvector.md`, `payload_vectorial_limpio.md` |
| API Backend | `fastapi_pydantic_typer.md`, `duckdb_pgvector.md`, `memoria_rag_tokens.md` |
| Observabilidad | `observabilidad_pull.md`, `fastapi_pydantic_typer.md` |
| Dashboard Frontend | `vue3_pinia_tailwind.md`, `memoria_rag_tokens.md` |
| Testing + QA | `testing_qa.md` (aplica a todos los dominios) |

---

## Edge Case Coverage

- **Ingesta con HTML malformado:** El parser Silver debe manejar tags no cerrados y HTML no estandar de gob.mx.
- **Conferencia sin intervenciones:** Si una pagina de archivo no contiene articulos con conferencias, se registra como `html_count = 0` en el manifiesto de ingesta.
- **Participante sin nombre detectable:** Va a DLQ con motivo `participant_not_detected`.
- **Texto vacio tras limpieza:** Va a DLQ con motivo `empty_after_clean`.
- **Ollama no disponible durante generacion de embeddings:** Reintento exponencial (3 intentos, 2s/4s/8s). Si falla, se loggea y el registro queda sin embedding (se reintenta en la siguiente ejecucion).
- **llamacpp no disponible durante chat RAG:** El endpoint /chat devuelve 503 con mensaje explicito.
- **Corpus vacio (sin datos en Gold):** El endpoint /search devuelve `results: []` y `total: 0`.
- **MAX_CONTEXT_TOKENS excedido:** Truncado FIFO del historial. System prompt + query actual NUNCA se truncan.
- **Dos ejecuciones simultaneas del pipeline:** El archivo de lock (`/tmp/pipeline.lock`) previene ejecucion concurrente.
- **pgvector no inicializado:** El healthcheck de Docker Compose garantiza que postgres + pgvector esten listos antes de iniciar el backend.

---

## Checkpoints de Implementacion

---

### FASE 0: Infraestructura Base

#### CP-00: Docker Compose y Estructura de Directorios

**Objetivo:** Levantar el entorno base con PostgreSQL + pgvector, Ollama, DuckDB CLI y crear la estructura de directorios del proyecto.

**Archivos a crear/modificar:**
- `docker-compose.yml`
- `.env.template`
- `backend/pyproject.toml`
- `frontend/package.json`
- `data/lakehouse/.gitkeep` (bronze, silver, gold, logs)
- `.gitignore` (verificar que existe)

**Acciones:**
1. Escribir `docker-compose.yml` con servicios: `postgres`, `ollama`, `llamacpp`.
2. Crear `.env.template` con todas las variables del PRD (seccion 7).
3. Inicializar `backend/pyproject.toml` con dependencias base.
4. Inicializar `frontend/package.json` con Vue 3, Pinia, Tailwind, Vitest.
5. Crear estructura de directorios `data/lakehouse/{bronze,silver,gold,logs}/` con `.gitkeep`.

**Evidencia Requerida:**
- `docker compose up -d` levanta los 3 servicios sin errores.
- `docker compose ps` muestra todos los servicios como `Up` o `healthy`.
- `docker compose logs postgres` muestra "database system is ready".
- `docker compose logs ollama` muestra "Listening on [::]:11434".
- `ls data/lakehouse/` muestra bronze, silver, gold, logs.

---

### FASE 1: Backend — Data Pipeline

#### CP-01: Schemas Pydantic (Modelos de Datos)

**Objetivo:** Definir todos los schemas Pydantic V2 para las tres capas del medallon.

**Archivos a crear:**
- `backend/src/lakehouse/__init__.py`
- `backend/src/lakehouse/config.py` (Settings con Pydantic)
- `backend/src/lakehouse/schemas/__init__.py`
- `backend/src/lakehouse/schemas/bronze.py` (IngestionManifest, BronzeRecord)
- `backend/src/lakehouse/schemas/silver.py` (InterventionRecord, DLQRejectRecord, ConferenceRecord)
- `backend/src/lakehouse/schemas/gold.py` (RagCorpusRecord)
- `backend/src/lakehouse/schemas/search.py` (SearchRequest, SearchResponse)
- `backend/src/lakehouse/schemas/chat.py` (ChatRequest, ChatResponse, SourceChunk)
- `backend/src/lakehouse/schemas/observability.py` (PipelineStatus, PipelineLogs)

**Evidencia Requerida:**
- `uv run python -c "from lakehouse.schemas.bronze import BronzeRecord; print('OK')"` funciona.
- Tests unitarios de validacion Pydantic: `uv run pytest tests/test_schemas/ -xvs` pasa con >= 95% coverage en schemas.
- SearchRequest rechaza query vacia, query > 500 chars, top_k fuera de rango, campos extra.

---

#### CP-02: Ingesta Bronze (Scraper + DuckDB)

**Objetivo:** Implementar la descarga de HTML desde gob.mx y almacenamiento en DuckDB con content_hash determinista.

**Archivos a crear:**
- `backend/src/lakehouse/pipeline/__init__.py`
- `backend/src/lakehouse/pipeline/ingestion.py`
- `backend/src/lakehouse/pipeline/scraper.py`
- `backend/src/lakehouse/db/__init__.py`
- `backend/src/lakehouse/db/duckdb_conn.py`
- `backend/tests/test_pipeline/test_ingestion.py`

**Evidencia Requerida:**
- `uv run python -m lakehouse pipeline ingest --dry-run` simula sin escribir.
- `uv run python -m lakehouse pipeline ingest` descarga y guarda en Bronze.
- Dos ejecuciones consecutivas del mismo lote: segunda no duplica registros.
- content_hash es identico para la misma pagina en distintas ejecuciones.
- Tabla `bronze.raw_html` existe y contiene registros con `ingestion_run_id`.

---

#### CP-03: Parsing Silver (HTML → Pydantic Records)

**Objetivo:** Convertir HTML Bronze a registros InterventionRecord validados con Pydantic.

**Archivos a crear:**
- `backend/src/lakehouse/pipeline/parsing.py`
- `backend/src/lakehouse/pipeline/dlq.py`
- `backend/src/lakehouse/db/merge.py`
- `backend/tests/test_pipeline/test_parsing.py`

**Evidencia Requerida:**
- Parser extrae participant y text de al menos 80% de los chunks en un lote real.
- DLQ captura registros invalidos con rejection_reason.
- MERGE INTO Silver no duplica en segunda ejecucion.
- Tablas `silver.interventions` y `silver.conferences` existen con datos.
- `uv run pytest tests/test_pipeline/test_parsing.py -xvs` pasa.

---

#### CP-04: Enriquecimiento Gold (Embeddings + pgvector)

**Objetivo:** Generar embeddings via Ollama y almacenarlos en pgvector con payload limpio.

**Archivos a crear:**
- `backend/src/lakehouse/pipeline/enrichment.py`
- `backend/src/lakehouse/db/pgvector_conn.py`
- `backend/src/lakehouse/db/migrations/001_create_gold_rag_corpus.sql`
- `backend/tests/test_pipeline/test_enrichment.py`

**Evidencia Requerida:**
- `build_embedding_payload()` genera texto sin hashes ni IDs tecnicos (verificar visualmente).
- Ollama responde con embedding de dimension correcta (768 para nomic-embed-text).
- Tabla `gold.rag_corpus` contiene registros con embeddings no nulos.
- Indices B-Tree y HNSW creados (verificar con `\d gold.rag_corpus` en psql).
- Busqueda semantica basica: query "reforma energetica" devuelve chunks relevantes.

---

### FASE 2: Backend — API REST

#### CP-05: FastAPI App + Health + Search Endpoint

**Objetivo:** Crear la aplicacion FastAPI con endpoints de health y busqueda semantica.

**Archivos a crear:**
- `backend/src/lakehouse/main.py`
- `backend/src/lakehouse/api/__init__.py`
- `backend/src/lakehouse/api/deps.py`
- `backend/src/lakehouse/api/routers/__init__.py`
- `backend/src/lakehouse/api/routers/health.py`
- `backend/src/lakehouse/api/routers/search.py`
- `backend/tests/test_api/test_search.py`

**Evidencia Requerida:**
- `uv run fastapi dev src/lakehouse/main.py` levanta en puerto 8000.
- `curl http://localhost:8000/health` → `{"status": "ok"}`.
- `curl -X POST http://localhost:8000/search/ -H "Content-Type: application/json" -d '{"query":"reforma","top_k":3}'` → 200 con results.
- Busqueda con filtros (fecha, participante) devuelve subconjunto filtrado.
- `strategy` en response indica "hnsw", "relational_then_vector", o "hybrid".

---

#### CP-06: Chat Endpoint con RAG

**Objetivo:** Implementar el endpoint /chat que orquesta busqueda semantica + generacion con llamacpp.

**Archivos a crear:**
- `backend/src/lakehouse/api/routers/chat.py`
- `backend/src/lakehouse/services/__init__.py`
- `backend/src/lakehouse/services/token_estimator.py`
- `backend/src/lakehouse/services/context_builder.py`
- `backend/tests/test_api/test_chat.py`

**Evidencia Requerida:**
- `curl -X POST http://localhost:8000/chat/ ...` → 200 con answer + sources.
- Sources incluyen conference_date, participant, chunk_text, similarity.
- TokenUsage refleja consumo real de la ventana de contexto.
- Si el contexto excede MAX_CONTEXT_TOKENS, se truncan mensajes antiguos (verificar en logs).
- Respuesta del chat es coherente y cita fuentes de los sources.

---

#### CP-07: Observabilidad Endpoints

**Objetivo:** Exponer endpoints para que el dashboard lea estado del pipeline y logs.

**Archivos a crear:**
- `backend/src/lakehouse/api/routers/observability.py`
- `backend/src/lakehouse/services/log_reader.py`
- `backend/src/lakehouse/services/status_writer.py`
- `backend/tests/test_api/test_observability.py`

**Evidencia Requerida:**
- `GET /observability/status` → 200 con PipelineStatus.
- `GET /observability/logs?lines=50` → 200 con ultimas 50 lineas del log.
- El pipeline (CP-02) escribe `cron.status` correctamente al iniciar/finalizar.
- Semaforo cambia de color segun estado real del pipeline.

---

#### CP-08: CLI Typer

**Objetivo:** Crear la CLI con Typer para orquestar el pipeline y la evaluacion RAG.

**Archivos a crear:**
- `backend/src/lakehouse/cli.py`
- `backend/src/lakehouse/pipeline/evaluate_rag.py`

**Evidencia Requerida:**
- `uv run python -m lakehouse --help` muestra comandos disponibles.
- `uv run python -m lakehouse pipeline ingest` ejecuta la ingesta Bronze.
- `uv run python -m lakehouse evaluate-rag` ejecuta la evaluacion con gemma4.

---

### FASE 3: Frontend — Dashboard Vue

#### CP-09: Setup Vue 3 + Vite + Tailwind + Pinia

**Objetivo:** Inicializar el proyecto frontend con la configuracion base.

**Archivos a crear:**
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/tailwind.config.ts`
- `frontend/postcss.config.js`
- `frontend/index.html`
- `frontend/src/main.ts`
- `frontend/src/App.vue`

**Evidencia Requerida:**
- `pnpm install` sin errores.
- `pnpm dev` levanta en `http://localhost:5173`.
- `pnpm typecheck` pasa sin errores.
- `pnpm build` genera `dist/` sin warnings.

---

#### CP-10: Chat RAG UI

**Objetivo:** Implementar la interfaz de chat con barra de tokens y tarjetas de evidencia.

**Archivos a crear:**
- `frontend/src/stores/chat.ts`
- `frontend/src/api/client.ts`
- `frontend/src/api/chat.ts`
- `frontend/src/api/search.ts`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/components/chat/ChatMessage.vue`
- `frontend/src/components/chat/TokenBar.vue`
- `frontend/src/components/search/EvidenceCard.vue`
- `frontend/tests/components/TokenBar.test.ts`
- `frontend/tests/components/ChatWindow.test.ts`

**Evidencia Requerida:**
- UI del chat renderiza mensajes de usuario y respuestas del asistente.
- TokenBar cambia de verde → rojo cuando > 90% de MAX_CONTEXT_TOKENS.
- EvidenceCard muestra fecha, participante, fragmento y es clickeable.
- Store de Pinia gestiona estado del chat correctamente (mensajes, tokens, loading).
- `pnpm test:unit` pasa para componentes del chat.

---

#### CP-11: Dashboard de Observabilidad

**Objetivo:** Implementar el dashboard con semaforo de estado y visor de logs.

**Archivos a crear:**
- `frontend/src/stores/observability.ts`
- `frontend/src/api/observability.ts`
- `frontend/src/components/dashboard/SemaforoEstado.vue`
- `frontend/src/components/dashboard/LogViewer.vue`
- `frontend/src/components/dashboard/DashboardPage.vue`
- `frontend/tests/components/SemaforoEstado.test.ts`

**Evidencia Requerida:**
- SemaforoEstado muestra color y label correctos segun PipelineStatus.
- LogViewer muestra ultimas lineas del log sin recargar la pagina.
- Polling cada 10 segundos actualiza ambos componentes.
- DashboardPage integra SemaforoEstado + LogViewer + ChatWindow.

---

### FASE 4: QA y Evaluacion

#### CP-12: Test Suite Completa + Coverage >= 90%

**Objetivo:** Consolidar todos los tests y verificar cobertura >= 90%.

**Archivos a verificar/crear:**
- `backend/tests/conftest.py` (fixtures compartidos)
- `backend/tests/test_schemas/` (todos los schemas)
- `backend/tests/test_pipeline/` (ingestion, parsing, enrichment, merge)
- `backend/tests/test_api/` (health, search, chat, observability)
- `backend/tests/test_db/` (duckdb, pgvector)
- `frontend/tests/components/` (todos los componentes)

**Evidencia Requerida:**
- `uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90` pasa.
- `pnpm test:unit --coverage` pasa con >= 80% en frontend.
- `uv run ruff check` sin errores.
- `uv run ty check` sin errores.
- `pnpm typecheck` sin errores.

---

#### CP-13: Evaluacion RAG (LLM-as-a-Judge)

**Objetivo:** Ejecutar y verificar que evaluate-rag alcanza los umbrales de calidad.

**Archivos a crear:**
- `backend/data/golden_dataset.json` (50 preguntas predefinidas)
- `backend/tests/test_evaluate_rag.py`

**Evidencia Requerida:**
- `uv run python -m lakehouse evaluate-rag` completa sin errores.
- Fidelidad (cero alucinaciones) >= 90%.
- Relevancia de respuesta >= 80%.
- Reporte de evaluacion guardado en `data/lakehouse/logs/evaluate_rag_results.json`.

---

#### CP-14: Idempotencia End-to-End

**Objetivo:** Verificar que el pipeline completo es idempotente de punta a punta.

**Acciones:**
1. Ejecutar pipeline completo (Bronze → Silver → Gold).
2. Re-ejecutar con los mismos datos de entrada.
3. Verificar en cada capa: `filas_nuevas = 0`, `duplicados = total registros previos`.

**Evidencia Requerida:**
- Bronze: segunda ejecucion no agrega registros (content_hash repetido).
- Silver: MERGE no inserta duplicados.
- Gold: embeddings no se regeneran para chunks ya procesados.
- `evaluate-rag` produce resultados identicos en ambas ejecuciones (variacion <= 5%).

---

### FASE 5: Cierre del Sprint

#### CP-15: Docker Compose Full Stack + DoD Verification

**Objetivo:** Verificar que `docker compose up -d` levanta el stack completo y todos los
Criterios de Aceptacion del PRD se cumplen.

**Evidencia Requerida:**
- `docker compose up -d` exitoso (todos los servicios healthy).
- CA-01: Dos lotes Bronze con timestamps distintos.
- CA-02: Registros Silver validados con Pydantic + DLQ con rechazos.
- CA-03: Reejecucion produce filas_nuevas=0, duplicados=0.
- CA-04: Embeddings en pgvector para cada chunk Gold.
- CA-05: Busqueda semantica devuelve resultados relevantes.
- CA-06: evaluate-rag >= 90% fidelidad, >= 80% relevancia.
- CA-07: Variacion de etiquetas <= 5% entre ejecuciones.
- CA-08: Reconstruccion total <= 15 minutos para 3 meses de datos.
- CA-09: Dashboard muestra semaforo y logs en tiempo real (polling).
- DoD completo: se puede hacer `docker compose up -d` y el sistema funciona end-to-end.

---

### FASE 6: Interrupcion Graceful

#### CP-16: Interrupcion Graceful de Pipelines

**Objetivo:** Que ingest/parse/enrich terminen gracefulmente ante SIGINT/SIGTERM,
escribiendo su corrida como `interrupted` con conteos parciales.

**Archivos:**
- `backend/src/lakehouse/pipeline/interrupt.py` (nuevo)
- `backend/src/lakehouse/cli.py`
- `backend/src/lakehouse/db/observability_conn.py`
- `backend/src/lakehouse/pipeline/ingestion.py`, `parse_service.py`, `enrichment.py`
- `frontend/src/components/pipeline/PipelineCard.vue`, `PipelineTimeline.vue`
- `frontend/src/components/dashboard/SemaforoEstado.vue`

**Evidencia Requerida:**
- `uv run pytest -xvs --cov=src --cov-report=term-missing` pasa (>= 90% coverage).
- `uv run ruff check --fix && uv run ruff format` sin errores.
- `uv run ty check` sin errores.
- `pnpm lint`, `pnpm typecheck`, `pnpm test:unit` pasan.
- Manual: `Ctrl+C` durante `pipeline ingest` escribe `status='interrupted'` con parciales y exit 130.

---

### FASE 6: Agente, Memoria y Autenticacion (PRD 3.0)

#### T1: Verdad del proyecto

**Objetivo:** Corregir inconsistencias de configuracion y fijar linea base canónica.

**Estado:** [x] Completado

**Evidencia:**
- `max_context_tokens = 10000` y `llamacpp_model = "gemma-4-12b"` alineados en backend/frontend/.env.template.
- Contrato `token_usage` unificado (`total`, no `total_tokens`).
- `make test-backend && make lint && make typecheck-backend && make typecheck-frontend` verde.

---

#### T2: Migraciones y repositorios de datos

**Objetivo:** Esquema de autenticacion y memoria conversacional en PostgreSQL.

**Estado:** [x] Completado

**Evidencia:**
- Migracion `002_auth_memory.sql` aplica tablas `app_user`, `conversation`, `message`, `tool_execution`.
- Test de migracion idempotente y reversible con cascada verificada.
- `uv run pytest tests/test_db/test_migrations.py --cov=src --cov-fail-under=90` verde.

---

#### T3: Autenticacion, cookies y CSRF

**Objetivo:** JWT por cookie HttpOnly + token CSRF firmado + 2 usuarios demo.

**Estado:** [x] Completado

**Evidencia:**
- `test_login_valido_fija_cookie_httponly`, `test_endpoint_protegido_sin_cookie_401`, `test_csrf_requerido_en_mutacion` verdes.
- Guard global protege todo salvo `GET /health` y login.

---

#### T4: Aislamiento y memoria conversacional

**Objetivo:** Endpoints CRUD de conversaciones con aislamiento por usuario y retencion 30d.

**Estado:** [x] Completado

**Evidencia:**
- Matriz 2x2 (2 usuarios x 2 conversaciones) verificada: usuario A no lee conversacion de B.
- `test_borrado_cascada` elimina mensajes y traces al borrar conversacion.

---

#### T5: Rate limits

**Objetivo:** Limites atómicos en PostgreSQL para login y chat.

**Estado:** [x] Completado

**Evidencia:**
- Ventanas atómicas `INSERT ... ON CONFLICT DO UPDATE`.
- `test_login_5_por_minuto`, `test_chat_10_por_minuto`, `test_cuota_diaria_100` verdes.

---

#### T6: Implementacion individual de cada tool

**Objetivo:** 3 tools de solo lectura con prefiltro SQL y validacion de rangos.

**Estado:** [x] Completado

**Evidencia:**
- `buscar_declaraciones`, `explorar_temas`, `consultar_cluster` probadas individualmente.
- `uv run pytest tests/test_agent/test_tools.py --cov=src --cov-fail-under=90` verde.

---

#### T7: Planificador y ejecutor agéntico

**Objetivo:** Plan JSON validado + ejecutor seguro, max 2 tools por turno.

**Estado:** [x] Completado

**Evidencia:**
- `test_plan_valido_se_ejecuta`, `test_plan_nombre_no_permitido_rechazado`, `test_max_dos_tools` verdes.
- Fallback trazable a `buscar_declaraciones` ante fallo.

---

#### T8: Sintesis, evidencia y negativa

**Objetivo:** Sintetizador con umbral de negativa, traza de tools y evidencia.

**Estado:** [x] Completado

**Evidencia:**
- `test_negativa_sin_evidencia`, `test_respuesta_con_evidencias_y_traza` verdes.
- Negativa correcta cuando no hay evidencia suficiente.

---

#### T9: Interfaz de login y conversaciones

**Objetivo:** Dashboard integrado con memoria conversacional, chat RAG con fuentes/ embeddings 3D/ metadata, indicadores de medallón en header.

**Estado:** [x] Completado

**Evidencia:**
- Columna izquierda: lista de conversaciones con boton `+`, click para cambiar, borrar con `✕`.
- Chat central: conserva ResponseCard, TokenBar, click para fuentes, embeddings 3D filtrados, metadata (latency/tokens/model/similitud/fuentes/cobertura).
- Auto-creacion de conversacion al escribir sin seleccionar ninguna (titulo = primer mensaje truncado).
- Header: indicadores Bronze/Silver/Gold con SVG de medallas, flechas de flujo, chips de estado armónicos.
- Eliminada pestaña "Investigar" — todo en el dashboard principal.
- `pnpm typecheck` y `pnpm test:unit` verdes (46 tests).
- Smoke test en navegador: login → dashboard → conversacion → turno del agente con tokens > 0.

---

### FASE: Endurecimiento de seguridad y gate perpetuo (S1–S10)

> Plan de referencia: `docs/superpowers/plans/2026-09-05-security-hardening-gate.md`
> Spec: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md`

#### S1: Registro del marcador `security` y catálogo de controles

**Objetivo:** Registrar el marcador pytest `security` y crear `governance/security-controls.yaml` (fuente de verdad amenaza→control→prueba).

**Estado:** [x] Completado

**Evidencia:**
- Catalogo `governance/security-controls.yaml` con 14 controles (amenaza→control→prueba).
- Marcador `security` registrado en `pyproject.toml`; `make security-report` carga el catalogo sin error.

---

#### S2: H1 — Middleware de headers seguros

**Objetivo:** `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` siempre; HSTS + CSP solo en producción.

**Estado:** [x] Completado

**Evidencia:**
- `SecurityHeadersMiddleware` (nosniff/no-referrer/DENY siempre; HSTS+CSP solo en prod) enrutado desde la factory `create_app`.
- Tests `test_security_headers_always_present` y `test_hsts_and_csp_only_in_production` verdes.

---

#### S3: H2 + H3 — Docs en prod y CORS de origen exacto

**Objetivo:** `/docs`/`/redoc`/`/openapi.json` → 404 en producción; CORS cerrado por defecto (sin `*`).

**Estado:** [x] Completado

**Evidencia:**
- `/docs`, `/redoc` y `/openapi.json` devuelven 404 en produccion.
- CORS de origen exacto con fail-closed (sin `*`); tests `test_docs_disabled_in_production` y `test_cors_exact_origin` verdes.

---

#### S4: H4 — Errores saneados

**Objetivo:** Handler de `RuntimeError` sin filtrar `str(exc)` ni tipo al cliente; detalle solo en logs.

**Estado:** [x] Completado

**Evidencia:**
- Handler de `RuntimeError` loggea `exc_info` sin exponer `str(exc)` al cliente; eliminado el filtrado/leak en `conversations.py`.
- Test `test_runtime_error_does_not_leak_internals` verde.

---

#### S5: H5 — Límite de tamaño de body

**Objetivo:** Middleware que devuelve `413` para `Content-Length > 64 KB`.

**Estado:** [x] Completado

**Evidencia:**
- `BodySizeLimitMiddleware` rechaza bodies > 64 KB con `413`.
- Test `test_body_size_limit_returns_413` verde.

---

#### S6: H5 — Timeouts de BD y modelo

**Objetivo:** Helper `pg_connect` con `connect_timeout` + `statement_timeout` aplicado a conexiones de API; timeout explícito en `rag_search`.

**Estado:** [x] Completado

**Evidencia:**
- `db/connection.py` con `pg_connect` + `pg_conn_str_with_timeouts`: connect 5s / statement 10s / modelo 10s aplicados a las rutas de API.
- Test `test_pg_connect_applies_timeouts` verde; integración con Postgres vivo pasa.

---

#### S7: H6 — Escáner de secretos

**Objetivo:** `scripts/scan_secrets.py` determinista que detecta secretos rastreados por git.

**Estado:** [x] Completado

**Evidencia:**
- `scripts/scan_secrets.py` determinista: exit 0 en repo limpio.
- Tests de regresión en `backend/tests/test_scan_secrets.py` (detecta secretos, tolera false positives de plantillas).

---

#### S8: Inspector determinista y gate

**Objetivo:** `backend/scripts/security_check.py` + `governance/GATE-SEC-SECURITY.md` + targets `make security`/`make security-report`.

**Estado:** [x] Completado

**Evidencia:**
- `backend/scripts/security_check.py` + `governance/GATE-SEC-SECURITY.md` creados.
- Targets `make security` (bloquea si falta control) y `make security-report` (matriz informativa) operativos.

---

#### S9: Skills de seguridad (6 dominio + 2 técnicas) + AGENTS.md

**Objetivo:** Skills atómicas de amenaza (`domain/`) y técnicas (`tech/`) + actualizar `AGENTS.md`.

**Estado:** [x] Completado

**Evidencia:**
- 8 skills creadas (6 `domain/` + 2 `tech/`) y referenciadas en `AGENTS.md` con sus responsabilidades.

---

#### S10: Pruebas de seguridad (unit/integración/e2e) + GATE-SEC en AGENTS.md + verificación final

**Objetivo:** Ligar cada control del catálogo a su prueba con marcadores; documentar `GATE-SEC` como gate perpetuo; verificación final.

**Estado:** [x] Completado

**Evidencia:**
- Marcadores OWASP en tests backend (`pytest.mark.security("<ID>")`) y frontend (`// security: <ID>`); GATE-SEC documentado en `AGENTS.md`.
- `make security` verde (16/16 pruebas/chequeos sobre 14 controles); suite backend 617 passed con coverage 96.66%; `pnpm test:unit` 47 verdes; e2e de aislamiento con usuario 2 añadido (`make e2e`).

---

### FASE: Docker y verificación del pipeline (PRD 3.0)

#### T10: Docker y verificación del pipeline

**Objetivo:** Servicio `pipeline` en contenedor con el mismo código + `make docker-verify` con muestra Bronze congelada.

**Estado:** [x] Completado

**Evidencia:**
- Fixture congelado `backend/tests/fixtures/bronze/` (8 conferencias HTML gob.mx) sin descargas.
- `pipeline/verify.py` (`load_frozen_bronze`, `ensure_verify_database`, `verify_pipeline`) + CLI `pipeline verify`.
- Test `tests/test_pipeline/test_verify.py` valida Bronze→Silver→Gold→clustering→etiquetado por capa (mocks solo en la frontera HTTP de Ollama/llamacpp).
- `Dockerfile.pipeline` + servicio `pipeline` (perfil) en `docker-compose.yml`; `make docker-verify` reproducible.
- `make docker-verify` (Ollama + llamacpp reales via host): Bronze 8, Silver 8/16/0, Gold 8/8, clustering 2/0, etiquetado 2/0 — idéntico en dos ejecuciones.
- Suite backend 621 passed, coverage 96.70%; `ruff`/`ty` sin errores; `make security` verde.

---

#### T11: Adaptadores Gemini y reindexación productiva

**Objetivo:** Adaptadores Gemini (embeddings + chat) aislados, metadatos de índice con validación fail-closed y reindexación total hacia un índice Neon independiente y versionado.

**Estado:** [x] Completado

**Evidencia:**
- `services/gemini_embedding.py` (`GeminiEmbeddingAdapter`: `embed_documents`/`embed_query`, 768 dims, normalización L2, tareas `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`) y `services/gemini_chat.py` (`GeminiChatAdapter.generate`) con `google-genai` (SDK oficial) aislado en adaptadores.
- `schemas/index_metadata.py` + `db/index_metadata.py` (tabla `index_metadata`: proveedor, modelo, dimensión, tarea, versión de formato, fecha, hash de corpus) con upsert y lectura.
- `services/index_metadata.py`: `validate_query_config` (fail-closed, CA-R05) + `validate_index_at_startup` (no-op en local; en producción valida modelo/dimensión/tarea contra metadatos y aborta el arranque si no coinciden). Cableado en `main.py` lifespan.
- `services/reindex_production.py::reindex_corpus`: re-embebido TOTAL hacia un índice separado (`target_table`) con `ON CONFLICT` y registro de metadatos (CA-R06: índices local/productivo físicamente separados).
- `db/pgvector_conn.py::build_neon_connection_string`: exige endpoint agrupado (`-pooler`) y `sslmode=require` (TLS).
- `config.py`: settings productivos (`gemini_api_key`, `gemini_embedding_model`, `gemini_chat_model`, `gemini_embedding_dimension`, `index_format_version`, `neon_database_url`) + `is_production`.
- `.env.template` ampliado y `.env.production.example` creado (placeholders, sin secretos).
- `tests/test_gemini_adapters.py`: 24 tests (adaptadores mockeados en la frontera de `google-genai`, normalización, fail-closed, TLS/pooling, validación de metadatos, reindexación con separación de índices).
- Suite backend 645 passed, coverage 96.68%; `ruff`/`ty` sin errores.

#### T12: Cloud Run + Neon (Terraform)

**Objetivo:** Despliegue real a GCP con IaC Terraform (Cloud Run + Neon + Secret Manager), build productivo single-origin web+API, conexion productiva a Neon (TLS+pooler) y URL `run.app` viva que cumple CA-D04…CA-D08.

**Estado:** [x] Completado

**Evidencia:**
- `infra/terraform/` (IaC): estado remoto en GCS `rag-conferencias-matutinas-tfstate`, SA `lakehouse-cloudrun` con minimos privilegios (solo `secretAccessor`), Cloud Run `max-instances=1` escala a cero (1 vCPU / 1Gi / concurrencia 10), Artifact Registry `lakehouse`, 4 secretos nuevos con random_password (JWT, CSRF, contraseñas demo) referenciando los existentes GEMINI_API_KEY/NEON_DATABASE_URL. `terraform validate`/`plan`/`apply` limpios; lockfile commiteado; `terraform.tfvars` gitignored.
- Secret Manager con **6 versiones activas** (se deshabilitaron los legacy `POSTGRES_USER`/`POSTGRES_PASSWORD` que no usa la app).
- **Build unico single-origin:** `Dockerfile` raiz multi-stage (frontend `pnpm build` con `VITE_API_BASE=''` + runtime uvicorn sirviendo `dist/` con fallback SPA desde FastAPI; `main.py::_mount_frontend_static`). `.dockerignore` excluye secretos/corpus/git.
- **Conexion productiva a Neon:** `db/connection.py::get_database_url` (prod → `neon_database_url` + TLS vía `build_neon_connection_string`, fail-closed; local → URL actual) sustituyendo los builders dispersos; `pg_connect`/`pg_conn_str_with_timeouts` omiten el startup parameter `statement_timeout` en endpoints `-pooler` (Neon lo rechaza).
- **CLI de reindexacion:** `pipeline reindex-production` (bootstrap Neon idempotente + GeminiEmbeddingAdapter + `reindex_corpus`); corpus reindexado **11120/11120** embeddings a Neon con `index_metadata` = google/`gemini-embedding-001`/768/RETRIEVAL_DOCUMENT/v1 (fail-closed de arranque satisfecho).
- **Visuales productivas (clusters + 3D sobre Gemini):** `pipeline sync-production-visuals` recalcula sobre los embeddings GEMINI de Neon (sin mezclar espacios) reutilizando UMAP-3D (`embedding_3d` en 11120 filas), UMAP+HDBSCAN (**52 clusters** con run `7aca59fb…`) y etiquetado (**52/52 completados**); `/clusters/latest` devuelve 52 clusters etiquetados + ruido y `/embeddings/3d` devuelve 11,120 puntos 3D en la URL productiva.
- **Gateway proveedor prod/local:** `agent/llm.py::chat_json/chat_text` y `rag_search.embed_search_query` despachan a Gemini en produccion (embeddings `RETRIEVAL_QUERY`, chat `gemini-3.5-flash-lite`) y a llama.cpp/Ollama en local. `GeminiChatAdapter` extrae el system prompt a `system_instruction` y mapea roles a `user`/`model` (Gemini no acepta role `system`). Afecta planner/synthesizer/chat router/temporal parser/tools.
- `scripts/gcp_cost.py` determinista (snapshot de precios 2026-09-05) + `scripts/gcp_cost.example.json`: **total mensual estimado USD 0.00, within_free_tier=true**.
- **URL productiva:** `https://rag-del-pueblo-iens6os2ba-uc.a.run.app` (servicio Cloud Run `rag-del-pueblo`; antes `lakehouse-mananeras`)
  - `GET /health` publico → `{"status":"ok","version":"0.1.0"}` (CA-D05).
  - Login OK con ambos usuarios demo; `/auth/me`; crear/listar/retomar/borrar conversaciones (CA-D04).
  - Aislamiento: usuario 2 no lista conversaciones del 1 y obtiene `404` al leer/borrar las ajenas (CA-D06).
  - Turno del agente en UI: pregunta de salud → respuesta con **5 fuentes citadas**, `buscar_declaraciones` en tool_executions, `model_used=gemini-3.5-flash-lite`, token_usage y latency visibles (CA-D04/D08).
- Gates: backend **675 passed**, cobertura **96.34%** (`--cov-fail-under=90`); `ruff` y `ty` sin errores; frontend `pnpm typecheck` + `pnpm test:unit` (47) verdes; `make security` 16/16. Se corrigio YAML invalido en `frontend/pnpm-workspace.yaml` (`onlyBuiltDependencies`).

---

## Resumen de Checkpoints

| CP | Fase | Nombre | Estado |
|----|------|--------|--------|
| CP-00 | Infraestructura | Docker Compose + Directorios | [x] |
| CP-01 | Backend | Schemas Pydantic | [x] |
| CP-02 | Backend | Ingesta Bronze | [x] |
| CP-03 | Backend | Parsing Silver | [x] |
| CP-04 | Backend | Enriquecimiento Gold | [x] |
| CP-05 | Backend | FastAPI Health + Search | [x] |
| CP-06 | Backend | Chat Endpoint RAG | [x] |
| CP-07 | Backend | Observabilidad Endpoints | [x] |
| CP-08 | Backend | CLI Typer | [x] |
| CP-09 | Frontend | Setup Vue 3 + Vite + Tailwind | [x] |
| CP-10 | Frontend | Chat RAG UI | [x] |
| CP-11 | Frontend | Dashboard Observabilidad | [x] |
| CP-12 | QA | Test Suite + Coverage 90% | [x] |
| CP-13 | QA | Evaluacion RAG (LLM-as-a-Judge) | [x] |
| CP-14 | QA | Idempotencia End-to-End | [x] |
| CP-15 | Cierre | Docker Full Stack + DoD | [x] |
| CP-16 | Cierre | Interrupcion Graceful de Pipelines | [x] |
| T1 | Agente/Memoria/Auth | Verdad del proyecto | [x] |
| T2 | Agente/Memoria/Auth | Migraciones y repositorios | [x] |
| T3 | Agente/Memoria/Auth | Autenticacion, cookies y CSRF | [x] |
| T4 | Agente/Memoria/Auth | Aislamiento y memoria conversacional | [x] |
| T5 | Agente/Memoria/Auth | Rate limits | [x] |
| T6 | Agente/Memoria/Auth | Implementacion individual de cada tool | [x] |
| T7 | Agente/Memoria/Auth | Planificador y ejecutor agéntico | [x] |
| T8 | Agente/Memoria/Auth | Sintesis, evidencia y negativa | [x] |
| T9 | Agente/Memoria/Auth | Interfaz de login y conversaciones | [x] |
| S1 | Seguridad | Marcador `security` y catálogo de controles | [x] |
| S2 | Seguridad | Headers seguros (H1) | [x] |
| S3 | Seguridad | Docs en prod + CORS exacto (H2/H3) | [x] |
| S4 | Seguridad | Errores saneados (H4) | [x] |
| S5 | Seguridad | Límite de body (H5) | [x] |
| S6 | Seguridad | Timeouts BD/modelo (H5) | [x] |
| S7 | Seguridad | Escáner de secretos (H6) | [x] |
| S8 | Seguridad | Inspector determinista + gate | [x] |
| S9 | Seguridad | Skills de seguridad + AGENTS.md | [x] |
| S10 | Seguridad | Pruebas de seguridad + GATE-SEC + verificación | [x] |
| T10 | Agente/Memoria/Auth | Docker y verificación del pipeline | [x] |
| T11 | Agente/Memoria/Auth | Adaptadores Gemini y reindexación productiva | [x] |
| T12 | Agente/Memoria/Auth | Cloud Run + Neon via Terraform | [x] |
| T13 | Agente/Memoria/Auth | Verificacion parser temporal contra Gemini (CLI + integracion) | [x] |
