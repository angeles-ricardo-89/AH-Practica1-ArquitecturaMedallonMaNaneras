# Spec — Clusterizacion y Autoetiquetado Semantico en Gold

## 1. Objetivo

Agregar a la capa Gold un proceso reproducible que agrupe los chunks segun su contenido semantico
mediante UMAP + HDBSCAN, asigne identificadores de cluster con fuerza de pertenencia, y genere
automaticamente etiquetas breves para cada cluster usando el LLM local (llamacpp/gemma4).

El proceso se ejecuta automaticamente al final de `enrich` cuando detecta embeddings sin clusterizar.

## 2. Estado actual

- Tabla Gold: `gold.rag_corpus` con columnas `chunk_key` (PK VARCHAR), `embedding` (vector(768)),
  `embedding_3d` (DOUBLE PRECISION[3]), `chunk_text`, `payload`, `conference_date`, `participant`, etc.
- UMAP 3D existe en `pipeline/enrichment.py:_compute_umap_3d()` — se ejecuta al final de enrich.
- LLM local: llamacpp en puerto 9200 (gemma4) para generacion, Ollama en 11434 (embeddinggemma) para embeddings.
- CLI: Typer con `python -m lakehouse pipeline enrich` como unico comando Gold.
- Observabilidad: `observability.pipeline_runs` registra corridas por capa.
- No existe ninguna tabla ni codigo de clusterizacion.

## 3. Decisiones de diseno

| Decision | Eleccion |
|---|---|
| Tabla de chunks | Extender `gold.rag_corpus` existente (no crear tabla nueva) |
| CLI | Extender comando `enrich` existente; clusterizacion automatica al detectar embeddings sin clusterizar |
| LLM para etiquetado | llamacpp/gemma4 (reutiliza backend de generacion existente) |
| Migracion de schema | Programatica al iniciar (`ensure_clustering_schema()`) |
| Modulo de codigo | Nuevo archivo `pipeline/clustering.py`, llamado desde `EnrichService.run()` |
| Prompt template | `backend/src/lakehouse/prompts/cluster_label_v1.txt` |
| Observabilidad | Mismo `pipeline_run` del enrich (capa=gold), sin entry separada |
| Dataset HDBSCAN | Completo cada vez (todos los chunks con embedding valido) |
| Ejecucion | Sincronica, bloquea `enrich` hasta terminar |
| Configuracion | Extender `Settings` existente en `config.py` |
| Frontend | Coloreado por cluster_id en scatter 3D + tooltip con label + seleccion basica de cluster |
| Idempotencia | Fingerprint de corpus + hash de parametros; skip si ya existe run equivalente |

## 4. Flujo del pipeline

```
EnrichService.run()
  → enriquecer embeddings (existente, sin cambios)
  → _compute_umap_3d() (existente, sin cambios)
  → [NUEVO] detectar si hay embeddings sin clusterizar
  → [NUEVO] si hay pendientes → run_clustering_pipeline()
```

### 4.1 Pipeline de clusterizacion (pipeline/clustering.py)

