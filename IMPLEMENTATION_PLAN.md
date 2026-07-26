# IMPLEMENTATION PLAN — Lakehouse Mañaneras

## Metadatos

- **Version:** 0.1.0
- **PRD:** `docs/prd/arquitectura_medallon_y_embbeding_CSP.md`
- **Fecha de creacion:** 2026-07-26
- **Estado actual:** Planeacion aprobada, pendiente de ejecucion
- **Ultimo checkpoint completado:** N/A (ninguno iniciado)

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
- `uv run ty src/` sin errores.
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

## Resumen de Checkpoints

| CP | Fase | Nombre | Estado |
|----|------|--------|--------|
| CP-00 | Infraestructura | Docker Compose + Directorios | [x] |
| CP-01 | Backend | Schemas Pydantic | [x] |
| CP-02 | Backend | Ingesta Bronze | [x] |
| CP-03 | Backend | Parsing Silver | [ ] |
| CP-04 | Backend | Enriquecimiento Gold | [ ] |
| CP-05 | Backend | FastAPI Health + Search | [ ] |
| CP-06 | Backend | Chat Endpoint RAG | [ ] |
| CP-07 | Backend | Observabilidad Endpoints | [ ] |
| CP-08 | Backend | CLI Typer | [ ] |
| CP-09 | Frontend | Setup Vue 3 + Vite + Tailwind | [ ] |
| CP-10 | Frontend | Chat RAG UI | [ ] |
| CP-11 | Frontend | Dashboard Observabilidad | [ ] |
| CP-12 | QA | Test Suite + Coverage 90% | [ ] |
| CP-13 | QA | Evaluacion RAG (LLM-as-a-Judge) | [ ] |
| CP-14 | QA | Idempotencia End-to-End | [ ] |
| CP-15 | Cierre | Docker Full Stack + DoD | [ ] |
