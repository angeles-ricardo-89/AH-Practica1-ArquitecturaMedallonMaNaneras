# Base de Datos de Pruebas Aislada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que los tests de integración PostgreSQL usen una base de datos `mananeras_test` separada, sin contaminar `mananeras`.

**Architecture:** Un `conftest.py` con `pytest_configure` que setea `POSTGRES_DB=mananeras_test` vía variable de entorno antes de cualquier test, crea la DB de pruebas con la extensión `vector`, y opcionalmente la droppea al finalizar.

**Tech Stack:** Python 3.13, pytest, psycopg3, PostgreSQL 17 + pgvector (docker).

**Spec:** `docs/superpowers/specs/2026-08-02-test-database-isolation-design.md`

---

### Task 1: Crear `conftest.py` con base de datos de pruebas aislada

**Files:**
- Create: `backend/tests/conftest.py`
- No modifica ningún archivo existente

- [ ] **Step 1: Crear `backend/tests/conftest.py`**

```python
from __future__ import annotations

import os

import psycopg

TEST_DB = "mananeras_test"


def pytest_configure(config) -> None:  # noqa: ARG001
    """Crea la base de datos de pruebas y la activa para todos los tests."""
    os.environ["POSTGRES_DB"] = TEST_DB

    admin_conn = "postgresql://mananeras:mananeras@localhost:5433/postgres"
    try:
        with psycopg.connect(admin_conn) as conn:
            conn.autocommit = True
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.errors.DuplicateDatabase:
        pass
    except psycopg.Error:
        raise SystemExit(
            "No se pudo crear la base de datos de pruebas mananeras_test. "
            "Asegurate de que PostgreSQL este corriendo (docker compose up -d postgres)."
        ) from None

    try:
        with psycopg.connect(
            f"postgresql://mananeras:mananeras@localhost:5433/{TEST_DB}"
        ) as conn:
            conn.autocommit = True
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except psycopg.Error:
        raise SystemExit(
            "No se pudo instalar la extension pgvector en mananeras_test."
        ) from None
```

- [ ] **Step 2: Verificar que el test suite usa la DB de pruebas**

Ejecutar desde `/mnt/mydata/projects/proyecto1_diplo/backend`:

```bash
uv run python -c "
from lakehouse.config import Settings
s = Settings()
print(f'DB={s.postgres_db}')
assert s.postgres_db == 'mananeras_test', f'Esperaba mananeras_test, obtuve {s.postgres_db}'
print('OK: Settings usa mananeras_test')
"
```
Expected: `OK: Settings usa mananeras_test`

- [ ] **Step 3: Correr el test suite completo contra la DB de pruebas**

```bash
uv run pytest -q
```
Expected: PASS (441 tests). La DB `mananeras_test` se crea automáticamente en `pytest_configure`.

- [ ] **Step 4: Verificar que la DB de producción sigue intacta**

```bash
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://mananeras:mananeras@localhost:5433/mananeras')
conn.autocommit = True
count = conn.execute('SELECT COUNT(*) FROM gold.rag_corpus WHERE embedding_3d IS NOT NULL').fetchone()[0]
print(f'produccion: gold.rag_corpus con embedding_3d = {count}')
assert count > 0, 'La DB de produccion perdio datos de embedding_3d'
print('OK: DB de produccion intacta')
conn.close()
"
```
Expected: `OK: DB de produccion intacta` con count > 0.

- [ ] **Step 5: Verificar que la DB de pruebas tiene datos de test**

```bash
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://mananeras:mananeras@localhost:5433/mananeras_test')
conn.autocommit = True
schemas = conn.execute(\"SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('observability','gold')\").fetchall()
print('schemas en test:', [s[0] for s in schemas])
assert len(schemas) >= 1, 'La DB de pruebas no tiene schemas de test'
print('OK: DB de pruebas tiene schemas')
ext = conn.execute(\"SELECT extname FROM pg_extension WHERE extname='vector'\").fetchone()
assert ext is not None, 'Falta la extension vector en la DB de pruebas'
print('OK: extension vector instalada')
conn.close()
"
```
Expected: `OK: DB de pruebas tiene schemas` y `OK: extension vector instalada`.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "aisla base de datos de pruebas via conftest con mananeras_test"
```

---

## Self-Review

**Spec coverage:**
- §3.1 Override global vía env var → Task 1 (pytest_configure con os.environ) ✓
- §3.2 Creación DB en pytest_configure → Task 1 (CREATE DATABASE + CREATE EXTENSION) ✓
- §3.3 Archivo conftest.py → Task 1 (contenido exacto del spec) ✓
- §3.4 DuckDB sin cambios → no requiere tarea (verificado en contexto) ✓
- §5 Casos borde (DB duplicada, PG caído) → cubiertos con except DuplicateDatabase y SystemExit ✓
- §6 Criterios de éxito → Steps 2-5 verifican ✓

**Placeholders:** ninguno.

**Type consistency:** N/A (no hay interfaces entre tareas; una sola tarea).