```
1. ensure_clustering_schema()
   → Agrega cluster_id, cluster_pertenencia, clustering_run_id a rag_corpus
   → Crea gold.clustering_runs
   → Crea gold.cluster_labels

2. compute_corpus_fingerprint() + compute_parameters_hash()
   → SHA256 de (chunk_keys ordenados + embedding hashes + model version)
   → SHA256 de (umap_params + hdbscan_params + sampling_params + prompt_version)

3. Verificar idempotencia
   → SELECT COUNT(*) FROM gold.clustering_runs
     WHERE status='completed'
       AND corpus_fingerprint = :fp
       AND parameters_hash = :ph
   → Si > 0, retornar existente (log: "corrida equivalente ya existe")
   → Si --force, continuar de todos modos

4. Crear run en gold.clustering_runs (status='running')

5. Cargar embeddings desde pgvector
   → SELECT chunk_key, chunk_text, embedding FROM gold.rag_corpus
   → _parse_pgvector_to_list() (reutiliza funcion existente)

6. validate_embeddings()
   → Rechaza: NULL, dimension != esperada, NaN, Inf, vector vacio, norma=0
   → rejected_count = len(rechazados)
   → Si valid_count < 4: abortar (UMAP necesita al menos 4 puntos)

7. normalize(norm='l2') sobre matriz numpy

8. UMAP clustering (15 dimensiones, metric='cosine', min_dist=0.0)
   → Instancia independiente de la UMAP 3D existente

9. HDBSCAN sobre vectores UMAP (metric='euclidean')
   → cluster_ids = labels_
   → cluster_pertenencia = probabilities_
   → cluster_id=-1 → ruido (pertenencia=0.0)

10. persist_cluster_assignments()
    → UPDATE masivo con VALUES + FROM (transaccional, no UPDATE individual)
    → SET cluster_id, cluster_pertenencia, clustering_run_id

11. Actualizar run con metricas parciales
    → cluster_count (sin -1), noise_count, valid_count, rejected_count

12. label_clusters() — solo si no se saltea
    → Por cada cluster_id >= 0:
      a. select_representative_chunks(k=K_HDBSCAN_SAMPLING, orden: pertenencia DESC, chunk_key ASC)
      b. Truncar cada chunk a CLUSTER_LABEL_MAX_CHARS_PER_CHUNK chars
      c. Cargar prompt desde cluster_label_v1.txt y formatear con los textos
      d. POST a llamacpp (temperature=0, max_tokens=20)
      e. validate_label() → limpiar respuesta (strips, quita prefijos, normaliza espacios)
      f. Si invalido: reintentar hasta CLUSTER_LABEL_MAX_RETRIES
      g. Persistir en gold.cluster_labels (label_status='completed' o 'failed')
    → Fallo de un cluster NO detiene el etiquetado de otros

13. Marcar run como 'completed' (o 'partial' si alguna etiqueta fallo)
```

## 5. Esquema de base de datos

### 5.1 Columnas nuevas en gold.rag_corpus

```sql
ALTER TABLE gold.rag_corpus ADD COLUMN IF NOT EXISTS cluster_id INTEGER NULL;
ALTER TABLE gold.rag_corpus ADD COLUMN IF NOT EXISTS cluster_pertenencia REAL NULL
    CHECK (cluster_pertenencia IS NULL OR (cluster_pertenencia >= 0.0 AND cluster_pertenencia <= 1.0));
ALTER TABLE gold.rag_corpus ADD COLUMN IF NOT EXISTS clustering_run_id UUID NULL;
```

### 5.2 Tabla gold.clustering_runs

```sql
CREATE TABLE IF NOT EXISTS gold.clustering_runs (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status              VARCHAR NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','failed','partial')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    input_count         INTEGER NOT NULL DEFAULT 0,
    valid_count         INTEGER NOT NULL DEFAULT 0,
    rejected_count      INTEGER NOT NULL DEFAULT 0,
    cluster_count       INTEGER NOT NULL DEFAULT 0,
    noise_count         INTEGER NOT NULL DEFAULT 0,
    labeled_cluster_count INTEGER NOT NULL DEFAULT 0,
    failed_label_count  INTEGER NOT NULL DEFAULT 0,
    corpus_fingerprint  VARCHAR NOT NULL,
    parameters_hash     VARCHAR NOT NULL,
    embedding_model     VARCHAR NOT NULL,
    umap_parameters     JSONB NOT NULL DEFAULT '{}',
    hdbscan_parameters  JSONB NOT NULL DEFAULT '{}',
    labeling_parameters JSONB NOT NULL DEFAULT '{}',
    error_message       TEXT
);
```

### 5.3 Tabla gold.cluster_labels

```sql
CREATE TABLE IF NOT EXISTS gold.cluster_labels (
    clustering_run_id   UUID NOT NULL REFERENCES gold.clustering_runs(run_id),
    cluster_id          INTEGER NOT NULL CHECK (cluster_id >= 0),
    cluster_label       VARCHAR,
    label_status        VARCHAR NOT NULL DEFAULT 'pending'
                        CHECK (label_status IN ('pending','completed','failed')),
    sample_size         INTEGER NOT NULL DEFAULT 0,
    sample_chunk_keys   TEXT[] NOT NULL DEFAULT '{}',
    model_name          VARCHAR,
    prompt_version      VARCHAR,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clustering_run_id, cluster_id)
);
```

