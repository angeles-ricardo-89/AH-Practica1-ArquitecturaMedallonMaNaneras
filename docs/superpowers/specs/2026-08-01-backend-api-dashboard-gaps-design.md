# Spec Backend — Endpoints para Dashboard RAG

## 1. Objetivo

Cubrir los gaps de datos identificados entre el spec de UI del dashboard (`docs/prd/ui/spec_ui_dashboard_rag_mananeras.md`)
y los endpoints REST actuales del backend. El gap analysis revelo que **18 de 35 requisitos** de datos del spec
de UI no tienen cobertura con los 5 endpoints existentes.

Este spec define **4 endpoints nuevos**, **1 endpoint modificado**, cambios en esquemas Pydantic, una tabla nueva
en PostgreSQL, una columna nueva en `gold.rag_corpus`, y modificaciones al CLI del pipeline.

---

## 2. Endpoints nuevos

### 2.1 `GET /observability/pipeline/layers`

**Archivo:** `backend/src/lakehouse/api/routers/observability.py`

**Response model:** `PipelineLayersResponse`

```python
class LayerRun(BaseModel):
    capa: str                          # "bronze" | "silver" | "gold"
    status: str                        # "running" | "ok" | "error" | "unknown"
    run_id: str
    duracion_seg: float | None         # None si sigue corriendo
    records_in: int                    # default 0
    records_out: int                   # default 0
    dlq_count: int                     # default 0
    started_at: str | None
    finished_at: str | None

class PipelineLayersResponse(BaseModel):
    layers: list[LayerRun]
    health_global: str                 # "Healthy" | "Degraded" | "Failed" | "sin datos"
    ultima_corrida_global: str         # ISO timestamp o ""
```

**Logica de `health_global`:**

| Estados de capas | health_global |
|---|---|
| Sin datos (tabla vacia) | `"sin datos"` |
| Las 3 capas en `ok` | `"Healthy"` |
| Alguna `error` | `"Failed"` |
| Alguna `running` (sin errores) | `"Degraded"` |
| Faltan capas (no han corrido, <3 registros) | `"Degraded"` |

**Fuente de datos:** tabla PostgreSQL `observability.pipeline_runs` (ver seccion 5).

**Query:** selecciona la ultima corrida (por `started_at`) de cada capa (`bronze`, `silver`, `gold`).

---

### 2.2 `GET /observability/pipeline/logs/{layer}`

**Archivo:** `backend/src/lakehouse/api/routers/observability.py`

**Path parameter:** `layer: str` — `"bronze"`, `"silver"`, o `"gold"`.

**Query parameter:** `lines: int = 50` (ge=1, le=500).

**Response model:** `PipelineLogs` (existente, reutilizado).

```python
class PipelineLogs(BaseModel):
    lines: list[str]
    total_lines: int
```

**Logica:** lee `data/lakehouse/logs/pipeline.log` y filtra lineas cuyo prefijo coincida con `[{layer}]`.
Ejemplo: `[bronze] Iniciando ingesta...`.

Si el archivo no existe, devuelve `lines: [], total_lines: 0`.

---

### 2.3 `GET /config`

**Archivo:** `backend/src/lakehouse/api/routers/config.py` (nuevo archivo).

**Response model:** `ConfigResponse`

```python
class ModelosConfig(BaseModel):
    llm: str
    embedding: str

class ConfigResponse(BaseModel):
    ambiente: str              # APP_ENV, default "desconocido"
    docker: bool               # detecta /.dockerenv
    version: str               # "0.1.0"
    modelos: ModelosConfig
```

**Fuente de datos:**
- `ambiente`: `os.getenv("APP_ENV", "desconocido")`
- `docker`: `os.path.exists("/.dockerenv")`
- `version`: hardcodeado `"0.1.0"` (mismo que `/health`)
- `modelos`: desde `Settings().llamacpp_model` y `Settings().ollama_embed_model`

**Router:** incluido sin prefijo en `main.py`.

---

### 2.4 `GET /embeddings/3d`

**Archivo:** `backend/src/lakehouse/api/routers/embeddings.py` (nuevo archivo).

**Response model:** `Embedding3DResponse`

