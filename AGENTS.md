# AGENTS.md — Lakehouse Mañaneras

Reglas perpetuas de gobernanza, calidad y comportamiento para cualquier agente (humano o IA).
Todo `git commit` y toda ejecucion de feature debe respetar los gates de abajo.

- **PRD (fuente de verdad):** `docs/prd/arquitectura_medallon_y_embbeding_CSP.md`
- **Estado/checkpoints:** `IMPLEMENTATION_PLAN.md` (leer primero si entras sin contexto)

---

## MAPA DEL REPO

| Ruta | Que es |
|------|--------|
| `backend/` | Backend Python 3.13 (uv). Paquete instalable `lakehouse` en `backend/src/lakehouse` (`[tool.uv] package=true`). CLI Typer: `cli.py` / `__main__.py`. API FastAPI: `main.py`. Routers en `api/routers/`. Pipeline bronze→silver→gold en `pipeline/`. Mas `services/`, `db/`, `schemas/`, `prompts/`. |
| `frontend/` | Vue 3 + Pinia + Tailwind CSS 4 + ECharts/echarts-gl (pnpm). `src/api` (fetch contra `/api` via proxy Vite), `src/stores` (pinia), componentes por dominio: `dashboard/`, `pipeline/`, `chat/`, `inspector/`, `search/`, `shared/`. |
| `evaluacion/` | Evaluador externo del diplomado (paquete `evaluador`). NO es producto; ejecutar solo con `make evaluacion`. Corre aislado con su propio DuckDB temporal. |
| `data/` y `backend/data/lakehouse/` | Capas medallon (bronze/silver/gold). Artefactos generados, gitignored. El DuckDB real se crea en `backend/data/lakehouse/` al correr desde `backend/`; `data/lakehouse/` en raiz es solo scaffold con `.gitkeep`. |
| `docs/superpowers/{specs,plans}` | Specs y planes de feature (Gate S). |
| `governance/GATE-S-SPEC-QUALITY.md` | Criterios completos del Gate S. |
| `scripts/` | Utilidades del repo: `export_report_pdf.py` (genera el PDF del reporte), `gcp_cost.py` (costo determinista ~$0), `scan_secrets.py` (GATE-SEC). `scripts/pdf-tools/` = paquete pnpm con mermaid-cli (render de diagramas). |
| `infra/terraform/` | IaC productivo GCP (Cloud Run, Neon, Secret Manager, Gemini). `*.tfvars`/`*.tfstate` gitignored; estado remoto en GCS. |
| `docs/reporte.md` → `docs/reporte.pdf` | Reporte final: fuente Markdown editable (diagramas mermaid inline) y PDF generado (ambos commiteados). Portada `docs/Portada-reporte.png`; capturas en `docs/evidence/`. |

Docker Compose levanta: `postgres` pgvector (expuesto `5433:5432`), `backend` (NO expuesto al host), `frontend` (`5174:5173`, corre `pnpm dev`). DB por defecto `mananeras/mananeras/mananeras`.

---

## ENTORNO LOCAL — GOTCHAS QUE UN AGENTE NO ADIVINA

- **Los tests de backend NO son hermeticos**: requieren Postgres+pgvector vivo en `localhost:5433`.
  `backend/tests/conftest.py` crea/usa la DB `mananeras_test` y aborta (`SystemExit`) si no hay postgres.
  Levanta antes: `docker compose up -d postgres`.
- **`.env` se lee relativo al CWD** (pydantic-settings `env_file=".env"`). Por eso los targets del Makefile hacen `cd backend`. El `.env` de raiz esta gitignored (copiar `.env.template`). El modelo de embed local es `embeddinggemma` (default de `config.py` y del template). Para produccion hay `.env.production.example` (Gemini + Neon); los valores reales viven en Secret Manager, nunca se commitean.
- **Ollama (embeddings) y llamacpp (chat) corren en el host**, nunca en docker. En docker se alcanzan via `host.docker.internal:11434` y `host.docker.internal:9200/v1`; en local `localhost:11434` / `localhost:9200/v1`. Sin ellos: `pipeline enrich` reintenta y deja registros sin embedding; `/chat` devuelve 503.
- **Frontend dev**: Vite proxya `/api` → `http://backend:8000` (`vite.config.ts`). Ese hostname solo resuelve dentro de la red de compose. Para ver la UI usa docker (`http://localhost:5174`); un `pnpm dev` en el host no llegara a la API salvo que definas un alias `backend`.
- El host expone **solo** postgres (5433) y frontend (5174); el backend de compose no tiene puerto publicado.

---

## GATES DE CONTROL PERPETUOS

### Gate S: Calidad de Especificacion (antes de crear features)