## 6. Configuracion

Se extiende `Settings` en `backend/src/lakehouse/config.py` con los siguientes campos:

```python
# UMAP para clusterizacion
umap_clustering_n_components: int = 15
umap_clustering_n_neighbors: int = 30
umap_clustering_min_dist: float = 0.0
umap_clustering_metric: str = "cosine"
umap_clustering_random_state: int = 42

# HDBSCAN
hdbscan_min_cluster_size: int = 15
hdbscan_min_samples: int = 5
hdbscan_metric: str = "euclidean"
hdbscan_algorithm: str = "auto"
hdbscan_cluster_selection_method: str = "eom"
hdbscan_n_jobs: int = -1

# Muestreo
k_hdbscan_sampling: int = 5

# Autoetiquetado
cluster_label_max_chars_per_chunk: int = 1500
cluster_label_max_retries: int = 2
cluster_label_prompt_version: str = "v1"
```

Todos con su prefijo en `.env` (ej: `UMAP_CLUSTERING_N_COMPONENTS`).

## 7. API — Nuevo endpoint

### `GET /api/clusters/latest`

Devuelve los datos de la corrida de clusterizacion mas reciente con status `completed` o `partial`.

```json
{
  "run_id": "uuid",
  "status": "completed",
  "cluster_count": 12,
  "noise_count": 3,
  "clusters": [
    {
      "cluster_id": 0,
      "label": "Salud publica",
      "chunk_count": 45,
      "avg_membership": 0.87,
      "sample_chunk_keys": ["key1", "key2", "key3", "key4", "key5"]
    }
  ],
  "points": [
    {
      "chunk_key": "key1",
      "cluster_id": 0,
      "pertenencia": 0.92,
      "x": 1.23, "y": -0.45, "z": 0.81
    }
  ]
}
```

Las coordenadas `x,y,z` se obtienen de la columna `embedding_3d` existente en `rag_corpus`.

### `GET /api/clusters/{run_id}`

Igual que `/latest` pero para una corrida especifica.

## 8. Frontend

### 8.1 Nuevo cliente API: `frontend/src/api/clusters.ts`

```typescript
export interface ClusterInfo {
  cluster_id: number;
  label: string | null;
  chunk_count: number;
  avg_membership: number;
  sample_chunk_keys: string[];
}

export interface ClusterPoint {
  chunk_key: string;
  cluster_id: number;
  pertenencia: number;
  x: number;
  y: number;
  z: number;
}

export interface ClusterData {
  run_id: string;
  status: string;
  cluster_count: number;
  noise_count: number;
  clusters: ClusterInfo[];
  points: ClusterPoint[];
}

export async function getClustersLatest(): Promise<ClusterData>;
export async function getClusters(runId: string): Promise<ClusterData>;
```

### 8.2 Cambios en componentes

**`Embeddings3D.vue`:**
- Recibe `clusterData: ClusterData | null` como prop
- Paleta categorica por `cluster_id` (d3.schemeCategory10 ciclado)
- `cluster_id = -1` → gris semitransparente (`rgba(128,128,128,0.3)`)
- Tooltip al hover: `cluster_id={id} label={label} pertenencia={p}`
- Se mantiene highlight rojo para chunks citados en chat (tiene prioridad sobre color de cluster)

**`DashboardPage.vue`:**
- Al montar: `getClustersLatest()` → pasa datos a `Embeddings3D`
- Si no hay datos de clusterizacion, comportamiento actual sin cambios

**`dashboardStore` (Pinia):**
- `clusterData: ClusterData | null`
- `fetchClusters()` — accion asincrona

## 9. Prompt de autoetiquetado

Archivo: `backend/src/lakehouse/prompts/cluster_label_v1.txt`