```python
class Embedding3DPoint(BaseModel):
    chunk_key: str
    x: float
    y: float
    z: float
    conference_date: str

class Embedding3DResponse(BaseModel):
    points: list[Embedding3DPoint]
```

**Logica:** `SELECT chunk_key, embedding_3d, conference_date FROM gold.rag_corpus WHERE embedding_3d IS NOT NULL`.
Las coordenadas se pre-computan en `pipeline enrich` via UMAP (ver seccion 5.2).

**Casos borde:**
- Sin puntos (columna toda NULL, corpus vacio): `points: []`.
- UMAP fallo durante el enrich: `points: []`, no es error del endpoint.

**Router:** incluido sin prefijo en `main.py`.

---

## 3. Endpoint modificado: `POST /chat/`

**Archivo:** `backend/src/lakehouse/api/routers/chat.py`

### Cambios en `ChatResponse`

Campo nuevo: `model_used: str`

```python
class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    token_usage: dict[str, int]    # ahora incluye key "total"
    model_used: str                # ej: "gemma4"
    latency_ms: float              # tiempo de pared del endpoint
```

### Cambios en `SourceChunk`

Campos nuevos: `qualitative_label`, `embedding_3d`

```python
class SourceChunk(BaseModel):
    conference_date: str
    conference_id: str
    participant: str
    chunk_text: str
    similarity: float
    conference_url: str
    pregunta_activa: str
    qualitative_label: str         # "Alta" | "Media" | "Baja"
    embedding_3d: list[float] | None  # [x, y, z] o None si no hay 3D
```

### Logica nueva en el router

1. **Latencia:** `time.perf_counter()` al inicio y final del endpoint. Se incluye en `latency_ms`.
2. **Modelo:** se lee de `settings.llamacpp_model` y se incluye en `model_used`.
3. **Total tokens:** `token_usage["total"] = token_usage["prompt"] + token_usage["completion"]`.
4. **Qualitative label:** despues de obtener los resultados del search, se calculan percentiles entre los `top_k`:
   - Top 25% (mayor similitud) → `"Alta"`
   - Mid 50% → `"Media"`
   - Bottom 25% → `"Baja"`
   - Si `top_k < 4`: todos `"Alta"`.
5. **embedding_3d:** se incluye en el `SELECT` de `search_gold_corpus_from_vector` y `search_with_date_filter`. Se agrega al `SourceChunk` como `list[float]` de 3 elementos, o `None` si la columna es NULL.

---

## 4. Router registrations en `main.py`

```python
app.include_router(config.router)        # nuevo: GET /config
app.include_router(embeddings.router)    # nuevo: GET /embeddings/3d
```

Los routers `observability`, `chat`, `search`, `health` ya estan registrados.

---

## 5. Cambios en base de datos

### 5.1 Nueva tabla: `observability.pipeline_runs`

**Motor:** PostgreSQL (mismo que pgvector, via `psycopg2`).

```sql
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
```

**Creacion del schema:** `CREATE SCHEMA IF NOT EXISTS observability;` en el modulo de inicializacion de DB.

**`run_id` determinista:** `sha256(f"{capa}:{started_at.isoformat()}")`. Garantiza idempotencia en reejecuciones.

### 5.2 Nueva columna: `gold.rag_corpus.embedding_3d`

```sql
ALTER TABLE gold.rag_corpus
    ADD COLUMN IF NOT EXISTS embedding_3d DOUBLE PRECISION[3];
```

Se pobla al final del `pipeline enrich` via UMAP (ver seccion 6.2).

### 5.3 Modulo de inicializacion

Nuevo archivo `backend/src/lakehouse/db/observability_conn.py`:

```python
def ensure_observability_tables(conn) -> None:
    """Crea schema observability y tabla pipeline_runs si no existen."""
```

Se llama desde `pipeline enrich` (o desde un punto comun de inicializacion del CLI).

---

## 6. Cambios en el CLI del pipeline

### 6.1 Escritura de `pipeline_runs`

Cada comando (`pipeline ingest`, `pipeline parse`, `pipeline enrich`) debe:

1. Generar `run_id = sha256(f"{capa}:{datetime.now(UTC).isoformat()}")`
2. `INSERT INTO observability.pipeline_runs (run_id, capa, status, started_at) VALUES (...)`
3. Ejecutar la logica existente del pipeline
4. `UPDATE observability.pipeline_runs SET status='ok', finished_at=NOW(), records_in=..., records_out=..., dlq_count=... WHERE run_id=...`

En caso de error:
5. `UPDATE observability.pipeline_runs SET status='error', finished_at=NOW(), error_message=... WHERE run_id=...`

### 6.2 Computo UMAP 3D

Dentro de `pipeline enrich`, despues del upsert de embeddings en `gold.rag_corpus`:

1. Detectar si hubo chunks nuevos (comparar `embedded > 0` del resultado del enrich).
2. Si no hubo nuevos, saltar UMAP.
3. Si hubo nuevos:
   - `SELECT chunk_key, embedding FROM gold.rag_corpus` (todos los registros).
   - Si `len(rows) < 4`: loggear warning, saltar UMAP (no se puede reducir con <4 puntos).
   - `umap.UMAP(n_components=3, random_state=42, n_neighbors=min(15, len(rows)-1)).fit_transform(vectors)`.
   - `UPDATE gold.rag_corpus SET embedding_3d = ARRAY[x, y, z] WHERE chunk_key = ...` (batch o row-by-row).
4. Dependencia nueva: `umap-learn>=0.5.0` en `pyproject.toml`.

**Nota:** UMAP se ejecuta en el proceso principal (no en workers) porque necesita todos los vectores juntos.

---

## 7. Cambios en logging del pipeline

Modificar los loggers de cada capa para prefijar lineas con `[bronze]`, `[silver]`, `[gold]`:

```python
logger = get_logger(__name__, layer="bronze")  # el layer se usa como prefijo
```

Esto permite que `GET /observability/pipeline/logs/{layer}` filtre por prefijo.

---

## 8. Archivos involucrados

| Archivo | Accion |
|---|---|
| `backend/src/lakehouse/schemas/observability.py` | Agregar `LayerRun`, `PipelineLayersResponse` |
| `backend/src/lakehouse/schemas/chat.py` | Agregar campos a `ChatResponse`, `SourceChunk` |
| `backend/src/lakehouse/schemas/config.py` | Nuevo: `ConfigResponse`, `ModelosConfig` |
| `backend/src/lakehouse/schemas/embeddings.py` | Nuevo: `Embedding3DPoint`, `Embedding3DResponse` |
| `backend/src/lakehouse/api/routers/observability.py` | Agregar `GET /pipeline/layers`, `GET /pipeline/logs/{layer}` |
| `backend/src/lakehouse/api/routers/config.py` | Nuevo: `GET /config` |
| `backend/src/lakehouse/api/routers/embeddings.py` | Nuevo: `GET /embeddings/3d` |
| `backend/src/lakehouse/api/routers/chat.py` | Modificar: nuevos campos en response, qualitative label, latency |
| `backend/src/lakehouse/main.py` | Registrar nuevos routers |
| `backend/src/lakehouse/db/observability_conn.py` | Nuevo: `ensure_observability_tables()` |
| `backend/src/lakehouse/pipeline/enrichment.py` | Agregar computo UMAP al final |
| `backend/src/lakehouse/cli.py` | Agregar escritura de `pipeline_runs` en ingest/parse/enrich |
| `backend/src/lakehouse/services/rag_search.py` | Agregar `embedding_3d` al SELECT de busqueda |
| `backend/src/lakehouse/log_config.py` | Agregar prefijo de capa al formatter |
| `backend/pyproject.toml` | Agregar `umap-learn>=0.5.0` |
| `backend/tests/test_schemas/` | Tests para nuevos schemas |
| `backend/tests/test_api/` | Tests para nuevos endpoints |
| `backend/tests/test_services/` | Tests para qualitative label, UMAP |
| `frontend/src/api/observability.ts` | Agregar tipos para `PipelineLayersResponse`, `getPipelineLayers()` |
| `frontend/src/api/config.ts` | Nuevo: `ConfigResponse`, `getConfig()` |
| `frontend/src/api/embeddings.ts` | Nuevo: `Embedding3DResponse`, `getEmbeddings3D()` |
| `frontend/src/api/chat.ts` | Actualizar `SourceChunk`, `ChatResponse` con nuevos campos |