Activacion: feature nueva, cambio de arquitectura o refactor mayor del pipeline.

```
[BLOQUEO] → si no existe spec en docs/superpowers/specs/
[BLOQUEO] → si la spec no paso spec-review-loop (max 3 iteraciones)
[BLOQUEO] → si hay TBD/TODO/placeholders sin resolver
```

1. `/superpowers:brainstorming` es MANDATORIO; `/superpowers:writing-plans` tras brainstorming aprobado.
2. Ningun plan se aprueba solo: el usuario debe revisarlo explicitamente.
3. Criterios completos: `governance/GATE-S-SPEC-QUALITY.md`.

### Gate Q: Calidad de Implementacion (cada commit / checkpoint)

```
[BLOQUEO] → si tests < 90% coverage en el modulo modificado (pyproject ya fuerza --cov-fail-under=90)
[BLOQUEO] → si ruff check o typecheck (ty) reportan errores
[BLOQUEO] → si hay prints/debugger/console.log no intencionales
[BLOQUEO] → si existen TODOs sin referencia a un issue/checkpoint del plan
```

1. `ruff check --fix && ruff format` antes de stage (backend).
2. `ty check` (typecheck estricto) antes de commit en backend.
3. `pnpm typecheck` antes de commit en frontend.
4. Todo checkpoint del plan debe pasar con evidencia verificable (ver `IMPLEMENTATION_PLAN.md`).

### Gate I: Integracion y E2E reales (features de auth/memoria/agente/UI)

Los tests unitarios no prueban que la aplicacion funcione. Toda feature que toque
autenticacion, memoria, el agente o la UI exige evidencia real:

```
[BLOQUEO] → si no hay tests de integracion que ejerciten el flujo real (HTTP real + Postgres real)
            y solo simulen entidades EXTERNAS (Ollama/llamacpp/Gemini) en su frontera HTTP.
            Prohibido mockear servicios internos (run_agent_turn, tools, routers) en integracion.
[BLOQUEO] → si una feature toco auth/memoria/agente/UI y `make e2e` no esta verde contra un
            stack vivo (backend + Postgres real + llamacpp + Ollama). E2E = sin mocks en absoluto.
[BLOQUEO] → si el frontend no se verifico con un smoke en navegador real (login → dashboard →
            conversacion → turno del agente) sobre el stack de docker.
```

- Integracion: `backend/tests/test_api/test_agent_integration.py` y equivalentes; corren en la suite normal.
- E2E sin mocks: `uv run pytest tests/e2e -m e2e` contra un backend vivo (ver `make e2e`).
- Aprende del historial real: bugs que los unitarios no vieron (umbral de negativa descalibrado,
  `content` vacio por razonamiento de llamacpp, dependencia ausente en el contenedor de UI).

### Gate QA: QA Obsesivo (antes de merge/cierre de feature)

```
[BLOQUEO] → si no se probaron los casos borde listados en la spec
[BLOQUEO] → si el LLM-as-a-Judge (evaluate-rag) no alcanza ≥ 90% fidelidad
[BLOQUEO] → si la idempotencia no se verifica (filas_nuevas=0, duplicados=0 en reejecucion)
```

### Gate SEC: Seguridad OWASP (GATE-SEC)

Activacion: commit/checkpoint que toque auth, memoria, agente, UI, config, o que introduzca/ajuste un control de seguridad.

```
[BLOQUEO] → si make security sale != 0 (control del catalogo sin prueba que lo ejercite, lockfile ausente o secreto detectado)
[BLOQUEO] → si un control de governance/security-controls.yaml no tiene prueba/chequeo registrado
[BLOQUEO] → si una feature de seguridad se introduce sin registrar su control en governance/security-controls.yaml
[BLOQUEO] → si scripts/scan_secrets.py detecta un secreto rastreado por git
[BLOQUEO] → si se modifico un archivo de seguridad sin actualizar la skill correspondiente en .opencode/skills/
```

- Como correr: `make security` (bloquea) / `make security-report` (informa). Referencia: `governance/GATE-SEC-SECURITY.md` y `governance/security-controls.yaml`.
- Relacion con Gate Q: GATE-SEC se ejecuta en el ciclo de Gate Q (junto a ruff/ty/pytest), pero `make security` no lo sustituye por ninguno de esos checks.

---

## SKILLS MANDATORIAS (cargar y seguir; no son opcionales)

### De Proceso (Meta)

| Skill | Archivo | Cuando |
|-------|---------|--------|
| Socratic Method | `.opencode/skills/meta/socratic-method/SKILL.md` | Antes de cualquier decision de diseno |
| Spec Review Loop | `.opencode/skills/meta/spec-review-loop/SKILL.md` | Despues de escribir una spec |
| Brainstorming | Superpowers | Antes de crear features |
| Writing Plans | Superpowers | Tras brainstorming aprobado |

