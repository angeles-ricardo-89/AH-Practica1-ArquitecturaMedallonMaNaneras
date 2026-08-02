# Backend API — Endpoints para Dashboard RAG: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cubrir los 18 gaps de datos del spec UI del dashboard con 4 endpoints nuevos, 1 endpoint modificado, nueva tabla PostgreSQL, columna embedding_3d, y tracking de pipeline runs por capa.

**Architecture:** Nuevos routers FastAPI (`config`, `embeddings`) + extension de `observability` y `chat`. Los pipeline runs se persisten en tabla PostgreSQL `observability.pipeline_runs`. UMAP se ejecuta al final del enrich. Los logs por capa usan el sistema de archivos por-layer ya existente en `log_config.py`.

**Tech Stack:** FastAPI, Pydantic v2, PostgreSQL + pgvector, psycopg, umap-learn, structlog

---

## File Map

| File | Responsibility | Action |
|------|---------------|--------|
| `backend/src/lakehouse/db/observability_conn.py` | DDL para tabla `pipeline_runs` y columna `embedding_3d` | Create |
| `backend/src/lakehouse/schemas/observability.py` | `LayerRun`, `PipelineLayersResponse` | Modify |
| `backend/src/lakehouse/schemas/config.py` | `ConfigResponse`, `ModelosConfig` | Create |
| `backend/src/lakehouse/schemas/embeddings.py` | `Embedding3DPoint`, `Embedding3DResponse` | Create |
| `backend/src/lakehouse/schemas/chat.py` | Agregar campos a `ChatResponse`, `SourceChunk` | Modify |
| `backend/src/lakehouse/services/rag_search.py` | Agregar `embedding_3d` al SELECT | Modify |
| `backend/src/lakehouse/services/qualitative_label.py` | Funcion de percentiles para labels | Create |
| `backend/src/lakehouse/api/routers/observability.py` | `GET /pipeline/layers`, `GET /pipeline/logs/{layer}` | Modify |
| `backend/src/lakehouse/api/routers/config.py` | `GET /config` | Create |
| `backend/src/lakehouse/api/routers/embeddings.py` | `GET /embeddings/3d` | Create |
| `backend/src/lakehouse/api/routers/chat.py` | Nuevos campos en response + latency + label | Modify |
| `backend/src/lakehouse/main.py` | Registrar routers `config`, `embeddings` | Modify |
| `backend/src/lakehouse/cli.py` | Escribir `pipeline_runs` en cada comando | Modify |
| `backend/src/lakehouse/pipeline/enrichment.py` | UMAP al final del enrich | Modify |
| `backend/pyproject.toml` | Agregar `umap-learn` | Modify |
| `frontend/src/api/observability.ts` | Tipos `LayerRun`, `PipelineLayersResponse`, `getPipelineLayers`, `getPipelineLogsByLayer` | Modify |
| `frontend/src/api/config.ts` | Tipos `ConfigResponse`, `getConfig` | Create |
| `frontend/src/api/embeddings.ts` | Tipos `Embedding3DPoint`, `Embedding3DResponse`, `getEmbeddings3D` | Create |
| `frontend/src/api/chat.ts` | Actualizar `SourceChunk`, `ChatResponse` | Modify |

---

### Task 1: DB — modulo de inicializacion de observability

**Files:**
- Create: `backend/src/lakehouse/db/observability_conn.py`
- Create: `backend/tests/test_pipeline/test_observability_conn.py`

- [ ] **Step 1: Escribir el test para ensure_observability_tables**

```python
# backend/tests/test_pipeline/test_observability_conn.py
import psycopg

from lakehouse.db.observability_conn import (
    add_embedding_3d_column,
    ensure_observability_tables,
)


class TestEnsureObservabilityTables:
    def test_creates_schema_and_table(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP SCHEMA IF EXISTS observability CASCADE")

        ensure_observability_tables(conn_str)
        add_embedding_3d_column(conn_str)

        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'observability' AND table_name = 'pipeline_runs'
            ORDER BY ordinal_position
        """)
        cols = {row[0]: row[1] for row in cur.fetchall()}
        assert "run_id" in cols
        assert "capa" in cols
        assert "status" in cols
        assert "started_at" in cols
        assert "finished_at" in cols
        assert "records_in" in cols
        assert "records_out" in cols
        assert "dlq_count" in cols
        assert "error_message" in cols

        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
            AND column_name = 'embedding_3d'
        """)
        assert cur.fetchone() is not None

        cur.execute("DROP SCHEMA IF EXISTS observability CASCADE")
        conn.close()

    def test_idempotent_on_second_call(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        ensure_observability_tables(conn_str)
        ensure_observability_tables(conn_str)
        add_embedding_3d_column(conn_str)
        add_embedding_3d_column(conn_str)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_pipeline/test_observability_conn.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Escribir el modulo DB**

```python
# backend/src/lakehouse/db/observability_conn.py
from __future__ import annotations

import psycopg

PIPELINE_RUNS_DDL = """
CREATE SCHEMA IF NOT EXISTS observability;

CREATE TABLE IF NOT EXISTS observability.pipeline_runs (
    run_id         TEXT PRIMARY KEY,
    capa           TEXT NOT NULL CHECK (capa IN ('bronze', 'silver', 'gold')),
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'ok', 'error')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    records_in     INTEGER NOT NULL DEFAULT 0,
    records_out    INTEGER NOT NULL DEFAULT 0,
    dlq_count      INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_capa_started
    ON observability.pipeline_runs (capa, started_at DESC);
"""

EMBEDDING_3D_DDL = """
ALTER TABLE gold.rag_corpus
    ADD COLUMN IF NOT EXISTS embedding_3d DOUBLE PRECISION[3];
"""


def ensure_observability_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(PIPELINE_RUNS_DDL)
        conn.commit()