```
[INSTRUCCION DE SISTEMA / CONTEXTO]
Eres un sistema experto en analisis de datos y taxonomias. Tu unica tarea es asignar una categoria o etiqueta conceptual a un grupo de textos.

[REGLAS ESTRICTAS]
1. La etiqueta debe ser una frase o titulo muy corto, con un maximo de 4 palabras.
2. Debe describir el denominador comun o tema central de todos los ejemplos provistos.
3. Responde UNICAMENTE con la etiqueta del tema.
4. Prohibido incluir introducciones, explicaciones, saludos, notas aclaratorias o comillas en tu respuesta.

[EJEMPLOS DE TEXTO DEL GRUPO DE DATOS]
{textos_formateados}

[RESPUESTA]
```

Los placeholders `{textos_formateados}` se reemplazan con los chunks muestreados, uno por linea con formato `- {texto_truncado}`.

## 10. Dependencias nuevas

Se agregan al `pyproject.toml`:

```toml
"hdbscan>=0.8.33",
"scikit-learn>=1.4",
```

`hdbscan` es el paquete standalone que proporciona `probabilities_` (fuerza de pertenencia). `scikit-learn` se explicita como dependencia directa (actualmente es transitiva via `umap-learn`). Ambas son necesarias: `sklearn` para `normalize` y utilidades, `hdbscan` para `HDBSCAN` con `probabilities_`.

## 11. Modulos del codigo

### 10.1 `backend/src/lakehouse/pipeline/clustering.py` — nuevo

Funciones publicas:

| Funcion | Descripcion |
|---|---|
| `ensure_clustering_schema(conn)` | Migracion programatica (columnas + tablas) |
| `compute_corpus_fingerprint(chunk_keys, embeddings, model)` | SHA256 determinista |
| `compute_parameters_hash(settings)` | SHA256 de parametros |
| `validate_embeddings(embeddings, expected_dim)` | Filtra invalidos, retorna (validos, rechazados) |
| `run_clustering_pipeline(settings)` | Orquestador completo |
| `label_clusters(conn, run_id, cluster_ids, chunks, settings)` | Autoetiquetado con llamacpp |
| `validate_label(raw_label)` | Limpia y valida respuesta del LLM |
| `select_representative_chunks(chunks, cluster_id, k)` | Top-k por pertenencia |
| `persist_cluster_assignments(conn, run_id, assignments)` | UPDATE masivo |
| `_parse_pgvector_to_list(pg_str)` | Reutilizado de enrichment.py |

### 10.2 `backend/src/lakehouse/services/enrich_service.py` — modificado

En `EnrichService.run()`, despues de `_compute_umap_3d()`:

```python
# Clusterizacion automatica si hay embeddings pendientes
from lakehouse.pipeline.clustering import run_clustering_pipeline

try:
    run_clustering_pipeline(settings)
except Exception as e:
    logger.warning("clusterizacion_fallida", error=str(e))
```

La clusterizacion fallida no revierte el enrich ni el UMAP 3D. Solo se loguea.

### 10.3 `backend/src/lakehouse/config.py` — modificado

Se agregan los 17 campos de configuracion listados en la seccion 6.

### 10.4 `backend/src/lakehouse/api/routers/` — nuevo router

`backend/src/lakehouse/api/routers/clusters.py` con endpoints `GET /clusters/latest` y `GET /clusters/{run_id}`.

## 11. Pruebas

### 11.1 Unitarias (`backend/tests/test_pipeline/test_clustering.py`)

| Test | Que verifica |
|---|---|
| `test_validate_embeddings_rejects_null` | Embedding None → rechazado |
| `test_validate_embeddings_rejects_nan` | Valores NaN → rechazado |
| `test_validate_embeddings_rejects_inf` | Valores inf → rechazado |
| `test_validate_embeddings_rejects_wrong_dim` | Dimension != 768 → rechazado |
| `test_validate_embeddings_rejects_zero_norm` | Norma L2 = 0 → rechazado |
| `test_validate_embeddings_accepts_valid` | Vector valido → aceptado |
| `test_normalize_l2_preserves_shape` | Normalizacion no cambia dimensiones |
| `test_normalize_l2_unit_norm` | Vectores normalizados tienen norma ~1.0 |
| `test_corpus_fingerprint_deterministic` | Misma entrada → mismo hash |
| `test_corpus_fingerprint_changes_with_data` | Diferente entrada → diferente hash |
| `test_parameters_hash_deterministic` | Mismos params → mismo hash |
| `test_select_representative_chunks_top_k` | Top-5 por pertenencia |
| `test_select_representative_chunks_tiebreaker` | Empate → ordena por chunk_key ASC |
| `test_select_representative_chunks_small_cluster` | Cluster con menos de k chunks → todos |
| `test_validate_label_rejects_empty` | String vacio → invalido |
| `test_validate_label_rejects_multiline` | Multilinea → invalido |
| `test_validate_label_strips_prefixes` | "Etiqueta: X" → "X" |
| `test_validate_label_strips_quotes` | '"Salud"' → "Salud" |
| `test_validate_label_normalizes_spaces` | "  mucha   salud  publica  ." → "mucha salud publica" |
| `test_validate_label_truncates_long` | Mas de 4 palabras → invalido |
| `test_noise_gets_cluster_minus_one` | labels_=-1 → cluster_id=-1, pertenencia=0.0 |