### Tecnicas

| Skill | Archivo | Dominio |
|-------|---------|---------|
| Python + uv + Ruff | `.opencode/skills/tech/python_uv_ruff.md` | Backend, CLI, Scripts |
| FastAPI + Pydantic + Typer | `.opencode/skills/tech/fastapi_pydantic_typer.md` | API, Validacion |
| Vue 3 + Pinia + Tailwind | `.opencode/skills/tech/vue3_pinia_tailwind.md` | Frontend |
| DuckDB + pgvector | `.opencode/skills/tech/duckdb_pgvector.md` | Datos, Vectores |
| Testing + QA | `.opencode/skills/tech/testing_qa.md` | Calidad |
| ECharts 3D Vue | `.opencode/skills/tech/echarts_3d_vue.md` | Visualizacion 3D |
| UMAP + HDBSCAN Clustering | `.opencode/skills/tech/umap_hdbscan_clustering.md` | Clustering semantico |
| LLM Auto-Labeling | `.opencode/skills/tech/llm_auto_labeling.md` | Etiquetado automatico |
| Autenticacion JWT | `.opencode/skills/tech/autenticacion_jwt.md` | Cookie HttpOnly, CSRF, Argon2, usuarios demo |
| Security Headers + Middleware | `.opencode/skills/tech/security_headers.md` | Headers CSP/CORS/docs/body |
| Testing de Seguridad | `.opencode/skills/tech/security_testing.md` | Pruebas con marcadores OWASP y gate |
| Terraform GCP | `.opencode/skills/tech/terraform_gcp.md` | IaC Cloud Run, Neon, Secret Manager, Gemini |
| Config Runtime GCP | `.opencode/skills/tech/config_runtime_gcp.md` | Cloud Run runtime, Neon TLS, modelos Gemini |
| Costo Infraestructura GCP | `.opencode/skills/tech/costo_infraestructura_gcp.md` | Herramienta determinista de costo (~$0) |

### De Dominio

| Skill | Archivo | Responsabilidad |
|-------|---------|-----------------|
| Idempotencia y Merge | `.opencode/skills/domain/idempotencia_y_merge.md` | Claves naturales, MERGE INTO |
| Arquitectura Medallon | `.opencode/skills/domain/arquitectura_medallon.md` | Flujo Bronze→Silver→Gold |
| Memoria RAG Tokens | `.opencode/skills/domain/memoria_rag_tokens.md` | Ventana de contexto |
| Memoria Conversacional | `.opencode/skills/domain/memoria_conversacional.md` | Aislamiento, retencion 30d, borrado |
| Agente de Investigacion | `.opencode/skills/domain/agente_investigacion.md` | Plan JSON, 3 tools solo lectura, negativa |
| Payload Vectorial Limpio | `.opencode/skills/domain/payload_vectorial_limpio.md` | Formato texto para Ollama |
| Observabilidad Pull | `.opencode/skills/domain/observabilidad_pull.md` | Logs, semaforos, dashboard |
| Security Auth + JWT | `.opencode/skills/domain/security-auth-jwt.md` | JWT, Argon2, cookies, login rate-limit |
| Security CSRF | `.opencode/skills/domain/security-csrf.md` | Token HMAC en header, SameSite como refuerzo |
| Security Control de Acceso | `.opencode/skills/domain/security-access-control.md` | user_id del JWT, ajena -> 404, aislamiento |
| Security Inyeccion y Agencia | `.opencode/skills/domain/security-injection.md` | SQL parametrizado, 3 tools allowlist, plan JSON |
| Security Manejo de Salida | `.opencode/skills/domain/security-output-handling.md` | DOMPurify, errores saneados, logs sin detalle |
| Security Headers y Config | `.opencode/skills/domain/security-headers-config.md` | Headers CSP/CORS, docs prod, body, timeouts |

Cada Domain Skill referencia la Tech Skill que usa: sigue las referencias cruzadas.

---

## REGLAS DE CONVIVENCIA CON EL CODIGO

- **Prohibido pyenv/pip/poetry.** Solo `uv` para dependencias Python 3.13.
- **Prohibido npm/yarn.** Solo `pnpm` (frontend y `scripts/pdf-tools`).
- **Prohibido IDs aleatorios (UUID4, Snowflake).** Solo hashes concatenados deterministas.
- **Prohibido modificar archivos de skill sin actualizar AGENTS.md.**
- **Cero prints de debug en produccion.** Usar `logging` con niveles por `APP_ENV`.
- **Todo endpoint documentado.** Usar `summary` y `description` en decoradores FastAPI.
- **Commits atomicos**, mensaje en espanol imperativo: "agrega ingesta bronze", "corrige race condition en merge".