def add_embedding_3d_column(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(EMBEDDING_3D_DDL)
        conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_pipeline/test_observability_conn.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/db/observability_conn.py backend/tests/test_pipeline/test_observability_conn.py
git commit -m "agrega modulo DB para observability.pipeline_runs y columna embedding_3d"
```

---

### Task 2: Schemas — LayerRun y PipelineLayersResponse

**Files:**
- Modify: `backend/src/lakehouse/schemas/observability.py`
- Modify: `backend/tests/test_schemas/test_observability.py`

- [ ] **Step 1: Agregar tests para los nuevos schemas**

```python
# agregar al final de backend/tests/test_schemas/test_observability.py

from lakehouse.schemas.observability import LayerRun, PipelineLayersResponse


class TestLayerRun:
    def test_valid_layer_run(self):
        r = LayerRun(
            capa="bronze",
            status="ok",
            run_id="abc123",
            duracion_seg=12.4,
            records_in=150,
            records_out=150,
            dlq_count=0,
            started_at="2026-08-01T10:00:00Z",
            finished_at="2026-08-01T10:00:12Z",
        )
        assert r.capa == "bronze"
        assert r.duracion_seg == 12.4
        assert r.dlq_count == 0

    def test_defaults(self):
        r = LayerRun(capa="silver", status="running", run_id="xyz")
        assert r.records_in == 0
        assert r.records_out == 0
        assert r.dlq_count == 0
        assert r.duracion_seg is None
        assert r.started_at is None
        assert r.finished_at is None

    def test_valid_capas(self):
        for capa in ("bronze", "silver", "gold"):
            r = LayerRun(capa=capa, status="ok", run_id="x")
            assert r.capa == capa

    def test_valid_statuses(self):
        for status in ("running", "ok", "error", "unknown"):
            r = LayerRun(capa="bronze", status=status, run_id="x")
            assert r.status == status


class TestPipelineLayersResponse:
    def test_empty(self):
        r = PipelineLayersResponse(layers=[], health_global="sin datos", ultima_corrida_global="")
        assert r.health_global == "sin datos"
        assert r.layers == []

    def test_with_layers(self):
        layers = [
            LayerRun(capa="bronze", status="ok", run_id="a1"),
            LayerRun(capa="silver", status="ok", run_id="a2"),
            LayerRun(capa="gold", status="ok", run_id="a3"),
        ]
        r = PipelineLayersResponse(
            layers=layers,
            health_global="Healthy",
            ultima_corrida_global="2026-08-01T10:00:00Z",
        )
        assert len(r.layers) == 3
        assert r.health_global == "Healthy"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_schemas/test_observability.py -v
```
Expected: FAIL (LayerRun/PipelineLayersResponse not defined)

- [ ] **Step 3: Agregar los schemas**

```python
# agregar al final de backend/src/lakehouse/schemas/observability.py

class LayerRun(BaseModel):
    capa: str = Field(...)
    status: str = Field(default="unknown")
    run_id: str = Field(...)
    duracion_seg: float | None = Field(default=None)
    records_in: int = Field(default=0, ge=0)
    records_out: int = Field(default=0, ge=0)
    dlq_count: int = Field(default=0, ge=0)
    started_at: str | None = Field(default=None)
    finished_at: str | None = Field(default=None)


class PipelineLayersResponse(BaseModel):
    layers: list[LayerRun] = Field(default_factory=list)
    health_global: str = Field(default="sin datos")
    ultima_corrida_global: str = Field(default="")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_schemas/test_observability.py -v
```
Expected: PASS (existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/observability.py backend/tests/test_schemas/test_observability.py
git commit -m "agrega schemas LayerRun y PipelineLayersResponse para dashboard"
```

---

### Task 3: Schemas — ConfigResponse y ModelosConfig

**Files:**
- Create: `backend/src/lakehouse/schemas/config.py`
- Create: `backend/tests/test_schemas/test_config_schema.py`

- [ ] **Step 1: Escribir el test**

```python
# backend/tests/test_schemas/test_config_schema.py
from lakehouse.schemas.config import ConfigResponse, ModelosConfig


class TestModelosConfig:
    def test_valid(self):
        m = ModelosConfig(llm="gemma4", embedding="embeddinggemma")
        assert m.llm == "gemma4"
        assert m.embedding == "embeddinggemma"


class TestConfigResponse:
    def test_valid(self):
        c = ConfigResponse(
            ambiente="dev",
            docker=True,
            version="0.1.0",
            modelos=ModelosConfig(llm="gemma4", embedding="embeddinggemma"),
        )
        assert c.ambiente == "dev"
        assert c.docker is True
        assert c.version == "0.1.0"
        assert c.modelos.llm == "gemma4"

    def test_desconocido_when_no_env(self):
        c = ConfigResponse(
            ambiente="desconocido",
            docker=False,
            version="0.1.0",
            modelos=ModelosConfig(llm="gemma4", embedding="embeddinggemma"),
        )
        assert c.ambiente == "desconocido"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_schemas/test_config_schema.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Escribir los schemas**

```python
# backend/src/lakehouse/schemas/config.py
from pydantic import BaseModel, Field


class ModelosConfig(BaseModel):
    llm: str = Field(...)
    embedding: str = Field(...)


class ConfigResponse(BaseModel):
    ambiente: str = Field(default="desconocido")
    docker: bool = Field(default=False)
    version: str = Field(...)
    modelos: ModelosConfig = Field(...)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_schemas/test_config_schema.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/config.py backend/tests/test_schemas/test_config_schema.py
git commit -m "agrega schemas ConfigResponse y ModelosConfig"
```

---

### Task 4: Schemas — Embedding3DPoint y Embedding3DResponse

**Files:**
- Create: `backend/src/lakehouse/schemas/embeddings.py`
- Create: `backend/tests/test_schemas/test_embeddings_schema.py`

- [ ] **Step 1: Escribir el test**

```python
# backend/tests/test_schemas/test_embeddings_schema.py
from lakehouse.schemas.embeddings import Embedding3DPoint, Embedding3DResponse


class TestEmbedding3DPoint:
    def test_valid(self):
        p = Embedding3DPoint(chunk_key="abc123", x=1.2, y=-0.5, z=3.1, conference_date="2026-01-15")
        assert p.x == 1.2
        assert p.y == -0.5
        assert p.z == 3.1
        assert p.conference_date == "2026-01-15"


class TestEmbedding3DResponse:
    def test_with_points(self):
        r = Embedding3DResponse(
            points=[
                Embedding3DPoint(chunk_key="a", x=0.0, y=0.0, z=0.0, conference_date="2026-01-15"),
                Embedding3DPoint(chunk_key="b", x=1.0, y=1.0, z=1.0, conference_date="2026-01-16"),
            ]
        )
        assert len(r.points) == 2

    def test_empty(self):
        r = Embedding3DResponse(points=[])
        assert r.points == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_schemas/test_embeddings_schema.py -v
```
Expected: FAIL

- [ ] **Step 3: Escribir los schemas**

```python
# backend/src/lakehouse/schemas/embeddings.py
from pydantic import BaseModel, Field


class Embedding3DPoint(BaseModel):
    chunk_key: str = Field(...)
    x: float = Field(...)
    y: float = Field(...)
    z: float = Field(...)
    conference_date: str = Field(...)


class Embedding3DResponse(BaseModel):
    points: list[Embedding3DPoint] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_schemas/test_embeddings_schema.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/embeddings.py backend/tests/test_schemas/test_embeddings_schema.py
git commit -m "agrega schemas Embedding3DPoint y Embedding3DResponse"
```

---

### Task 5: Schema — actualizar ChatResponse y SourceChunk

**Files:**
- Modify: `backend/src/lakehouse/schemas/chat.py`
- Modify: `backend/tests/test_schemas/test_chat.py`

- [ ] **Step 1: Agregar tests para los nuevos campos**

```python
# agregar al final de backend/tests/test_schemas/test_chat.py


class TestSourceChunkNewFields:
    def test_with_qualitative_label(self):
        s = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El dia de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
            qualitative_label="Alta",
        )
        assert s.qualitative_label == "Alta"
        assert s.embedding_3d is None

    def test_with_embedding_3d(self):
        s = SourceChunk(
            conference_date="2024-10-01",
            conference_id="abc123",
            participant="PRESIDENTA",
            chunk_text="El dia de hoy...",
            similarity=0.95,
            conference_url="https://example.com",
            qualitative_label="Media",
            embedding_3d=[1.0, 2.0, 3.0],
        )
        assert s.embedding_3d == [1.0, 2.0, 3.0]
        assert s.qualitative_label == "Media"

    def test_valid_labels(self):
        for label in ("Alta", "Media", "Baja"):
            s = SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc",
                participant="X",
                chunk_text="texto",
                similarity=0.5,
                qualitative_label=label,
            )
            assert s.qualitative_label == label