### 11.2 Integracion (`backend/tests/test_pipeline/test_clustering_integration.py`)

| Test | Que verifica |
|---|---|
| `test_full_pipeline_with_fixture_data` | UMAP+HDBSCAN+etiquetado completo |
| `test_idempotency_same_input` | Segunda ejecucion con mismos datos → skip |
| `test_force_rerun` | --force crea nueva corrida aunque exista equivalente |
| `test_noise_excluded_from_labeling` | cluster_id=-1 no genera entrada en cluster_labels |
| `test_partial_run_on_label_failure` | Fallo de LLM → run queda como 'partial', no 'failed' |
| `test_cluster_assignments_persisted` | UPDATE masivo guarda cluster_id correctamente |
| `test_umap_output_dimension` | UMAP clustering produce n_components columnas |
| `test_embedding_3d_not_used_as_input` | HDBSCAN recibe UMAP clustering, no embedding_3d |
| `test_schema_migration_idempotent` | ensure_clustering_schema() es seguro ejecutar multiples veces |

### 11.3 API (`backend/tests/test_api/test_clusters_router.py`)

| Test | Que verifica |
|---|---|
| `test_get_clusters_latest_returns_data` | /clusters/latest devuelve datos |
| `test_get_clusters_latest_empty` | Sin corridas → 404 o respuesta vacia |
| `test_get_clusters_by_run_id` | /clusters/{run_id} devuelve corrida especifica |

## 12. Casos borde

| Caso | Comportamiento |
|---|---|
| Menos de 4 embeddings validos | Abortar clusterizacion (UMAP requiere >= 4 puntos) |
| Todos los embeddings invalidos | Abortar, run.status='failed' |
| HDBSCAN no encuentra clusters (todos ruido) | run.status='completed', todos cluster_id=-1, sin etiquetas |
| llamacpp no disponible | Todos los labels fallan, run.status='partial' |
| Prompt file no encontrado | Abortar etiquetado, run.status='partial' |
| Enrich ejecutado sin nuevos embeddings | No se dispara clusterizacion |
| Dos enriches concurrentes | No hay lock (MVP). La segunda corrida encontrara la primera completada y hara skip por idempotencia |
| Chunk sin embedding (NULL) | Excluido en la carga inicial, contado como rejected |

## 13. Fuera de alcance

- Identidad estable de temas entre corridas
- Alineacion automatica de clusters historicos
- Clasificacion multietiqueta o taxonomias jerarquicas
- Validacion humana obligatoria
- Fusion automatica de etiquetas similares
- Entrenamiento o ajuste fino de modelos
- Clusterizacion incremental
- Indices vectoriales sobre coordenadas UMAP
- Lock de concurrencia para clusterizacion

## 14. Resultado esperado

Al finalizar una corrida valida:
- Cada chunk procesable tiene `cluster_id`, `cluster_pertenencia` y `clustering_run_id`
- Los puntos ruido estan identificados (cluster_id=-1)
- Cada cluster valido tiene una etiqueta breve o un fallo trazable
- El dashboard colorea los puntos 3D por cluster y muestra etiquetas en tooltip
- La busqueda semantica sigue funcionando sobre `embedding` original
- La corrida es reproducible, auditable e idempotente