---

## REPORTE (ENTREGABLE PDF)

El reporte final es Markdown editable; el PDF es un artefacto generado (ambos commiteados).

- **Fuente:** `docs/reporte.md` (diagramas mermaid inline). Edita aqui; nunca edites el PDF a mano.
- **Generar:** `python3 scripts/export_report_pdf.py` — corre con el **Python del host**, NO con `uv`/venv del backend.
  Requiere en el host `pandoc`, `weasyprint`, `Pillow` y `Chrome/Chromium`, mas mermaid-cli instalado una vez con:
  `cd scripts/pdf-tools && PUPPETEER_SKIP_DOWNLOAD=true pnpm install` (usa el Chrome del sistema; no descarga Chromium).
- **Mermaid:** WeasyPrint no renderiza mermaid ni escala imagenes altas. El script renderiza cada bloque `mermaid` (code fence) a PNG con mermaid-cli y lo ajusta con Pillow para que quepa en una pagina. No intentes `max-height` en el CSS: WeasyPrint lo ignora.
- **Screenshots** (`docs/evidence/*.png`): capturalos con viewport **~1280x850**. A viewport grande (~1863px) el texto de la UI queda ilegible al reducirse al ancho de contenido del PDF (643px).
- Portada `docs/Portada-reporte.png` (A4) a pagina completa; el contenido arranca en la pagina 2.

---

## COMANDOS

```bash
# Postgres + pgvector (PREREQUISITO de los tests backend y del pipeline)
docker compose up -d postgres

# Backend (desde backend/; Makefile hace el cd por ti)
make lint            # ruff check
make lint-fix        # ruff check --fix + ruff format
make typecheck-backend   # ty check
make test-backend    # pytest --cov=src ... --cov-fail-under=90 (necesita postgres arriba)
uv run pytest tests/test_pipeline/test_ingestion.py   # test suelto; addopts ya aplican coverage
uv run python -m lakehouse verify-temporal-gemini  # [Gate QA] parser temporal contra Gemini

# Pipeline por etapas (Makefile en raiz). ARGS se pasan tal cual:
make pipeline-ingest ARGS="--dry-run"   # bronze (scrapea gob.mx)
make pipeline-parse                     # silver
make pipeline-enrich                    # gold: embeddings + clustering (requiere Ollama)
make pipeline-full

# Evaluacion RAG (backend): python -m lakehouse evaluate-rag

# Reporte (entregable): regenera el PDF desde docs/reporte.md (Python del host)
python3 scripts/export_report_pdf.py

# Seguridad (GATE-SEC)
make security            # GATE-SEC: bloquea si algun control de seguridad carece de prueba
make security-report     # GATE-SEC: reporta la matriz amenaza->control->prueba sin bloquear

# Frontend (desde frontend/)
pnpm lint
pnpm typecheck      # vue-tsc --noEmit
pnpm test:unit      # vitest run (no necesita backend)
pnpm build          # vue-tsc --noEmit && vite build

# Todo el stack en docker (UI en http://localhost:5174)
docker compose up -d --build
docker compose logs -f

# Evaluador del diplomado (no es producto)
make evaluacion
```

Notas:
- `backend/pyproject.toml` ya fija `addopts = "-xvs --cov=src ... --cov-fail-under=90"` y `testpaths=["tests"]`: un `uv run pytest` pelado basta para correr todo con el gate de coverage.
- Typecheck estricto: `ty` (no pyright; `opencode.json` lo deshabilita y usa el LSP de `ty`).

---

## CICLO DE VIDA DE UNA FEATURE

```
[Usuario pide feature]
    ↓
[Gate S] → /superpowers:brainstorming → spec en docs/superpowers/specs/
    ↓
[Gate S] → spec-review-loop (max 3 iteraciones)
    ↓
[Gate S] → /superpowers:writing-plans → IMPLEMENTATION_PLAN.md actualizado
    ↓
[Usuario APRUEBA plan explicitamente]
    ↓
[Implementacion por checkpoints]  → en cada uno [Gate Q] → ruff + ty + pytest (≥90%)
    ↓
[Gate QA] → casos borde + evaluate-rag + idempotencia
```

---

## NOTAS PARA EL AGENTE

- Sin contexto previo, lee primero `IMPLEMENTATION_PLAN.md` para conocer el estado actual y seguir los checkpoints en orden.
- Si encuentras una violacion de gate, REPORTALA. No la ignores.
- Los specs/plans tienen precedencia numerica de fecha en `docs/superpowers/`; el mas reciente refleja el trabajo en curso.