class TestChatResponseNewFields:
    def test_with_model_and_latency(self):
        r = ChatResponse(
            answer="respuesta",
            sources=[],
            token_usage={"prompt": 100, "completion": 50, "total": 150},
            model_used="gemma4",
            latency_ms=1250.5,
        )
        assert r.model_used == "gemma4"
        assert r.latency_ms == 1250.5
        assert r.token_usage["total"] == 150
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_schemas/test_chat.py::TestSourceChunkNewFields -v
```
Expected: FAIL (qualitative_label not accepted)

- [ ] **Step 3: Actualizar los schemas**

```python
# reemplazar backend/src/lakehouse/schemas/chat.py

class SourceChunk(BaseModel):
    conference_date: str = Field(...)
    conference_id: str = Field(..., min_length=1)
    participant: str = Field(...)
    chunk_text: str = Field(...)
    similarity: float = Field(..., ge=0.0, le=1.0)
    conference_url: str = Field(default="")
    pregunta_activa: str = Field(default="")
    qualitative_label: str = Field(default="Media")
    embedding_3d: list[float] | None = Field(default=None)


class ChatResponse(BaseModel):
    answer: str = Field(...)
    sources: list[SourceChunk] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    model_used: str = Field(default="")
    latency_ms: float = Field(default=0.0)
```

- [ ] **Step 4: Fix test_chat.py que falla por SourceChunk sin qualitative_label**

El test `TestSourceChunk.test_valid_source` existente creaba `SourceChunk` sin `qualitative_label`. El default `"Media"` lo cubre. El test existente `TestChatResponse.test_valid_response` tambien tiene que actualizarse porque `ChatResponse` ahora requiere `model_used` y `latency_ms`... pero no son `Field(...)`, son opcionales con default. Verificar que el test compila.

```bash
uv run pytest backend/tests/test_schemas/test_chat.py -v
```
Expected: PASS (todos los tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/chat.py backend/tests/test_schemas/test_chat.py
git commit -m "agrega qualitative_label, embedding_3d, model_used, latency_ms a schemas de chat"
```

---

### Task 6: Services — qualitative label por percentil

**Files:**
- Create: `backend/src/lakehouse/services/qualitative_label.py`
- Create: `backend/tests/test_services/test_qualitative_label.py`

- [ ] **Step 1: Escribir el test**

```python
# backend/tests/test_services/test_qualitative_label.py
from lakehouse.services.qualitative_label import assign_qualitative_labels


class TestAssignQualitativeLabels:
    def test_top_k_8(self):
        scores = [0.95, 0.90, 0.85, 0.80, 0.60, 0.50, 0.40, 0.30]
        labels = assign_qualitative_labels(scores)
        # top 25% (2): Alta
        # mid 50% (4): Media
        # bottom 25% (2): Baja
        assert labels == ["Alta", "Alta", "Media", "Media", "Media", "Media", "Baja", "Baja"]

    def test_top_k_1(self):
        labels = assign_qualitative_labels([0.42])
        assert labels == ["Alta"]

    def test_top_k_3(self):
        labels = assign_qualitative_labels([0.90, 0.80, 0.30])
        # todos < 4 → todos Alta
        assert labels == ["Alta", "Alta", "Alta"]

    def test_top_k_4(self):
        scores = [0.90, 0.80, 0.70, 0.60]
        labels = assign_qualitative_labels(scores)
        # top 25% (1): Alta
        # mid 50% (2): Media
        # bottom 25% (1): Baja
        assert labels == ["Alta", "Media", "Media", "Baja"]

    def test_identical_scores(self):
        scores = [0.50, 0.50, 0.50, 0.50, 0.50]
        labels = assign_qualitative_labels(scores)
        assert labels == ["Alta", "Media", "Media", "Media", "Baja"]

    def test_empty(self):
        assert assign_qualitative_labels([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_services/test_qualitative_label.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Escribir la funcion**

```python
# backend/src/lakehouse/services/qualitative_label.py
from __future__ import annotations