---

## 9. Casos borde y errores

| Escenario | Comportamiento |
|---|---|
| Tabla `pipeline_runs` vacia (nunca se ejecuto pipeline) | `/pipeline/layers` devuelve `layers: []`, `health_global: "sin datos"` |
| UMAP falla (pocos chunks, < 4) | `/embeddings/3d` devuelve `points: []`, log warning, no bloquea enrich |
| `embedding_3d` es NULL (chunks pre-UMAP) | `/embeddings/3d` y `/chat/` los omiten o devuelven `None` |
| Archivo de log no existe o capa sin logs | `lines: [], total_lines: 0` |
| `APP_ENV` no seteado | `ambiente: "desconocido"` |
| Docker no detectado (sin `/.dockerenv`) | `docker: false` |
| Corpus vacio en `/chat/` (sin chunks en Gold) | `RuntimeError("Search unavailable")` → 503 |
| Reejecucion del pipeline en el mismo segundo (altamente improbable) | `run_id` determinista colisiona. Usar `ON CONFLICT DO NOTHING`. La segunda ejecucion no deja registro, lo cual es aceptable como proteccion anti-duplicados. |
| Percentil en qualitative label con `top_k=1` | Unico resultado → `"Alta"` |
| `top_k < 4` en qualitative label | Todos `"Alta"` (sin sentido dividir en percentiles) |
| Workers en paralelo intentan escribir `pipeline_runs` | No aplica: cada capa tiene su propio `run_id` y se ejecuta secuencialmente |
| Cierre abrupto del CLI (SIGTERM, crash) | El registro queda con `status='running'` y sin `finished_at`. El frontend muestra "En curso" correctamente. La siguiente corrida lo sobrescribe con su propio registro. |

---

## 10. Testing

### Schemas (unitarios)
- `TestPipelineLayersResponse`: validar defaults, serializacion con 0/1/3 capas
- `TestConfigResponse`: validar campos requeridos
- `TestEmbedding3DResponse`: validar con y sin puntos
- `TestChatResponse`: validar nuevos campos (`model_used`, `latency_ms`, `total_tokens`)
- `TestSourceChunk`: validar `qualitative_label`, `embedding_3d`

### Endpoints (integracion)
- `TestGetPipelineLayers`: tabla vacia, tabla con datos, capa en running, capa en error
- `TestGetPipelineLogsByLayer`: log con prefijos, log sin prefijos, archivo inexistente
- `TestGetConfig`: con y sin `APP_ENV`, con y sin `/.dockerenv`
- `TestGetEmbeddings3D`: corpus con datos 3D, corpus sin datos 3D, corpus vacio
- `TestChatWithNewFields`: verificar `model_used`, `latency_ms`, `qualitative_label`, `embedding_3d`

### Servicios (unitarios)
- `TestQualitativeLabel`: top_k=1, top_k=3, top_k=5, top_k=10, scores identicos
- `TestUMAP`: con 5/10/100 vectores sinteticos, matriz vacia, <4 vectores

### CLI (integracion)
- `TestPipelineWritesRunRecord`: verificar INSERT y UPDATE en `pipeline_runs`
- `TestPipelineUMAPOnEnrich`: verificar que `embedding_3d` se pobla tras enrich

---

## 11. Dependencias

```toml
# pyproject.toml
dependencies = [
    ...
    "umap-learn>=0.5.0",
]
```

`umap-learn` requiere `numpy`, `scipy`, `numba`. `numpy` ya esta en el proyecto. Las otras son transitivas.

---

## 12. No incluido en este spec

- Reranking (cross-encoder, Cohere, etc.) — queda como dato futuro.
- Cobertura de citas como metrica automatica — queda como dato futuro.
- Titulo de conferencia como campo en `SourceChunk` — no existe en el modelo de datos actual.
- Endpoint `POST /embeddings/3d/cited` — descartado; los datos 3D viajan en `SourceChunk` del `/chat/`.
- Modificacion al endpoint `/health` — se mantiene igual; la config se expone en `/config`.
- WebSockets para streaming del chat — fuera de alcance.
