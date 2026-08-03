# AGENTS.md — Lakehouse Mañaneras
## PROPOSITO

Este archivo define las reglas perpetuas de gobernanza, calidad y comportamiento para cualquier agente
(humano o IA) que interactue con este repositorio. Todo `git commit` y toda ejecucion de feature debe
respetar estos gates.

---

## GATES DE CONTROL PERPETUOS

### Gate S: Calidad de Especificacion (antes de crear features)

Activacion: siempre que se solicite una feature nueva, un cambio de arquitectura o un refactor
mayor al pipeline de datos.

```
[BLOQUEO] → si no existe spec en docs/superpowers/specs/
[BLOQUEO] → si la spec no paso spec-review-loop (max 3 iteraciones)
[BLOQUEO] → si hay TBD/TODO/placeholders sin resolver
```

Reglas:
1. `/superpowers:brainstorming` es MANDATORIO. No se salta jamas.
2. `/superpowers:writing-plans` es MANDATORIO tras brainstorming aprobado.
3. NINGUN plan se aprueba automaticamente. El usuario debe revisarlo explicitamente.
4. Ver GATE-S-SPEC-QUALITY.md en `governance/` para criterios completos.

### Gate Q: Calidad de Implementacion (durante desarrollo)

Activacion: en cada commit, en cada checkpoint del plan de implementacion.

```
[BLOQUEO] → si tests < 90% coverage en modulo modificado
[BLOQUEO] → si ruff check o typecheck (ty/pyright) reportan errores
[BLOQUEO] → si hay prints/debugger/console.log no intencionales
[BLOQUEO] → si existen TODOs sin referencia a un issue/checkpoint del plan
```

Reglas:
1. `ruff check --fix && ruff format` antes de stage.
2. `ty` (typecheck estricto) antes de commit en backend.
3. `pnpm typecheck` antes de commit en frontend.
4. Todo checkpoint del plan DEBE pasar evidencia verificable (ver `IMPLEMENTATION_PLAN.md`).

### Gate QA: QA Obsesivo (antes de merge/cierre de feature)

Activacion: al completar un modulo del plan de implementacion.

```
[BLOQUEO] → si no se probaron casos borde explicitamente listados en la spec
[BLOQUEO] → si el LLM-as-a-Judge (evaluate-rag) no alcanza ≥ 90% fidelidad
[BLOQUEO] → si idempotencia no se verifica (filas_nuevas=0, duplicados=0 en reejecucion)
```

---

## SKILLS MANDATORIAS

Todo agente debe cargar y seguir estas skills. No son opcionales.

### Skills de Proceso (Meta)

| Skill | Archivo | Cuando usarla |
|-------|---------|---------------|
| Socratic Method | `.opencode/skills/meta/socratic-method/SKILL.md` | Antes de cualquier decision de diseno |
| Spec Review Loop | `.opencode/skills/meta/spec-review-loop/SKILL.md` | Despues de escribir una spec |
| Brainstorming | Superpowers | Antes de crear features |
| Writing Plans | Superpowers | Tras brainstorming aprobado |

### Skills Tecnicas

| Skill | Archivo | Dominio |
|-------|---------|---------|
| Python + uv + Ruff | `.opencode/skills/tech/python_uv_ruff.md` | Backend, CLI, Scripts |
| FastAPI + Pydantic + Typer | `.opencode/skills/tech/fastapi_pydantic_typer.md` | API, Validacion |
| Vue 3 + Pinia + Tailwind | `.opencode/skills/tech/vue3_pinia_tailwind.md` | Frontend |
| DuckDB + pgvector | `.opencode/skills/tech/duckdb_pgvector.md` | Datos, Vectores |
| Testing + QA | `.opencode/skills/tech/testing_qa.md` | Calidad |
| ECharts 3D Vue | .opencode/skills/tech/echarts_3d_vue.md | Visualización 3D |
| UMAP + HDBSCAN Clustering | `.opencode/skills/tech/umap_hdbscan_clustering.md` | Clustering semantico |
| LLM Auto-Labeling | `.opencode/skills/tech/llm_auto_labeling.md` | Etiquetado automatico |
### Skills de Dominio

| Skill | Archivo | Responsabilidad |
|-------|---------|-----------------|
| Idempotencia y Merge | `.opencode/skills/domain/idempotencia_y_merge.md` | Claves naturales, MERGE INTO |
| Arquitectura Medallon | `.opencode/skills/domain/arquitectura_medallon.md` | Flujo Bronze→Silver→Gold |
| Memoria RAG Tokens | `.opencode/skills/domain/memoria_rag_tokens.md` | Ventana de contexto |
| Payload Vectorial Limpio | `.opencode/skills/domain/payload_vectorial_limpio.md` | Formato texto para Ollama |
| Observabilidad Pull | `.opencode/skills/domain/observabilidad_pull.md` | Logs, semaforos, dashboard |

---

## REGLAS DE CONVIVENCIA CON EL CODIGO

- **Prohibido pyenv/pip/poetry.** Solo `uv` para gestion de dependencias Python 3.13.
- **Prohibido npm/yarn.** Solo `pnpm` para frontend.
- **Prohibido IDs aleatorios (UUID4, Snowflake).** Solo hashes concatenados deterministas.
- **Prohibido modificar archivos de skill sin actualizar AGENTS.md.**
- **Cero prints de debug en produccion.** Usar `logging` con niveles configurados por `APP_ENV`.
- **Todo endpoint debe documentarse.** Usar `summary` y `description` en decoradores FastAPI.
- **Commits atomicos.** Un commit = un proposito claro. Mensajes en espanol imperativo: "agrega ingesta bronze", "corrige race condition en merge".

---

## REFERENCIA RAPIDA DE COMANDOS

```bash
# Backend (desde backend/)
uv run ruff check --fix && uv run ruff format
uv run ty check
uv run pytest -xvs --cov=src --cov-report=term-missing

# Frontend (desde frontend/)
pnpm lint
pnpm typecheck
pnpm test:unit

# Evaluacion RAG (desde backend/)
python -m lakehouse evaluate-rag

# Docker
docker compose up -d --build
docker compose logs -f
```

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
[Implementacion por checkpoints]
    ↓ (en cada checkpoint)
[Gate Q] → ruff + ty + pytest (≥90% coverage)
    ↓
[Gate QA] → casos borde + evaluate-rag + idempotencia
    ↓
[Checkpoint completado → siguiente checkpoint]
```

---

## NOTAS PARA EL AGENTE

- Si entras a este repositorio sin instrucciones previas, lee primero `IMPLEMENTATION_PLAN.md` para conocer el estado actual.
- Cada Domain Skill referencia a la Tech Skill que utiliza. Sigue las referencias cruzadas.
- Si encuentras una violacion de gate, REPORTALA. No la ignores.
- El PRD maestro esta en `docs/prd/arquitectura_medallon_y_embbeding_CSP.md`. Es la fuente de verdad del producto.