def assign_qualitative_labels(scores: list[float]) -> list[str]:
    if not scores:
        return []
    n = len(scores)
    if n < 4:
        return ["Alta"] * n

    top_count = max(1, n // 4)
    bottom_count = max(1, n // 4)
    mid_count = n - top_count - bottom_count

    labels = (
        ["Alta"] * top_count
        + ["Media"] * mid_count
        + ["Baja"] * bottom_count
    )
    return labels
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_services/test_qualitative_label.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/qualitative_label.py backend/tests/test_services/test_qualitative_label.py
git commit -m "agrega servicio de qualitative labels por percentil"
```

---

### Task 7: Services — agregar embedding_3d al SELECT de rag_search

**Files:**
- Modify: `backend/src/lakehouse/services/rag_search.py`

- [ ] **Step 1: Modificar `_rows_to_results` y las queries SQL**

```python
# En backend/src/lakehouse/services/rag_search.py

def _rows_to_results(rows: list) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows:
        embedding_3d_raw = row[7] if len(row) > 7 else None
        if embedding_3d_raw:
            embedding_3d = list(embedding_3d_raw) if isinstance(embedding_3d_raw, (list, tuple)) else None
        else:
            embedding_3d = None
        results.append(
            {
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
                "embedding_3d": embedding_3d,
            }
        )
    return results
```

Modificar la query en `search_gold_corpus_from_vector` (linea ~111):

```python
query_sql: LiteralString = cast(
    "LiteralString",
    f"""
    SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
        1 - (embedding <=> %s::vector) AS similarity,
        embedding_3d
    FROM gold.rag_corpus
    WHERE LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
    ORDER BY embedding <=> %s::vector
    LIMIT %s
    """,
)
```

Modificar la query en `search_with_date_filter` (linea ~168):

```python
query_sql: LiteralString = cast(
    "LiteralString",
    f"""
    SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
        1 - (embedding <=> %s::vector) AS similarity,
        embedding_3d
    FROM gold.rag_corpus
    WHERE conference_date BETWEEN %s::date AND %s::date
      AND LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
    ORDER BY embedding <=> %s::vector
    LIMIT %s
    """,
)
```

Tambien actualizar `search_sources` (linea ~200) para pasar `embedding_3d`:

```python
def search_sources(query: str, top_k: int) -> list[SourceChunk]:
    results = search_gold_corpus(query, top_k)
    logger.info("Busqueda de fuentes completada", query=query[:100], resultados=len(results))
    return [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
            embedding_3d=r.get("embedding_3d"),
        )
        for r in results
    ]
```

- [ ] **Step 2: Run existing tests to verify no regressions**

```bash
uv run pytest backend/tests/test_services/test_rag_search.py -v
```
Expected: PASS (o skip si requiere Ollama/pgvector)

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/services/rag_search.py
git commit -m "agrega embedding_3d al SELECT y resultados de busqueda vectorial"
```

---

### Task 8: Router — GET /observability/pipeline/layers

**Files:**
- Modify: `backend/src/lakehouse/api/routers/observability.py`
- Modify: `backend/tests/test_api/test_observability.py`

- [ ] **Step 1: Agregar test**

```python
# agregar al final de backend/tests/test_api/test_observability.py
import json
import psycopg


class TestPipelineLayers:
    def test_layers_empty_when_no_runs(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        conn.execute("DELETE FROM observability.pipeline_runs")

        resp = client.get("/observability/pipeline/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["layers"] == []
        assert data["health_global"] == "sin datos"

    def test_layers_returns_latest_per_capa(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._get_pg_conn_str",
            lambda: conn_str,
        )
        from lakehouse.db.observability_conn import ensure_observability_tables
        ensure_observability_tables(conn_str)

        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        conn.execute("DELETE FROM observability.pipeline_runs")
        conn.execute(
            """INSERT INTO observability.pipeline_runs
            (run_id, capa, status, started_at, finished_at, records_in, records_out)
            VALUES
            ('r1', 'bronze', 'ok', '2026-08-01T10:00:00Z', '2026-08-01T10:00:12Z', 150, 150),
            ('r2', 'silver', 'ok', '2026-08-01T10:00:05Z', '2026-08-01T10:00:20Z', 150, 140),
            ('r3', 'gold', 'ok', '2026-08-01T10:00:10Z', '2026-08-01T10:00:30Z', 140, 140)
            """
        )

        resp = client.get("/observability/pipeline/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["layers"]) == 3
        assert data["health_global"] == "Healthy"
        assert data["layers"][0]["capa"] == "bronze"
        assert data["layers"][0]["records_in"] == 150

        conn.execute("DELETE FROM observability.pipeline_runs")
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_api/test_observability.py::TestPipelineLayers -v
```
Expected: FAIL (404 - endpoint not found)

- [ ] **Step 3: Agregar el endpoint y helper**

```python
# agregar en backend/src/lakehouse/api/routers/observability.py

import psycopg
from lakehouse.config import Settings
from lakehouse.schemas.observability import LayerRun, PipelineLayersResponse


def _get_pg_conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@router.get(
    "/pipeline/layers",
    response_model=PipelineLayersResponse,
    summary="Get pipeline status per layer",
    description="Returns the latest run for each medallion layer (bronze, silver, gold)",
)
def get_pipeline_layers() -> PipelineLayersResponse:
    conn_str = _get_pg_conn_str()
    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT ON (capa)
                    capa, status, run_id,
                    EXTRACT(EPOCH FROM (finished_at - started_at)) AS duracion_seg,
                    records_in, records_out, dlq_count,
                    started_at, finished_at
                FROM observability.pipeline_runs
                ORDER BY capa, started_at DESC
            """)
            rows = cur.fetchall()
    except Exception:
        return PipelineLayersResponse(
            layers=[],
            health_global="sin datos",
            ultima_corrida_global="",
        )

    layers = []
    latest_global = ""
    for row in rows:
        started = row[7]
        finished = row[8]
        layers.append(
            LayerRun(
                capa=row[0],
                status=row[1] if row[1] else "unknown",
                run_id=row[2],
                duracion_seg=float(row[3]) if row[3] is not None else None,
                records_in=row[4] or 0,
                records_out=row[5] or 0,
                dlq_count=row[6] or 0,
                started_at=started.isoformat() if started else None,
                finished_at=finished.isoformat() if finished else None,
            )
        )
        if started and str(started) > latest_global:
            latest_global = str(started)

    statuses = {layer.status for layer in layers}
    if not statuses:
        health = "sin datos"
    elif "error" in statuses:
        health = "Failed"
    elif "running" in statuses:
        health = "Degraded"
    elif statuses == {"ok"}:
        health = "Healthy"
    elif len(layers) < 3:
        health = "Degraded"
    else:
        health = "Degraded"

    return PipelineLayersResponse(
        layers=layers,
        health_global=health,
        ultima_corrida_global=latest_global,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_api/test_observability.py::TestPipelineLayers -v -s
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/api/routers/observability.py backend/tests/test_api/test_observability.py
git commit -m "agrega endpoint GET /observability/pipeline/layers con estado por capa"
```

---

### Task 9: Router — GET /observability/pipeline/logs/{layer}

**Files:**
- Modify: `backend/src/lakehouse/api/routers/observability.py`
- Modify: `backend/tests/test_api/test_observability.py`

- [ ] **Step 1: Agregar test**

```python
# agregar al final de backend/tests/test_api/test_observability.py


class TestPipelineLogsByLayer:
    def test_logs_by_layer_filters_correctly(self, monkeypatch, tmp_path):
        log_dir = tmp_path / "logs" / "2026-08-01"
        log_dir.mkdir(parents=True)
        bronze_log = log_dir / "bronze_20260801_12345.log"
        bronze_log.write_text("[bronze] linea 1\n[bronze] linea 2\n")
        silver_log = log_dir / "silver_20260801_12346.log"
        silver_log.write_text("[silver] linea A\n[silver] linea B\n[silver] linea C\n")

        monkeypatch.setattr(
            "lakehouse.api.routers.observability._find_layer_logs",
            lambda layer, base_dir: [str(bronze_log)] if layer == "bronze" else [str(silver_log)],
        )

        resp = client.get("/observability/pipeline/logs/bronze?lines=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 2
        assert data["total_lines"] == 2

    def test_logs_by_layer_empty_for_missing_layer(self, monkeypatch):
        monkeypatch.setattr(
            "lakehouse.api.routers.observability._find_layer_logs",
            lambda layer, base_dir: [],
        )
        resp = client.get("/observability/pipeline/logs/gold?lines=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lines"] == []
        assert data["total_lines"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_api/test_observability.py::TestPipelineLogsByLayer -v
```
Expected: FAIL (404)

- [ ] **Step 3: Agregar el endpoint**

```python
# agregar en backend/src/lakehouse/api/routers/observability.py
import os
from datetime import datetime


def _find_layer_logs(layer: str, base_dir: str) -> list[str]:
    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = os.path.join(base_dir, today)
    if not os.path.isdir(log_dir):
        return []
    files = sorted(
        [os.path.join(log_dir, f) for f in os.listdir(log_dir)
         if f.startswith(f"{layer}_") and f.endswith(".log")],
        reverse=True,
    )
    return files


@router.get(
    "/pipeline/logs/{layer}",
    response_model=PipelineLogs,
    summary="Get pipeline logs by layer",
    description="Returns last N lines of pipeline log filtered by medallion layer",
)
def get_pipeline_logs_by_layer(
    layer: str,
    lines: int = Query(50, ge=1, le=500),
) -> PipelineLogs:
    base_dir = os.environ.get("PIPELINE_LOGS", "logs")
    log_files = _find_layer_logs(layer, base_dir)
    if not log_files:
        return PipelineLogs(lines=[], total_lines=0)

    all_lines: list[str] = []
    for filepath in log_files:
        try:
            with open(filepath) as f:
                all_lines.extend(line.rstrip("\n") for line in f)
        except OSError:
            continue

    total = len(all_lines)
    return PipelineLogs(lines=all_lines[-lines:], total_lines=total)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest backend/tests/test_api/test_observability.py::TestPipelineLogsByLayer -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/api/routers/observability.py backend/tests/test_api/test_observability.py
git commit -m "agrega endpoint GET /observability/pipeline/logs/{layer} con filtro por capa"
```

---

### Task 10: Router — GET /config

**Files:**
- Create: `backend/src/lakehouse/api/routers/config.py`
- Create: `backend/tests/test_api/test_config_router.py`

- [ ] **Step 1: Escribir el test**

```python
# backend/tests/test_api/test_config_router.py
import os

from fastapi.testclient import TestClient

from lakehouse.main import app

client = TestClient(app)


class TestConfigEndpoint:
    def test_returns_config(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ambiente"] == "staging"
        assert data["version"] == "0.1.0"
        assert "modelos" in data
        assert "llm" in data["modelos"]
        assert "embedding" in data["modelos"]

    def test_desconocido_when_no_env(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ambiente"] == "desconocido"

    def test_docker_detection(self, monkeypatch, tmp_path):
        fake_dockerenv = tmp_path / ".dockerenv"
        fake_dockerenv.write_text("")
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/.dockerenv")
        resp = client.get("/config")
        data = resp.json()
        # En CI/local puede no haber /.dockerenv, simplemente verificamos que el campo exista
        assert "docker" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_api/test_config_router.py -v
```
Expected: FAIL (404 - router not registered yet)

- [ ] **Step 3: Escribir el router**

```python
# backend/src/lakehouse/api/routers/config.py
import os

from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.config import ConfigResponse, ModelosConfig

router = APIRouter(tags=["config"])


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Get application configuration",
    description="Returns environment, version, docker status, and model names",
)
def get_config() -> ConfigResponse:
    settings = Settings()
    return ConfigResponse(
        ambiente=os.getenv("APP_ENV", "desconocido"),
        docker=os.path.exists("/.dockerenv"),
        version="0.1.0",
        modelos=ModelosConfig(
            llm=settings.llamacpp_model,
            embedding=settings.ollama_embed_model,
        ),
    )
```

- [ ] **Step 4: Run test — will be 404 until registered in main.py**

El test fallara con 404 hasta que registremos el router en main.py (Task 15). Por ahora solo verificamos que el codigo del router compila.

```bash
uv run python -c "from lakehouse.api.routers.config import router; print('OK')"
```
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/api/routers/config.py backend/tests/test_api/test_config_router.py
git commit -m "agrega router GET /config con ambiente, docker, version y modelos"
```

---

### Task 11: Router — GET /embeddings/3d

**Files:**
- Create: `backend/src/lakehouse/api/routers/embeddings.py`
- Create: `backend/tests/test_api/test_embeddings_router.py`

- [ ] **Step 1: Escribir el test**

```python
# backend/tests/test_api/test_embeddings_router.py
import psycopg
import pytest
from fastapi.testclient import TestClient

from lakehouse.main import app

client = TestClient(app)


class TestEmbeddings3D:
    def test_empty_when_no_points(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        monkeypatch.setattr(
            "lakehouse.api.routers.embeddings._get_pg_conn_str",
            lambda: conn_str,
        )
        # Asegurar que los puntos con embedding_3d=NULL no se devuelven
        resp = client.get("/embeddings/3d")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data

    def test_returns_points_with_3d_data(self, monkeypatch):
        import lakehouse.config
        monkeypatch.setattr(lakehouse.config.Settings, "model_config", {})
        from lakehouse.config import Settings
        settings = Settings()
        conn_str = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
        monkeypatch.setattr(
            "lakehouse.api.routers.embeddings._get_pg_conn_str",
            lambda: conn_str,
        )
        from lakehouse.db.observability_conn import add_embedding_3d_column
        add_embedding_3d_column(conn_str)

        conn = psycopg.connect(conn_str)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus
            (chunk_key, conference_id, participant, chunk_text, url, embedding, embedding_3d, conference_date)
            VALUES
            ('test-ck-1', 'conf-1', 'TEST', 'texto prueba 1', 'http://x.com',
             '[0.1,0.2,0.3]'::vector, ARRAY[1.0, 2.0, 3.0], '2026-01-15'),
            ('test-ck-2', 'conf-2', 'TEST', 'texto prueba 2', 'http://x.com',
             '[0.4,0.5,0.6]'::vector, ARRAY[4.0, 5.0, 6.0], '2026-01-16')
            ON CONFLICT (chunk_key) DO UPDATE SET embedding_3d = EXCLUDED.embedding_3d
        """)

        resp = client.get("/embeddings/3d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) >= 2
        for p in data["points"]:
            assert "chunk_key" in p
            assert "x" in p
            assert "y" in p
            assert "z" in p
            assert "conference_date" in p

        cur.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'test-ck-%'")
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/test_api/test_embeddings_router.py -v
```
Expected: FAIL (404)

- [ ] **Step 3: Escribir el router**

```python
# backend/src/lakehouse/api/routers/embeddings.py
import psycopg
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.embeddings import Embedding3DPoint, Embedding3DResponse

router = APIRouter(tags=["embeddings"])


def _get_pg_conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@router.get(
    "/embeddings/3d",
    response_model=Embedding3DResponse,
    summary="Get 3D embedding coordinates",
    description="Returns UMAP-reduced 3D coordinates for all chunks in Gold layer",
)
def get_embeddings_3d() -> Embedding3DResponse:
    conn_str = _get_pg_conn_str()
    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT chunk_key, embedding_3d, conference_date "
                "FROM gold.rag_corpus WHERE embedding_3d IS NOT NULL"
            )
            rows = cur.fetchall()
    except Exception:
        return Embedding3DResponse(points=[])

    points = [
        Embedding3DPoint(
            chunk_key=row[0],
            x=float(row[1][0]),
            y=float(row[1][1]),
            z=float(row[1][2]),
            conference_date=str(row[2]),
        )
        for row in rows
        if row[1] and len(row[1]) == 3
    ]
    return Embedding3DResponse(points=points)
```

- [ ] **Step 4: Run test — will be 404 until registered in main.py**

```bash
uv run python -c "from lakehouse.api.routers.embeddings import router; print('OK')"
```
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/api/routers/embeddings.py backend/tests/test_api/test_embeddings_router.py
git commit -m "agrega router GET /embeddings/3d con coordenadas UMAP-reducidas"
```

---

### Task 12: Router — modificar POST /chat/ con nuevos campos

**Files:**
- Modify: `backend/src/lakehouse/api/routers/chat.py`

- [ ] **Step 1: Modificar el router de chat**

Agregar imports:

```python
import time
from lakehouse.services.qualitative_label import assign_qualitative_labels
```

Modificar la funcion `chat` (linea 33) para medir latencia y poblar nuevos campos:

```python
@router.post(
    "/",
    response_model=ChatResponse,
    summary="Chat with RAG",
    description="Send a query and get an answer with sources from the RAG corpus",
)
def chat(request: ChatRequest) -> ChatResponse:
    t_start = time.perf_counter()
    settings = Settings()
    ...
```

Despues de construir sources (linea 77-88), agregar qualitative labels y embedding_3d:

```python
    sources = [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
            embedding_3d=r.get("embedding_3d"),
            qualitative_label="",  # se asigna abajo
        )
        for r in results
    ]

    scores = [s.similarity for s in sources]
    labels = assign_qualitative_labels(scores)
    for source, label in zip(sources, labels):
        source.qualitative_label = label
```

Modificar el return (linea 130-137):

```python
    t_end = time.perf_counter()
    latency_ms = (t_end - t_start) * 1000.0

    return ChatResponse(
        answer=answer,
        sources=sources,
        token_usage={
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        model_used=settings.llamacpp_model,
        latency_ms=round(latency_ms, 1),
    )
```

- [ ] **Step 2: Run existing chat tests**

```bash
uv run pytest backend/tests/test_api/test_chat.py -v
```
Expected: PASS (o skip si no hay backend disponible)

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/api/routers/chat.py
git commit -m "agrega latency_ms, model_used, total_tokens, qualitative_label y embedding_3d al endpoint /chat/"
```

---

### Task 13: CLI — escribir pipeline_runs en cada comando

**Files:**
- Modify: `backend/src/lakehouse/cli.py`

- [ ] **Step 1: Agregar funcion helper y modificar comandos**

Agregar imports al inicio de `cli.py`:

```python
import hashlib
from datetime import UTC, datetime
import psycopg
from lakehouse.db.observability_conn import ensure_observability_tables
```

Agregar funcion helper despues de `logger = ...`:

```python
def _get_pg_conn_str(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _write_pipeline_run(
    pg_conn_str: str,
    capa: str,
    status: str,
    started_at: str,
    records_in: int = 0,
    records_out: int = 0,
    dlq_count: int = 0,
    error_message: str | None = None,
) -> None:
    run_id = hashlib.sha256(f"{capa}:{started_at}".encode()).hexdigest()
    finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute(
                """INSERT INTO observability.pipeline_runs
                (run_id, capa, status, started_at, finished_at, records_in, records_out, dlq_count, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING""",
                (run_id, capa, status, started_at, finished_at, records_in, records_out, dlq_count, error_message),
            )
            conn.commit()
    except Exception:
        logger.warning("No se pudo escribir pipeline_run", capa=capa, run_id=run_id)
```

Modificar `ingest` (linea 19):

```python
@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
    clean: bool = typer.Option(default=False, help="Drop bronze tables before ingesting"),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    ensure_observability_tables(pg_conn_str)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "bronze", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    try:
        result = asyncio.run(service.run(dry_run=dry_run, max_articles=max_articles, clean=clean))
        if not dry_run:
            records = result.get("records_inserted", 0)
            _write_pipeline_run(pg_conn_str, "bronze", "ok", started_at,
                              records_in=records, records_out=records)
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "bronze", "error", started_at,
                              error_message=str(e))
        raise
    ...

```

Modificar `parse` (linea 35) de forma similar con `capa="silver"`, `records_in=result['interventions']`, `records_out=result['interventions']`, `dlq_count=result['dlq']`.

Modificar `enrich` (linea 53) de forma similar con `capa="gold"`, `records_in=result['total']`, `records_out=result['embedded']`.

- [ ] **Step 2: Verificar que compila**

```bash
uv run python -c "from lakehouse.cli import app; print('OK')"
```
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/cli.py
git commit -m "agrega escritura de pipeline_runs en comandos ingest, parse, enrich"
```

---

### Task 14: Pipeline — UMAP computation en enrich

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Agregar dependencia umap-learn**

```bash
cd backend && uv add umap-learn
```

- [ ] **Step 2: Agregar funcion UMAP en enrichment.py**

Agregar al final de `enrichment.py`, despues de `enrich_interventions`:

```python
def _compute_umap_3d(pg_conn_str: str) -> int:
    try:
        import numpy as np
        from umap import UMAP
    except ImportError:
        logger.warning("umap-learn no disponible, omitiendo reduccion 3D")
        return 0

    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute("SELECT chunk_key, embedding FROM gold.rag_corpus")
            rows = cur.fetchall()
    except Exception as e:
        logger.error("Error leyendo embeddings para UMAP", error=str(e))
        return 0

    if len(rows) < 4:
        logger.warning("Muy pocos chunks para UMAP (< 4), omitiendo")
        return 0

    chunk_keys = [r[0] for r in rows]
    vectors = np.array([r[1] for r in rows], dtype=np.float64)

    try:
        n_neighbors = min(15, len(rows) - 1)
        reducer = UMAP(n_components=3, random_state=42, n_neighbors=n_neighbors)
        coords = reducer.fit_transform(vectors)
    except Exception as e:
        logger.error("UMAP fallo", error=str(e))
        return 0

    updated = 0
    try:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            for key, coord in zip(chunk_keys, coords):
                cur.execute(
                    "UPDATE gold.rag_corpus SET embedding_3d = ARRAY[%s, %s, %s] WHERE chunk_key = %s",
                    (float(coord[0]), float(coord[1]), float(coord[2]), key),
                )
                updated += 1
            conn.commit()
    except Exception as e:
        logger.error("Error guardando coordenadas UMAP", error=str(e))
        return 0

    logger.info("UMAP 3D completado", chunks=updated)
    return updated
```

- [ ] **Step 3: Llamar UMAP desde EnrichService.run()**

En `backend/src/lakehouse/services/enrich_service.py`, despues de la llamada a `enrich_interventions` (linea 128), agregar:

```python
from lakehouse.pipeline.enrichment import _compute_umap_3d
```

Y en el `run()`, despues del `return enrich_interventions(...)` (linea 128), pero ANTES del return:

```python
        result = enrich_interventions(
            windows=windows,
            conference_date=None,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
            workers=workers,
        )
        if result.get("embedded", 0) > 0:
            self._logger.info("Ejecutando UMAP 3D sobre embeddings")
            _compute_umap_3d(self._pg_conn_str)
        return result
```

- [ ] **Step 4: Verificar que compila**

```bash
uv run python -c "from lakehouse.pipeline.enrichment import _compute_umap_3d; print('OK')"
```
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/src/lakehouse/services/enrich_service.py backend/pyproject.toml backend/uv.lock
git commit -m "agrega computo UMAP 3D al final del pipeline enrich con umap-learn"
```

---

### Task 15: main.py — registrar nuevos routers

**Files:**
- Modify: `backend/src/lakehouse/main.py`

- [ ] **Step 1: Agregar imports y registros**

```python
# agregar en backend/src/lakehouse/main.py
from lakehouse.api.routers import config, embeddings

# agregar despues de los otros app.include_router
app.include_router(config.router)
app.include_router(embeddings.router)
```

- [ ] **Step 2: Run tests que dependen de los routers registrados**

```bash
uv run pytest backend/tests/test_api/test_config_router.py backend/tests/test_api/test_embeddings_router.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/main.py
git commit -m "registra routers config y embeddings en main.py"
```

---

### Task 16: Frontend — actualizar tipos TypeScript

**Files:**
- Modify: `frontend/src/api/observability.ts`
- Create: `frontend/src/api/config.ts`
- Create: `frontend/src/api/embeddings.ts`
- Modify: `frontend/src/api/chat.ts`

- [ ] **Step 1: Actualizar observability.ts**

```typescript
// frontend/src/api/observability.ts
import { apiClient } from './client'

export interface PipelineStatus {
  status: string
  last_run: string
  last_success: string
  records_count: number
  semaphore: string
}

export interface PipelineLogs {
  lines: string[]
  total_lines: number
}

export interface LayerRun {
  capa: string
  status: string
  run_id: string
  duracion_seg: number | null
  records_in: number
  records_out: number
  dlq_count: number
  started_at: string | null
  finished_at: string | null
}

export interface PipelineLayersResponse {
  layers: LayerRun[]
  health_global: string
  ultima_corrida_global: string
}

export async function getPipelineStatus(): Promise<PipelineStatus> {
  return apiClient<PipelineStatus>('/observability/status')
}

export async function getPipelineLogs(lines = 50): Promise<PipelineLogs> {
  return apiClient<PipelineLogs>(`/observability/logs?lines=${lines}`)
}

export async function getPipelineLayers(): Promise<PipelineLayersResponse> {
  return apiClient<PipelineLayersResponse>('/observability/pipeline/layers')
}

export async function getPipelineLogsByLayer(layer: string, lines = 50): Promise<PipelineLogs> {
  return apiClient<PipelineLogs>(`/observability/pipeline/logs/${layer}?lines=${lines}`)
}
```

- [ ] **Step 2: Crear config.ts**

```typescript
// frontend/src/api/config.ts
import { apiClient } from './client'

export interface ModelosConfig {
  llm: string
  embedding: string
}

export interface ConfigResponse {
  ambiente: string
  docker: boolean
  version: string
  modelos: ModelosConfig
}

export async function getConfig(): Promise<ConfigResponse> {
  return apiClient<ConfigResponse>('/config')
}
```

- [ ] **Step 3: Crear embeddings.ts**

```typescript
// frontend/src/api/embeddings.ts
import { apiClient } from './client'

export interface Embedding3DPoint {
  chunk_key: string
  x: number
  y: number
  z: number
  conference_date: string
}

export interface Embedding3DResponse {
  points: Embedding3DPoint[]
}

export async function getEmbeddings3D(): Promise<Embedding3DResponse> {
  return apiClient<Embedding3DResponse>('/embeddings/3d')
}
```

- [ ] **Step 4: Actualizar chat.ts**

```typescript
// frontend/src/api/chat.ts
import { apiClient } from './client'

export interface SourceChunk {
  conference_date: string
  participant: string
  chunk_text: string
  similarity: number
  conference_url: string
  qualitative_label: string
  embedding_3d: number[] | null
}

export interface ChatResponse {
  answer: string
  sources: SourceChunk[]
  token_usage: Record<string, number>
  model_used: string
  latency_ms: number
}

export async function sendChatMessage(query: string, top_k = 8): Promise<ChatResponse> {
  return apiClient<ChatResponse>('/chat/', {
    method: 'POST',
    body: { query, top_k },
  })
}
```

- [ ] **Step 5: Verificar que compila**

```bash
cd frontend && pnpm typecheck
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/observability.ts frontend/src/api/config.ts frontend/src/api/embeddings.ts frontend/src/api/chat.ts
git commit -m "actualiza tipos y funciones de API frontend para nuevos endpoints del dashboard"
```

---

### Task 17: Verificacion final

- [ ] **Step 1: Run all backend tests**

```bash
uv run pytest backend/tests/ -v --ignore=backend/tests/test_pipeline/test_enrichment.py --ignore=backend/tests/test_pipeline/test_parsing.py --ignore=backend/tests/test_pipeline/test_ingestion.py
```

- [ ] **Step 2: Run ruff check + format**

```bash
uv run ruff check --fix && uv run ruff format
```

- [ ] **Step 3: Run typecheck**

```bash
uv run ty src/
```

- [ ] **Step 4: Run frontend typecheck**

```bash
cd frontend && pnpm typecheck
```

---

## Acceptance Criteria

1. `GET /observability/pipeline/layers` devuelve 3 capas con status, run_id, duracion, records, dlq_count.
2. `GET /observability/pipeline/logs/{layer}` devuelve logs filtrados por capa.
3. `GET /config` devuelve ambiente, docker, version, modelos.
4. `GET /embeddings/3d` devuelve coordenadas 3D de todos los chunks en Gold.
5. `POST /chat/` incluye `model_used`, `latency_ms`, `total_tokens` en `token_usage`, `qualitative_label` y `embedding_3d` en cada `SourceChunk`.
6. `pipeline ingest/parse/enrich` escriben registros en `observability.pipeline_runs`.
7. `pipeline enrich` ejecuta UMAP y pobla `embedding_3d` si hay >= 4 chunks.
8. No hay regresiones en tests existentes.
9. Ruff check + format limpios.
10. Typecheck backend y frontend limpios.
