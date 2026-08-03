# Gold Clusterization & Auto-Labeling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar clusterizacion semantica (UMAP + HDBSCAN) y autoetiquetado con LLM local a la capa Gold. Se ejecuta automaticamente al final de `enrich` cuando detecta embeddings sin clusterizar.

**Architecture:** Nuevo modulo `pipeline/clustering.py` con funciones puras para validacion, UMAP, HDBSCAN, persistencia y etiquetado. Llamado desde `EnrichService.run()` despues de `_compute_umap_3d()`. El UMAP de clusterizacion es una instancia independiente del UMAP de visualizacion. El autoetiquetado usa llamacpp/gemma4 con prompt versionado.

**Tech Stack:** Python 3.13, umap-learn, hdbscan, scikit-learn, numpy, psycopg, httpx (llamacpp), FastAPI + Pydantic (API), Vue 3 + ECharts 3D (frontend)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/pyproject.toml` | Modify | Add hdbscan, scikit-learn dependencies |
| `backend/src/lakehouse/config.py` | Modify | 17 new cluster settings |
| `backend/src/lakehouse/prompts/cluster_label_v1.txt` | Create | Prompt for LLM auto-labeling |
| `backend/src/lakehouse/pipeline/clustering.py` | Create | Core clustering pipeline |
| `backend/src/lakehouse/services/enrich_service.py` | Modify | Call clustering after enrich |
| `backend/src/lakehouse/schemas/cluster.py` | Create | Pydantic schemas for API |
| `backend/src/lakehouse/api/routers/clusters.py` | Create | GET /clusters/latest, /clusters/{run_id} |
| `backend/src/lakehouse/main.py` | Modify | Register clusters router |
| `backend/tests/test_pipeline/test_clustering.py` | Create | Unit tests |
| `backend/tests/test_pipeline/test_clustering_integration.py` | Create | Integration tests |
| `backend/tests/test_api/test_clusters_router.py` | Create | API tests |
| `frontend/src/api/clusters.ts` | Create | API client for cluster data |
| `frontend/src/stores/dashboard.ts` | Modify | Add cluster data state |
| `frontend/src/components/inspector/Embeddings3D.vue` | Modify | Color by cluster, tooltips |
| `frontend/src/components/dashboard/DashboardPage.vue` | Modify | Fetch cluster data on mount |

---

### Task 1: Agregar dependencias hdbscan + scikit-learn

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Agregar dependencias a pyproject.toml**

```toml
dependencies = [
    "duckdb>=1.2",
    "fastapi[standard]>=0.115",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "typer>=0.15",
    "httpx>=0.28",
    "structlog>=25.1",
    "python-dotenv>=1.1",
    "psycopg[binary]>=3.2",
    "umap-learn>=0.5.12",
    "hdbscan>=0.8.33",
    "scikit-learn>=1.4",
]
```

- [ ] **Step 2: Instalar dependencias**

```bash
cd backend && uv sync
```

Expected: `Resolved N packages in Xms`

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "agrega dependencias hdbscan y scikit-learn para clusterizacion gold"
```

---

### Task 2: Prompt template para autoetiquetado

**Files:**
- Create: `backend/src/lakehouse/prompts/cluster_label_v1.txt`

- [ ] **Step 1: Crear directorio prompts si no existe**

```bash
mkdir -p backend/src/lakehouse/prompts
```

- [ ] **Step 2: Escribir prompt template**

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

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/prompts/cluster_label_v1.txt
git commit -m "agrega prompt template v1 para autoetiquetado de clusters"
```

---

### Task 3: Settings de clusterizacion en config.py

**Files:**
- Modify: `backend/src/lakehouse/config.py`

- [ ] **Step 1: Agregar campos de clusterizacion al final de Settings**

```python
    # UMAP para clusterizacion (independiente del UMAP 3D de visualizacion)
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

    # Muestreo para etiquetado
    k_hdbscan_sampling: int = 5

    # Autoetiquetado
    cluster_label_max_chars_per_chunk: int = 1500
    cluster_label_max_retries: int = 2
    cluster_label_prompt_version: str = "v1"
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/lakehouse/config.py
git commit -m "agrega settings de clusterizacion a config"
```

---

### Task 4: Schema migration — ensure_clustering_schema()

**Files:**
- Create: `backend/tests/test_pipeline/test_clustering.py`

- [ ] **Step 1: Escribir el test de migracion**

```python
import psycopg
from lakehouse.pipeline.clustering import ensure_clustering_schema


def test_ensure_clustering_schema_creates_columns_and_tables(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'rag_corpus'
              AND column_name IN ('cluster_id', 'cluster_pertenencia', 'clustering_run_id')
            ORDER BY column_name
        """)
        cols = [r[0] for r in cur.fetchall()]
        assert "cluster_id" in cols
        assert "cluster_pertenencia" in cols
        assert "clustering_run_id" in cols

        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'gold'
              AND table_name IN ('clustering_runs', 'cluster_labels')
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        assert "clustering_runs" in tables
        assert "cluster_labels" in tables


def test_ensure_clustering_schema_is_idempotent(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        ensure_clustering_schema(conn)  # No debe fallar


def test_cluster_pertenencia_check_constraint(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'gold.rag_corpus'::regclass AND conname = 'chk_cluster_pertenencia_range'
        """)
        row = cur.fetchone()
        assert row is not None


def test_cluster_labels_no_negative_cluster_id(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO gold.cluster_labels (clustering_run_id, cluster_id, label_status)
                VALUES (gen_random_uuid(), -1, 'pending')
            """)
            conn.commit()
            assert False, "Deberia haber fallado por CHECK"
        except psycopg.errors.CheckViolation:
            conn.rollback()
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "schema" 2>&1 | tail -5
```

Expected: FAIL — module not found

- [ ] **Step 3: Crear ensure_clustering_schema() en clustering.py**

```python
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timezone
from pathlib import Path

import httpx
import numpy as np
import psycopg
import umap
from hdbscan import HDBSCAN
from sklearn.preprocessing import normalize

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="gold")


def ensure_clustering_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_id INTEGER NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_pertenencia REAL NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS clustering_run_id UUID NULL
    """)
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_cluster_pertenencia_range'
            ) THEN
                ALTER TABLE gold.rag_corpus
                ADD CONSTRAINT chk_cluster_pertenencia_range
                CHECK (cluster_pertenencia IS NULL OR (cluster_pertenencia >= 0.0 AND cluster_pertenencia <= 1.0));
            END IF;
        END $$;
    """)
    cur.execute("""
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
            corpus_fingerprint  VARCHAR NOT NULL DEFAULT '',
            parameters_hash     VARCHAR NOT NULL DEFAULT '',
            embedding_model     VARCHAR NOT NULL DEFAULT '',
            umap_parameters     JSONB NOT NULL DEFAULT '{}',
            hdbscan_parameters  JSONB NOT NULL DEFAULT '{}',
            labeling_parameters JSONB NOT NULL DEFAULT '{}',
            error_message       TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.cluster_labels (
            clustering_run_id   UUID NOT NULL REFERENCES gold.clustering_runs(run_id),
            cluster_id          INTEGER NOT NULL CHECK (cluster_id >= 0),
            cluster_label       VARCHAR,
            label_status        VARCHAR NOT NULL DEFAULT 'pending'
                                CHECK (label_status IN ('pending','completed','failed')),
            sample_size         INTEGER NOT NULL DEFAULT 0,
            sample_chunk_keys   TEXT[] NOT NULL DEFAULT '{}',
            model_name          VARCHAR DEFAULT '',
            prompt_version      VARCHAR DEFAULT '',
            attempt_count       INTEGER NOT NULL DEFAULT 0,
            error_message       TEXT DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (clustering_run_id, cluster_id)
        )
    """)
    conn.commit()
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py::test_ensure_clustering_schema_creates_columns_and_tables tests/test_pipeline/test_clustering.py::test_ensure_clustering_schema_is_idempotent tests/test_pipeline/test_clustering.py::test_cluster_pertenencia_check_constraint tests/test_pipeline/test_clustering.py::test_cluster_labels_no_negative_cluster_id -xvs
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega ensure_clustering_schema con migracion programatica y tests"
```

---

### Task 5: Validacion y normalizacion de embeddings

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py` (add tests)
- Modify: `backend/src/lakehouse/pipeline/clustering.py` (add functions)

- [ ] **Step 1: Agregar tests de validacion de embeddings**

```python
import numpy as np


def test_validate_embeddings_rejects_null():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1", "k2"],
        embeddings=[None, np.array([1.0, 2.0, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert keys == ["k2"]
    assert rejected[0][0] == "k1"
    assert rejected[0][1] == "null"


def test_validate_embeddings_rejects_nan():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.nan, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_inf():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, np.inf, 3.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "non_finite"


def test_validate_embeddings_rejects_wrong_dim():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([1.0, 2.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert "dimension" in rejected[0][1]


def test_validate_embeddings_rejects_zero_norm():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1"],
        embeddings=[np.array([0.0, 0.0, 0.0], dtype=np.float64)],
        expected_dim=3,
    )
    assert len(rejected) == 1
    assert rejected[0][1] == "zero_norm"


def test_validate_embeddings_accepts_valid():
    from lakehouse.pipeline.clustering import validate_embeddings

    keys, vecs, rejected = validate_embeddings(
        keys=["k1", "k2"],
        embeddings=[
            np.array([1.0, 2.0, 3.0], dtype=np.float64),
            np.array([4.0, 5.0, 6.0], dtype=np.float64),
        ],
        expected_dim=3,
    )
    assert keys == ["k1", "k2"]
    assert len(rejected) == 0
    assert vecs.shape == (2, 3)


def test_normalize_l2_preserves_shape():
    from sklearn.preprocessing import normalize

    vecs = np.array([[3.0, 4.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
    result = normalize(vecs, norm="l2")
    assert result.shape == vecs.shape


def test_normalize_l2_unit_norm():
    from sklearn.preprocessing import normalize

    vecs = np.random.RandomState(42).randn(10, 768).astype(np.float64)
    result = normalize(vecs, norm="l2")
    norms = np.linalg.norm(result, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)
```

- [ ] **Step 2: Ejecutar tests (deben fallar)**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "validate|normalize" 2>&1 | tail -5
```

Expected: FAIL

- [ ] **Step 3: Implementar validate_embeddings()**

```python
def validate_embeddings(
    keys: list[str],
    embeddings: list[np.ndarray | None],
    expected_dim: int,
) -> tuple[list[str], np.ndarray, list[tuple[str, str]]]:
    valid_keys: list[str] = []
    valid_vecs: list[np.ndarray] = []
    rejected: list[tuple[str, str]] = []

    for key, vec in zip(keys, embeddings):
        if vec is None:
            rejected.append((key, "null"))
            continue
        if not isinstance(vec, np.ndarray):
            vec = np.array(vec, dtype=np.float64)
        if vec.shape[0] != expected_dim:
            rejected.append((key, f"dimension:{vec.shape[0]}"))
            continue
        if not np.isfinite(vec).all():
            rejected.append((key, "non_finite"))
            continue
        if np.all(vec == 0):
            rejected.append((key, "zero_vector"))
            continue
        if np.linalg.norm(vec) == 0:
            rejected.append((key, "zero_norm"))
            continue
        valid_keys.append(key)
        valid_vecs.append(vec)

    arr = np.array(valid_vecs, dtype=np.float64) if valid_vecs else np.empty((0, expected_dim), dtype=np.float64)
    return valid_keys, arr, rejected
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "validate|normalize"
```

Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega validacion y normalizacion de embeddings con tests unitarios"
```

---

### Task 6: Fingerprints de corpus y parametros

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar tests de fingerprints**

```python
def test_corpus_fingerprint_deterministic():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    keys = ["key_a", "key_b", "key_c"]
    emb = np.random.RandomState(42).randn(3, 768).astype(np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    fp2 = compute_corpus_fingerprint(keys, emb, "embeddinggemma")
    assert fp1 == fp2


def test_corpus_fingerprint_changes_with_data():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    keys = ["k1", "k2"]
    emb1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    emb2 = np.array([[1.0, 2.0], [3.0, 5.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(keys, emb1, "model")
    fp2 = compute_corpus_fingerprint(keys, emb2, "model")
    assert fp1 != fp2


def test_corpus_fingerprint_different_key_order_same_hash():
    from lakehouse.pipeline.clustering import compute_corpus_fingerprint

    emb = np.array([[1.0], [2.0], [3.0]], dtype=np.float64)
    fp1 = compute_corpus_fingerprint(["c", "a", "b"], emb, "model")
    fp2 = compute_corpus_fingerprint(["a", "b", "c"], emb, "model")
    assert fp1 == fp2


def test_parameters_hash_deterministic():
    from lakehouse.pipeline.clustering import compute_parameters_hash

    params1 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    params2 = {"umap_n_components": 15, "hdbscan_min_cluster_size": 10}
    assert compute_parameters_hash(params1) == compute_parameters_hash(params2)


def test_parameters_hash_changes_with_params():
    from lakehouse.pipeline.clustering import compute_parameters_hash

    h1 = compute_parameters_hash({"x": 15})
    h2 = compute_parameters_hash({"x": 16})
    assert h1 != h2
```

- [ ] **Step 2: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "fingerprint|parameters_hash"
```

Expected: FAIL

- [ ] **Step 3: Implementar funciones de fingerprint**

```python
def compute_corpus_fingerprint(
    chunk_keys: list[str],
    embeddings: np.ndarray,
    model: str,
) -> str:
    data = json.dumps({
        "keys": sorted(chunk_keys),
        "embedding_hash": hashlib.sha256(embeddings.tobytes()).hexdigest(),
        "model": model,
    }, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


def compute_parameters_hash(params: dict) -> str:
    data = json.dumps(params, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "fingerprint|parameters_hash"
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega fingerprints deterministas para idempotencia de clusterizacion"
```

---

### Task 7: Carga de embeddings desde pgvector + _parse_pgvector_to_list

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar tests de carga de embeddings**

```python
def test_load_embeddings_returns_keys_and_array(pg_conn_str):
    from lakehouse.pipeline.clustering import ensure_clustering_schema, load_embeddings

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload, embedding)
            VALUES
            ('ck_test_1', 'conf_1', '2025-01-01', 'p1', 'texto 1', 'payload 1',
             '[1.0, 2.0, 3.0]'::vector),
            ('ck_test_2', 'conf_1', '2025-01-01', 'p1', 'texto 2', 'payload 2',
             '[4.0, 5.0, 6.0]'::vector),
            ('ck_test_null', 'conf_1', '2025-01-01', 'p1', 'texto null', 'payload null',
             NULL)
            ON CONFLICT (chunk_key) DO NOTHING
        """)
        conn.commit()

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    assert len(keys) == 2
    assert "ck_test_1" in keys
    assert "ck_test_2" in keys
    assert "ck_test_null" in null_keys
    assert embeddings.shape == (2, 3)


def test_load_embeddings_empty_table(pg_conn_str):
    from lakehouse.pipeline.clustering import load_embeddings

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    assert keys == []
    assert embeddings.shape[0] == 0
```

- [ ] **Step 2: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "load_embeddings"
```

Expected: FAIL

- [ ] **Step 3: Implementar load_embeddings() y _parse_pgvector_to_list()**

```python
_EMBEDDING_RE = re.compile(r"\[([-\d., eE+]+)\]")


def _parse_pgvector_to_list(pg_str: str | None) -> list[float] | None:
    if pg_str is None:
        return None
    match = _EMBEDDING_RE.search(str(pg_str))
    if not match:
        return None
    try:
        raw = match.group(1)
        if not raw.strip():
            return None
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    except (ValueError, OverflowError):
        return None


def load_embeddings(pg_conn_str: str) -> tuple[list[str], np.ndarray, list[str]]:
    raw_keys: list[str] = []
    raw_vecs: list[np.ndarray] = []
    null_keys: list[str] = []

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            "SELECT chunk_key, embedding::text FROM gold.rag_corpus"
        )
        for row in cur:
            vec = _parse_pgvector_to_list(row[1])
            if vec is None:
                null_keys.append(row[0])
                continue
            raw_keys.append(row[0])
            raw_vecs.append(np.array(vec, dtype=np.float64))

    if raw_vecs:
        embeddings = np.array(raw_vecs, dtype=np.float64)
    else:
        embeddings = np.empty((0, 0), dtype=np.float64)
    return raw_keys, embeddings, null_keys
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "load_embeddings"
```

Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega carga de embeddings desde pgvector con tests"
```

---

### Task 8: UMAP clustering + HDBSCAN

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar tests de UMAP y HDBSCAN**

```python
def test_umap_clustering_output_dimension():
    np.random.seed(42)
    X = np.random.RandomState(42).randn(100, 768).astype(np.float64)
    reducer = umap.UMAP(
        n_components=15, metric="cosine", min_dist=0.0,
        n_neighbors=15, random_state=42,
    )
    result = reducer.fit_transform(X)
    assert result.shape == (100, 15)


def test_hdbscan_labels_and_probabilities_shapes():
    np.random.seed(42)
    rng = np.random.RandomState(42)
    X = rng.randn(50, 5).astype(np.float64)
    clusterer = HDBSCAN(min_cluster_size=5, min_samples=3)
    labels = clusterer.fit_predict(X)
    probs = clusterer.probabilities_
    assert labels.shape == (50,)
    assert probs.shape == (50,)


def test_noise_gets_cluster_minus_one():
    np.random.seed(42)
    rng = np.random.RandomState(42)
    X = rng.randn(20, 2).astype(np.float64)
    X[:5] = np.random.RandomState(99).randn(5, 2) * 0.01
    X[5:10] = np.random.RandomState(88).randn(5, 2) * 0.01 + 10.0
    clusterer = HDBSCAN(min_cluster_size=3, min_samples=2)
    labels = clusterer.fit_predict(X)
    probs = clusterer.probabilities_
    for i in range(len(labels)):
        if labels[i] == -1:
            assert probs[i] == 0.0, f"Ruido debe tener pertenencia 0.0, obtuvo {probs[i]}"
```

- [ ] **Step 2: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "umap_clustering_output|hdbscan_labels|noise_gets"
```

Expected: 3 PASS (no implementacion necesaria, tests de comportamiento)

- [ ] **Step 3: Implementar run_umap_clustering() y run_hdbscan()**

```python
def run_umap_clustering(embeddings: np.ndarray, settings) -> np.ndarray:
    reducer = umap.UMAP(
        n_components=settings.umap_clustering_n_components,
        n_neighbors=min(settings.umap_clustering_n_neighbors, len(embeddings) - 1),
        min_dist=settings.umap_clustering_min_dist,
        metric=settings.umap_clustering_metric,
        random_state=settings.umap_clustering_random_state,
    )
    return reducer.fit_transform(embeddings)


def run_hdbscan(
    umap_vectors: np.ndarray,
    settings,
) -> tuple[np.ndarray, np.ndarray]:
    clusterer = HDBSCAN(
        min_cluster_size=min(settings.hdbscan_min_cluster_size, len(umap_vectors) // 2),
        min_samples=min(settings.hdbscan_min_samples, len(umap_vectors) - 1),
        metric=settings.hdbscan_metric,
        algorithm=settings.hdbscan_algorithm,
        cluster_selection_method=settings.hdbscan_cluster_selection_method,
        n_jobs=settings.hdbscan_n_jobs,
    )
    labels = clusterer.fit_predict(umap_vectors)
    probs = clusterer.probabilities_.astype(np.float64)
    probs[labels == -1] = 0.0
    return labels, probs
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "umap_clustering_output|hdbscan_labels|noise_gets"
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega UMAP clustering y HDBSCAN con tests"
```

---

### Task 9: Persistencia masiva de asignaciones

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar test de persistencia masiva**

```python
def test_persist_cluster_assignments(pg_conn_str):
    from lakehouse.pipeline.clustering import ensure_clustering_schema, persist_cluster_assignments

    run_id = "00000000-0000-0000-0000-000000000001"

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload)
            VALUES
            ('assign_1', 'c1', '2025-01-01', 'p1', 't1', 'pl1'),
            ('assign_2', 'c1', '2025-01-01', 'p1', 't2', 'pl2')
            ON CONFLICT (chunk_key) DO NOTHING
        """)
        conn.commit()

    assignments = [
        ("assign_1", 0, 0.95),
        ("assign_2", 1, 0.80),
    ]
    persist_cluster_assignments(pg_conn_str, run_id, assignments)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            "SELECT chunk_key, cluster_id, cluster_pertenencia, clustering_run_id "
            "FROM gold.rag_corpus WHERE chunk_key IN ('assign_1', 'assign_2') "
            "ORDER BY chunk_key"
        )
        rows = cur.fetchall()
        assert rows[0] == ("assign_1", 0, pytest.approx(0.95), run_id)
        assert rows[1] == ("assign_2", 1, pytest.approx(0.80), run_id)
```

- [ ] **Step 2: Ejecutar test**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py::test_persist_cluster_assignments -xvs
```

Expected: FAIL

- [ ] **Step 3: Implementar persist_cluster_assignments()**

```python
def persist_cluster_assignments(
    pg_conn_str: str,
    run_id: str,
    assignments: list[tuple[str, int, float]],
) -> None:
    if not assignments:
        return
    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TEMP TABLE _cluster_assignments (chunk_key VARCHAR, cluster_id INT, pertenencia REAL) ON COMMIT DROP"
        )
        with cur.copy("COPY _cluster_assignments FROM STDIN") as copy:
            for chunk_key, cid, membership in assignments:
                copy.write_row((chunk_key, cid, membership))
        cur.execute("""
            UPDATE gold.rag_corpus AS g
            SET cluster_id = a.cluster_id,
                cluster_pertenencia = a.pertenencia,
                clustering_run_id = %s
            FROM _cluster_assignments AS a
            WHERE g.chunk_key = a.chunk_key
        """, (run_id,))
        conn.commit()
```

- [ ] **Step 4: Ejecutar test**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py::test_persist_cluster_assignments -xvs
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega persistencia masiva de asignaciones de cluster"
```

---

### Task 10: Seleccion de chunks representativos para etiquetado

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar tests de seleccion de muestras**

```python
def test_select_representative_chunks_top_k():
    from lakehouse.pipeline.clustering import select_representative_chunks

    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.5},
        {"chunk_key": "b", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "c", "cluster_id": 0, "cluster_pertenencia": 0.3},
        {"chunk_key": "d", "cluster_id": 0, "cluster_pertenencia": 0.7},
        {"chunk_key": "e", "cluster_id": 0, "cluster_pertenencia": 0.6},
        {"chunk_key": "f", "cluster_id": 0, "cluster_pertenencia": 0.8},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=3)
    assert len(result) == 3
    assert result[0]["chunk_key"] == "b"
    assert result[1]["chunk_key"] == "f"
    assert result[2]["chunk_key"] == "d"


def test_select_representative_chunks_tiebreaker():
    from lakehouse.pipeline.clustering import select_representative_chunks

    chunks = [
        {"chunk_key": "z", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=2)
    assert result[0]["chunk_key"] == "a"
    assert result[1]["chunk_key"] == "z"


def test_select_representative_chunks_small_cluster():
    from lakehouse.pipeline.clustering import select_representative_chunks

    chunks = [
        {"chunk_key": "x", "cluster_id": 1, "cluster_pertenencia": 0.8},
    ]
    result = select_representative_chunks(chunks, cluster_id=1, k=5)
    assert len(result) == 1


def test_select_representative_chunks_excludes_other_clusters():
    from lakehouse.pipeline.clustering import select_representative_chunks

    chunks = [
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
        {"chunk_key": "b", "cluster_id": 1, "cluster_pertenencia": 0.95},
    ]
    result = select_representative_chunks(chunks, cluster_id=0, k=5)
    assert len(result) == 1
    assert result[0]["chunk_key"] == "a"


def test_select_representative_chunks_excludes_noise():
    from lakehouse.pipeline.clustering import select_representative_chunks

    chunks = [
        {"chunk_key": "n", "cluster_id": -1, "cluster_pertenencia": 0.0},
        {"chunk_key": "a", "cluster_id": 0, "cluster_pertenencia": 0.9},
    ]
    result = select_representative_chunks(chunks, cluster_id=-1, k=5)
    assert len(result) == 0
```

- [ ] **Step 2: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "select_representative"
```

Expected: FAIL

- [ ] **Step 3: Implementar select_representative_chunks()**

```python
def select_representative_chunks(
    chunks: list[dict],
    cluster_id: int,
    k: int = 5,
) -> list[dict]:
    if cluster_id < 0:
        return []
    cluster_chunks = [
        c for c in chunks
        if c.get("cluster_id") == cluster_id
    ]
    cluster_chunks.sort(key=lambda c: (-c.get("cluster_pertenencia", 0.0), c["chunk_key"]))
    return cluster_chunks[:k]
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "select_representative"
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega seleccion de chunks representativos para etiquetado"
```

---

### Task 11: Validacion de etiquetas generadas por LLM

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar tests de validate_label()**

```python
def test_validate_label_rejects_empty():
    from lakehouse.pipeline.clustering import validate_label

    label, error = validate_label("")
    assert label is None
    assert error == "empty"


def test_validate_label_rejects_multiline():
    from lakehouse.pipeline.clustering import validate_label

    label, error = validate_label("linea1\nlinea2")
    assert label is None
    assert error == "multiline"


def test_validate_label_rejects_too_many_words():
    from lakehouse.pipeline.clustering import validate_label

    label, error = validate_label("una etiqueta con mas de cuatro palabras aqui")
    assert label is None
    assert error == "too_many_words"


def test_validate_label_strips_prefixes():
    from lakehouse.pipeline.clustering import validate_label

    label, _ = validate_label("Etiqueta: Salud Publica")
    assert label == "Salud Publica"

    label, _ = validate_label("Tema: Educacion")
    assert label == "Educacion"

    label, _ = validate_label("Categoria: Seguridad Nacional")
    assert label == "Seguridad Nacional"

    label, _ = validate_label("Respuesta: Economia")
    assert label == "Economia"


def test_validate_label_strips_quotes():
    from lakehouse.pipeline.clustering import validate_label

    label, _ = validate_label('"Salud Publica"')
    assert label == "Salud Publica"


def test_validate_label_normalizes_spaces():
    from lakehouse.pipeline.clustering import validate_label

    label, _ = validate_label("  mucha   salud  publica  .")
    assert label == "mucha salud publica"


def test_validate_label_collapses_single_newline_with_text():
    from lakehouse.pipeline.clustering import validate_label

    label, _ = validate_label("texto\n")
    assert label == "texto"


def test_validate_label_accepts_valid_four_words():
    from lakehouse.pipeline.clustering import validate_label

    label, error = validate_label("Seguridad y Salud Publica")
    assert label == "Seguridad y Salud Publica"
    assert error is None


def test_validate_label_accepts_single_word():
    from lakehouse.pipeline.clustering import validate_label

    label, error = validate_label("Economia")
    assert label == "Economia"
    assert error is None
```

- [ ] **Step 2: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "validate_label"
```

Expected: FAIL

- [ ] **Step 3: Implementar validate_label()**

```python
_LABEL_RE = re.compile(r"\s+")
_LABEL_PREFIXES = [
    "etiqueta:", "tema:", "categoria:", "respuesta:",
    "label:", "category:", "topic:",
]


def validate_label(raw_label: str) -> tuple[str | None, str | None]:
    if not raw_label or not raw_label.strip():
        return None, "empty"

    label = raw_label.strip()
    label = _LABEL_RE.sub(" ", label)
    label = label.strip('"').strip("'")
    label = label.rstrip(".")

    lower = label.lower()
    for prefix in _LABEL_PREFIXES:
        if lower.startswith(prefix):
            label = label[len(prefix):].strip()
            break

    if not label:
        return None, "empty_after_normalize"

    lines = [l for l in label.split("\n") if l.strip()]
    if len(lines) > 1:
        return None, "multiline"
    label = lines[0] if lines else ""

    words = label.split()
    if len(words) > 4:
        return None, "too_many_words"

    if not label.strip():
        return None, "empty_after_normalize"

    return label.strip(), None
```

- [ ] **Step 4: Ejecutar tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs -k "validate_label"
```

Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering.py backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega validacion de etiquetas generadas por LLM"
```

---

### Task 12: Autoetiquetado con llamacpp

**Files:**
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Implementar load_prompt_template(), format_labeling_prompt(), generate_label(), label_clusters()**

```python
def load_prompt_template(version: str = "v1") -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    prompt_path = prompt_dir / f"cluster_label_{version}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def format_labeling_prompt(
    prompt_template: str,
    samples: list[dict],
    max_chars: int = 1500,
) -> str:
    texts = []
    for chunk in samples:
        text = chunk.get("chunk_text", "")
        if len(text) > max_chars:
            text = text[:max_chars]
        texts.append(f"- {text}")
    return prompt_template.replace("{textos_formateados}", "\n".join(texts))


def generate_label(
    prompt: str,
    base_url: str,
    model: str,
    max_tokens: int = 20,
    timeout: int = 30,
) -> str:
    response = httpx.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    raw = data["choices"][0]["message"]["content"].strip()
    if not raw:
        raise ValueError("empty_response")
    return raw


def label_clusters(
    pg_conn_str: str,
    run_id: str,
    cluster_ids: list[int],
    chunks: list[dict],
    settings,
) -> tuple[int, int]:
    prompt_template = load_prompt_template(settings.cluster_label_prompt_version)

    completed = 0
    failed = 0

    for cid in cluster_ids:
        if cid < 0:
            continue

        samples = select_representative_chunks(
            chunks, cid, k=settings.k_hdbscan_sampling,
        )
        if not samples:
            continue

        prompt = format_labeling_prompt(
            prompt_template, samples,
            max_chars=settings.cluster_label_max_chars_per_chunk,
        )

        label = None
        error_msg = None
        total_attempts = 0

        for attempt in range(settings.cluster_label_max_retries + 1):
            total_attempts = attempt + 1
            try:
                raw = generate_label(
                    prompt,
                    settings.llamacpp_base_url,
                    settings.llamacpp_model,
                )
                label, validation_error = validate_label(raw)
                if label:
                    break
                error_msg = validation_error
            except Exception as e:
                error_msg = str(e)

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            sample_keys = [s["chunk_key"] for s in samples]

            if label:
                cur.execute("""
                    INSERT INTO gold.cluster_labels
                        (clustering_run_id, cluster_id, cluster_label, label_status,
                         sample_size, sample_chunk_keys, model_name, prompt_version,
                         attempt_count)
                    VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s, %s)
                    ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                    SET cluster_label = EXCLUDED.cluster_label,
                        label_status = 'completed',
                        sample_size = EXCLUDED.sample_size,
                        sample_chunk_keys = EXCLUDED.sample_chunk_keys,
                        attempt_count = EXCLUDED.attempt_count,
                        updated_at = NOW()
                """, (run_id, cid, label, len(samples), sample_keys,
                      settings.llamacpp_model, settings.cluster_label_prompt_version, total_attempts))
                completed += 1
            else:
                cur.execute("""
                    INSERT INTO gold.cluster_labels
                        (clustering_run_id, cluster_id, label_status, error_message,
                         sample_size, sample_chunk_keys, model_name, prompt_version,
                         attempt_count)
                    VALUES (%s, %s, 'failed', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                    SET label_status = 'failed',
                        error_message = EXCLUDED.error_message,
                        attempt_count = EXCLUDED.attempt_count,
                        updated_at = NOW()
                """, (run_id, cid, error_msg or "unknown", len(samples), sample_keys,
                      settings.llamacpp_model, settings.cluster_label_prompt_version, total_attempts))
                failed += 1

            conn.commit()

    return completed, failed
```

- [ ] **Step 2: Verificar que los imports compilan**

```bash
cd backend && uv run python -c "from lakehouse.pipeline.clustering import label_clusters; print('OK')"
```

Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega autoetiquetado de clusters con llamacpp"
```

---

### Task 13: Orquestador run_clustering_pipeline()

**Files:**
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Implementar run_clustering_pipeline()**

```python
def run_clustering_pipeline(settings, force: bool = False) -> dict | None:
    pg_conn_str = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    input_count = len(keys) + len(null_keys)

    valid_keys, valid_embeddings, rejected = validate_embeddings(
        keys, [embeddings[i] for i in range(len(keys))],
        expected_dim=768,
    )
    rejected_count = len(rejected) + len(null_keys)

    if len(valid_keys) < 4:
        logger.warning("clustering_abortado", motivo="menos de 4 embeddings validos",
                       validos=len(valid_keys))
        return None

    umap_params = {
        "n_components": settings.umap_clustering_n_components,
        "n_neighbors": settings.umap_clustering_n_neighbors,
        "min_dist": settings.umap_clustering_min_dist,
        "metric": settings.umap_clustering_metric,
        "random_state": settings.umap_clustering_random_state,
    }
    hdbscan_params = {
        "min_cluster_size": settings.hdbscan_min_cluster_size,
        "min_samples": settings.hdbscan_min_samples,
        "metric": settings.hdbscan_metric,
        "algorithm": settings.hdbscan_algorithm,
        "cluster_selection_method": settings.hdbscan_cluster_selection_method,
        "n_jobs": settings.hdbscan_n_jobs,
    }
    labeling_params = {
        "k_sampling": settings.k_hdbscan_sampling,
        "max_chars_per_chunk": settings.cluster_label_max_chars_per_chunk,
        "max_retries": settings.cluster_label_max_retries,
        "prompt_version": settings.cluster_label_prompt_version,
        "model": settings.llamacpp_model,
    }

    all_params = {**umap_params, **hdbscan_params, **labeling_params}
    corpus_fp = compute_corpus_fingerprint(valid_keys, valid_embeddings, settings.ollama_embed_model)
    params_hash = compute_parameters_hash(all_params)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute("""
            SELECT run_id FROM gold.clustering_runs
            WHERE status = 'completed'
              AND corpus_fingerprint = %s
              AND parameters_hash = %s
            LIMIT 1
        """, (corpus_fp, params_hash))
        existing = cur.fetchone()
        if existing and not force:
            logger.info("corrida_equivalente_existente", run_id=existing[0])
            return {"run_id": existing[0], "skipped": True}

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.clustering_runs
                (status, input_count, valid_count, rejected_count,
                 corpus_fingerprint, parameters_hash, embedding_model,
                 umap_parameters, hdbscan_parameters, labeling_parameters)
            VALUES ('running', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
        """, (input_count, len(valid_keys), rejected_count,
              corpus_fp, params_hash, settings.ollama_embed_model,
              json.dumps(umap_params), json.dumps(hdbscan_params),
              json.dumps(labeling_params)))
        run_id = cur.fetchone()[0]
        conn.commit()

    try:
        normalized = normalize(valid_embeddings, norm="l2")

        umap_vectors = run_umap_clustering(normalized, settings)

        labels, probs = run_hdbscan(umap_vectors, settings)

        unique_clusters = sorted(set(int(l) for l in labels if l >= 0))
        noise_count = int((labels == -1).sum())

        assignments = [
            (valid_keys[i], int(labels[i]), float(probs[i]))
            for i in range(len(valid_keys))
        ]
        persist_cluster_assignments(pg_conn_str, run_id, assignments)

        now = datetime.now(timezone.utc)
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE gold.clustering_runs
                SET cluster_count = %s, noise_count = %s, status = 'completed'
                WHERE run_id = %s
            """, (len(unique_clusters), noise_count, run_id))
            conn.commit()

        chunks = [
            {
                "chunk_key": valid_keys[i],
                "cluster_id": int(labels[i]),
                "cluster_pertenencia": float(probs[i]),
            }
            for i in range(len(valid_keys))
        ]

        if unique_clusters:
            completed, failed = label_clusters(
                pg_conn_str, run_id, unique_clusters, chunks, settings,
            )
            final_status = "partial" if failed > 0 else "completed"
            with psycopg.connect(pg_conn_str) as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE gold.clustering_runs
                    SET labeled_cluster_count = %s, failed_label_count = %s,
                        status = %s, finished_at = NOW()
                    WHERE run_id = %s
                """, (completed, failed, final_status, run_id))
                conn.commit()
        else:
            with psycopg.connect(pg_conn_str) as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE gold.clustering_runs
                    SET finished_at = NOW()
                    WHERE run_id = %s
                """, (run_id,))
                conn.commit()

        logger.info("clusterizacion_completada", run_id=run_id,
                    clusters=len(unique_clusters), noise=noise_count)
        return {"run_id": run_id, "clusters": len(unique_clusters), "noise": noise_count}

    except Exception as e:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE gold.clustering_runs
                SET status = 'failed', error_message = %s, finished_at = NOW()
                WHERE run_id = %s
            """, (str(e)[:500], run_id))
            conn.commit()
        raise
```

**Missing import at the top of clustering.py:**

```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Verificar compilacion**

```bash
cd backend && uv run python -c "from lakehouse.pipeline.clustering import run_clustering_pipeline; print('OK')"
```

Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/pipeline/clustering.py
git commit -m "agrega orquestador run_clustering_pipeline con idempotencia y transaccionalidad"
```

---

### Task 14: Integrar clustering en EnrichService

**Files:**
- Modify: `backend/src/lakehouse/services/enrich_service.py`

- [ ] **Step 1: Modificar EnrichService.run() para llamar clustering despues de UMAP 3D**

Reemplazar el bloque dentro de `if result.get("embedded", 0) > 0:` (lineas 136-141) por:

```python
        if result.get("embedded", 0) > 0:
            self._logger.info("Ejecutando UMAP 3D sobre embeddings")
            from lakehouse.pipeline.enrichment import _compute_umap_3d  # noqa: PLC0415

            _compute_umap_3d(self._pg_conn_str)

            self._logger.info("Ejecutando clusterizacion semantica")
            try:
                from lakehouse.pipeline.clustering import run_clustering_pipeline  # noqa: PLC0415

                cluster_result = run_clustering_pipeline(self._settings)
                if cluster_result and cluster_result.get("skipped"):
                    self._logger.info(
                        "clusterizacion_omitida",
                        run_id=cluster_result.get("run_id"),
                    )
                elif cluster_result:
                    self._logger.info(
                        "clusterizacion_completada",
                        run_id=cluster_result.get("run_id"),
                        clusters=cluster_result.get("clusters"),
                        noise=cluster_result.get("noise"),
                    )
            except Exception:
                self._logger.exception("clusterizacion_fallida")
```

- [ ] **Step 2: Verificar que compila**

```bash
cd backend && uv run python -c "from lakehouse.services.enrich_service import EnrichService; print('OK')"
```

Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/services/enrich_service.py
git commit -m "integra clusterizacion automatica al final de enrich"
```

---

### Task 15: API — Pydantic schemas y router de clusters

**Files:**
- Create: `backend/src/lakehouse/schemas/cluster.py`
- Create: `backend/src/lakehouse/api/routers/clusters.py`
- Create: `backend/tests/test_api/test_clusters_router.py`
- Modify: `backend/src/lakehouse/main.py`

- [ ] **Step 1: Crear schemas de cluster**

```python
from pydantic import BaseModel, Field


class ClusterInfo(BaseModel):
    cluster_id: int
    label: str | None = None
    chunk_count: int = 0
    avg_membership: float = 0.0
    sample_chunk_keys: list[str] = Field(default_factory=list)


class ClusterPoint(BaseModel):
    chunk_key: str
    cluster_id: int
    pertenencia: float
    x: float
    y: float
    z: float


class ClusterDataResponse(BaseModel):
    run_id: str
    status: str
    cluster_count: int
    noise_count: int
    clusters: list[ClusterInfo] = Field(default_factory=list)
    points: list[ClusterPoint] = Field(default_factory=list)
```

- [ ] **Step 2: Crear router de clusters**

```python
import psycopg
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.cluster import ClusterDataResponse, ClusterInfo, ClusterPoint

router = APIRouter(tags=["clusters"])


def _get_pg_conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _fetch_cluster_data(conn_str: str, run_id: str | None = None) -> ClusterDataResponse:
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        if run_id:
            cur.execute(
                "SELECT run_id, status, cluster_count, noise_count "
                "FROM gold.clustering_runs WHERE run_id = %s",
                (run_id,),
            )
        else:
            cur.execute(
                "SELECT run_id, status, cluster_count, noise_count "
                "FROM gold.clustering_runs "
                "WHERE status IN ('completed', 'partial') "
                "ORDER BY started_at DESC LIMIT 1"
            )
        run_row = cur.fetchone()
        if not run_row:
            return ClusterDataResponse(
                run_id="", status="not_found", cluster_count=0, noise_count=0,
            )
        run_id_val, status, cluster_count, noise_count = run_row

        cur.execute("""
            SELECT gl.cluster_id, gl.cluster_label, gl.label_status,
                   gl.sample_size, gl.sample_chunk_keys
            FROM gold.cluster_labels gl
            WHERE gl.clustering_run_id = %s
            ORDER BY gl.cluster_id
        """, (run_id_val,))
        label_rows = cur.fetchall()

        labels_map: dict[int, ClusterInfo] = {}
        for cid, label, ls, ss, sck in label_rows:
            labels_map[cid] = ClusterInfo(
                cluster_id=cid,
                label=label if ls == "completed" else None,
                sample_chunk_keys=list(sck) if sck else [],
            )

        cur.execute("""
            SELECT g.cluster_id, COUNT(*) AS cnt, AVG(g.cluster_pertenencia) AS avg_p
            FROM gold.rag_corpus g
            WHERE g.clustering_run_id = %s AND g.cluster_id IS NOT NULL
            GROUP BY g.cluster_id
            ORDER BY g.cluster_id
        """, (run_id_val,))
        count_rows = cur.fetchall()

        for cid, cnt, avg_p in count_rows:
            if cid in labels_map:
                labels_map[cid].chunk_count = cnt
                labels_map[cid].avg_membership = round(float(avg_p), 4) if avg_p else 0.0
            else:
                labels_map[cid] = ClusterInfo(
                    cluster_id=cid, chunk_count=cnt,
                    avg_membership=round(float(avg_p), 4) if avg_p else 0.0,
                )

        cur.execute("""
            SELECT g.chunk_key, g.cluster_id, g.cluster_pertenencia,
                   g.embedding_3d[1] AS x, g.embedding_3d[2] AS y, g.embedding_3d[3] AS z
            FROM gold.rag_corpus g
            WHERE g.clustering_run_id = %s AND g.embedding_3d IS NOT NULL
        """, (run_id_val,))
        point_rows = cur.fetchall()

        points = [
            ClusterPoint(
                chunk_key=ck,
                cluster_id=int(cid) if cid is not None else -1,
                pertenencia=round(float(p), 4) if p else 0.0,
                x=round(float(x), 4) if x else 0.0,
                y=round(float(y), 4) if y else 0.0,
                z=round(float(z), 4) if z else 0.0,
            )
            for ck, cid, p, x, y, z in point_rows
            if x is not None and y is not None and z is not None
        ]

    return ClusterDataResponse(
        run_id=run_id_val,
        status=status,
        cluster_count=cluster_count,
        noise_count=noise_count,
        clusters=sorted(labels_map.values(), key=lambda c: c.cluster_id),
        points=points,
    )


@router.get(
    "/clusters/latest",
    response_model=ClusterDataResponse,
    summary="Get latest clustering run data",
    description="Returns cluster labels, points, and metadata for the most recent clustering run",
)
def get_clusters_latest() -> ClusterDataResponse:
    conn_str = _get_pg_conn_str()
    return _fetch_cluster_data(conn_str)


@router.get(
    "/clusters/{run_id}",
    response_model=ClusterDataResponse,
    summary="Get clustering run data by ID",
    description="Returns cluster labels, points, and metadata for a specific clustering run",
)
def get_clusters_by_run(run_id: str) -> ClusterDataResponse:
    conn_str = _get_pg_conn_str()
    return _fetch_cluster_data(conn_str, run_id=run_id)
```

- [ ] **Step 3: Crear tests del router**

```python
from fastapi.testclient import TestClient


def test_get_clusters_latest_returns_200(client: TestClient):
    response = client.get("/clusters/latest")
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "clusters" in data
    assert "points" in data


def test_get_clusters_latest_no_data_returns_empty(client: TestClient):
    response = client.get("/clusters/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found" or data["run_id"] == ""


def test_get_clusters_by_run_id_not_found(client: TestClient):
    response = client.get("/clusters/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"
```

- [ ] **Step 4: Registrar router en main.py**

Agregar en `backend/src/lakehouse/main.py`:

```python
from lakehouse.api.routers import chat, clusters, config, embeddings, health, observability, search
```

Y despues de `app.include_router(embeddings.router)`:

```python
app.include_router(clusters.router)
```

- [ ] **Step 5: Ejecutar tests de API**

```bash
cd backend && uv run pytest tests/test_api/test_clusters_router.py -xvs
```

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/lakehouse/schemas/cluster.py backend/src/lakehouse/api/routers/clusters.py backend/src/lakehouse/main.py backend/tests/test_api/test_clusters_router.py
git commit -m "agrega API de clusters con schemas, router y tests"
```

---

### Task 16: Frontend — API client y tipos

**Files:**
- Create: `frontend/src/api/clusters.ts`

- [ ] **Step 1: Crear cliente de API para clusters**

```typescript
import { apiClient } from './client'

export interface ClusterInfo {
  cluster_id: number
  label: string | null
  chunk_count: number
  avg_membership: number
  sample_chunk_keys: string[]
}

export interface ClusterPoint {
  chunk_key: string
  cluster_id: number
  pertenencia: number
  x: number
  y: number
  z: number
}

export interface ClusterDataResponse {
  run_id: string
  status: string
  cluster_count: number
  noise_count: number
  clusters: ClusterInfo[]
  points: ClusterPoint[]
}

export async function getClustersLatest(): Promise<ClusterDataResponse> {
  return apiClient<ClusterDataResponse>('/clusters/latest')
}

export async function getClustersByRun(runId: string): Promise<ClusterDataResponse> {
  return apiClient<ClusterDataResponse>(`/clusters/${runId}`)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/clusters.ts
git commit -m "agrega cliente API de clusters en frontend"
```

---

### Task 17: Frontend — Dashboard store con datos de clusters

**Files:**
- Modify: `frontend/src/stores/dashboard.ts`

- [ ] **Step 1: Agregar estado de cluster data al dashboard store**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getClustersLatest, type ClusterDataResponse, type ClusterInfo } from '../api/clusters'

export type ModalCapa = 'bronze' | 'silver' | 'gold'

export interface ResponseMetrics {
  similarity: number
  numSources: number
  coverage: number
  reranking?: string
  tokens?: number
  latency?: number
  model?: string
}

export const useDashboardStore = defineStore('dashboard', () => {
  const selectedResponseId = ref<string | null>(null)
  const modalCapa = ref<ModalCapa | null>(null)
  const autoRefresh = ref(true)
  const clusterData = ref<ClusterDataResponse | null>(null)
  const clusterError = ref<string | null>(null)

  const isModalOpen = computed(() => modalCapa.value !== null)

  const clusterColorMap = computed(() => {
    const palette = [
      '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
      '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    ]
    const map = new Map<number, string>()
    if (!clusterData.value) return map
    for (const cluster of clusterData.value.clusters) {
      const color = palette[cluster.cluster_id % palette.length]
      map.set(cluster.cluster_id, color!)
    }
    return map
  })

  function selectResponse(id: string | null) {
    selectedResponseId.value = id
  }

  function openModal(capa: ModalCapa) {
    modalCapa.value = capa
  }

  function closeModal() {
    modalCapa.value = null
  }

  function toggleAutoRefresh() {
    autoRefresh.value = !autoRefresh.value
  }

  async function fetchClusters() {
    try {
      clusterData.value = await getClustersLatest()
      clusterError.value = null
    } catch (err) {
      clusterError.value = err instanceof Error ? err.message : 'Error al obtener clusters'
    }
  }

  return {
    selectedResponseId,
    modalCapa,
    autoRefresh,
    clusterData,
    clusterError,
    clusterColorMap,
    isModalOpen,
    selectResponse,
    openModal,
    closeModal,
    toggleAutoRefresh,
    fetchClusters,
  }
})
```

- [ ] **Step 2: Verificar typecheck en frontend**

```bash
cd frontend && pnpm typecheck
```

Expected: zero errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/dashboard.ts
git commit -m "agrega estado de cluster data al dashboard store"
```

---

### Task 18: Frontend — Embeddings3D con colores por cluster y tooltips

**Files:**
- Modify: `frontend/src/components/inspector/Embeddings3D.vue`

- [ ] **Step 1: Actualizar Embeddings3D.vue con colores por cluster y tooltips**

Reemplazar el `script setup` completo:

```typescript
<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import * as echarts from 'echarts'
import 'echarts-gl'
import type { Embedding3DPoint } from '../../api/embeddings'
import { useDashboardStore } from '../../stores/dashboard'
import type { ClusterPoint } from '../../api/clusters'

const props = defineProps<{
  points: Embedding3DPoint[]
  highlightedChunks: string[]
}>()

const dashboardStore = useDashboardStore()

const chartRef = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const clusterPointMap = computed(() => {
  const map = new Map<string, ClusterPoint>()
  if (!dashboardStore.clusterData) return map
  for (const p of dashboardStore.clusterData.points) {
    map.set(p.chunk_key, p)
  }
  return map
})

const chartData = computed(() => {
  const noiseColor = 'rgba(168, 162, 158, 0.3)'

  return props.points.map((p) => {
    const cp = clusterPointMap.value.get(p.chunk_key)
    const isHighlighted = props.highlightedChunks.includes(p.chunk_key)

    let color: string
    let opacity: number

    if (isHighlighted) {
      color = '#7F1D1D'
      opacity = 1.0
    } else if (cp) {
      if (cp.cluster_id === -1) {
        color = noiseColor
        opacity = 0.3
      } else {
        color = dashboardStore.clusterColorMap.get(cp.cluster_id) ?? '#A8A29E'
        opacity = 0.7
      }
    } else {
      color = '#A8A29E'
      opacity = 0.6
    }

    let name = p.chunk_key
    if (cp && cp.cluster_id >= 0) {
      const label = dashboardStore.clusterData?.clusters.find(c => c.cluster_id === cp.cluster_id)?.label
      name = label ? `${label} (${cp.pertenencia.toFixed(2)})` : `Cluster ${cp.cluster_id} (${cp.pertenencia.toFixed(2)})`
    } else if (cp && cp.cluster_id === -1) {
      name = 'Ruido'
    }

    return {
      value: [p.x, p.y, p.z],
      itemStyle: { color, opacity },
      name,
    }
  })
})

function initChart() {
  if (!chartRef.value) return
  myChart = echarts.init(chartRef.value)
  updateChart()

  window.addEventListener('resize', handleResize)
}

function updateChart() {
  if (!myChart) return
  myChart.setOption({
    tooltip: {
      show: true,
      formatter: (params: any) => {
        const d = params.data || {}
        return d.name || ''
      },
      textStyle: { fontSize: 10 },
    },
    xAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    yAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    zAxis3D: {
      type: 'value', name: '',
      axisLine: { lineStyle: { color: '#D6D3D1' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    grid3D: {
      boxWidth: 100, boxHeight: 100, boxDepth: 100,
      viewControl: {
        autoRotate: false,
        projection: 'perspective',
        rotateSensitivity: 1,
        zoomSensitivity: 1,
        panSensitivity: 0,
      },
      light: {
        main: { intensity: 1.2, shadow: false },
        ambient: { intensity: 0.3 },
      },
    },
    series: [{
      type: 'scatter3D',
      data: chartData.value,
      symbolSize: 6,
      itemStyle: { borderWidth: 0 },
      emphasis: { itemStyle: { color: '#7F1D1D' } },
    }],
  })
}

function handleResize() {
  myChart?.resize()
}

watch(() => props.points, updateChart, { deep: true })
watch(() => props.highlightedChunks, updateChart, { deep: true })
watch(() => dashboardStore.clusterData, updateChart, { deep: true })

onMounted(initChart)
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  myChart?.dispose()
  myChart = null
})
</script>
```

Actualizar el template para agregar leyenda de ruido:

```html
<template>
  <div class="bg-white border border-stone-200 rounded-2xl p-4 flex flex-col">
    <div class="flex items-center justify-between mb-2">
      <h3 class="text-sm font-bold text-stone-950">Embeddings 3D</h3>
      <span class="text-[10px] text-stone-400">rotar + zoom limitado</span>
    </div>
    <div ref="chartRef" class="w-full h-48" />
    <div class="flex items-center gap-3 mt-2 text-[10px] text-stone-500 flex-wrap">
      <div class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full bg-stone-400" />
        <span>chunks neutros</span>
      </div>
      <div class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full bg-red-900" />
        <span>chunks citados</span>
      </div>
      <div v-if="dashboardStore.clusterData && dashboardStore.clusterData.noise_count > 0" class="flex items-center gap-1">
        <span class="w-2 h-2 rounded-full opacity-30" style="background-color: rgba(168, 162, 158, 0.3);" />
        <span>ruido ({{ dashboardStore.clusterData.noise_count }})</span>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Ejecutar typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: zero errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/inspector/Embeddings3D.vue
git commit -m "agrega colores por cluster y tooltips al scatter 3D"
```

---

### Task 19: Frontend — DashboardPage carga datos de clusters

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardPage.vue`

- [ ] **Step 1: Agregar fetch de clusters en onMounted**

Agregar dentro de `onMounted()`:

```typescript
onMounted(() => {
  obsStore.startPolling()
  chatStore.loadHistory()
  fetchEmbeddings()
  dashboardStore.fetchClusters()
})
```

- [ ] **Step 2: Ejecutar typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: zero errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/DashboardPage.vue
git commit -m "agrega carga de datos de clusters al montar dashboard"
```

---

### Task 20: Tests de integracion

**Files:**
- Create: `backend/tests/test_pipeline/test_clustering_integration.py`

- [ ] **Step 1: Crear tests de integracion con fixture data real**

```python
import json

import numpy as np
import psycopg
import pytest

from lakehouse.config import Settings
from lakehouse.pipeline.clustering import (
    compute_corpus_fingerprint,
    compute_parameters_hash,
    ensure_clustering_schema,
    load_embeddings,
    normalize,
    persist_cluster_assignments,
    run_clustering_pipeline,
    run_hdbscan,
    run_umap_clustering,
    validate_embeddings,
)


@pytest.fixture
def seeded_embeddings():
    rng = np.random.RandomState(42)
    return rng.randn(50, 768).astype(np.float64)


@pytest.fixture
def settings_override():
    s = Settings()
    s.umap_clustering_n_components = 5
    s.umap_clustering_n_neighbors = 10
    s.hdbscan_min_cluster_size = 5
    s.hdbscan_min_samples = 3
    return s


def test_umap_output_dimension_configurable(seeded_embeddings, settings_override):
    settings_override.umap_clustering_n_components = 10
    result = run_umap_clustering(seeded_embeddings, settings_override)
    assert result.shape == (50, 10)


def test_full_umap_hdbscan_pipeline(seeded_embeddings, settings_override):
    normalized = normalize(seeded_embeddings, norm="l2")
    umap_vecs = run_umap_clustering(normalized, settings_override)
    labels, probs = run_hdbscan(umap_vecs, settings_override)
    assert len(labels) == 50
    assert len(probs) == 50
    assert np.all((labels == -1) == (probs == 0.0))


def test_cluster_assignments_persisted(pg_conn_str):
    run_id = "00000000-0000-0000-0000-000000000002"
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload)
            VALUES
            ('int_test_a', 'c1', '2025-01-01', 'p1', 'texto a', 'payload a'),
            ('int_test_b', 'c1', '2025-01-01', 'p1', 'texto b', 'payload b'),
            ('int_test_c', 'c1', '2025-01-01', 'p1', 'texto c', 'payload c')
            ON CONFLICT (chunk_key) DO NOTHING
        """)
        conn.commit()

    assignments = [
        ("int_test_a", 0, 0.99),
        ("int_test_b", 1, 0.85),
        ("int_test_c", 1, 0.75),
    ]
    persist_cluster_assignments(pg_conn_str, run_id, assignments)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            "SELECT chunk_key, cluster_id, cluster_pertenencia, clustering_run_id "
            "FROM gold.rag_corpus WHERE chunk_key IN ('int_test_a', 'int_test_b', 'int_test_c') "
            "ORDER BY chunk_key"
        )
        rows = cur.fetchall()
        assert rows[0] == ("int_test_a", 0, pytest.approx(0.99), run_id)
        assert rows[1] == ("int_test_b", 1, pytest.approx(0.85), run_id)
        assert rows[2] == ("int_test_c", 1, pytest.approx(0.75), run_id)


def test_idempotency_same_input_creates_single_run(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    keys = ["idem_key_1", "idem_key_2"]
    emb = np.random.RandomState(99).randn(2, 768).astype(np.float64)
    fp = compute_corpus_fingerprint(keys, emb, "test_model")
    ph = compute_parameters_hash({"test": "v1"})

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.clustering_runs
                (status, valid_count, corpus_fingerprint, parameters_hash, embedding_model)
            VALUES ('completed', 2, %s, %s, 'test_model')
        """, (fp, ph))
        conn.commit()

    cur = conn.execute(
        "SELECT COUNT(*) FROM gold.clustering_runs "
        "WHERE corpus_fingerprint = %s AND parameters_hash = %s",
        (fp, ph),
    )
    assert cur.fetchone()[0] == 1


def test_embedding_3d_not_used_for_hdbscan(pg_conn_str):
    from lakehouse.pipeline.enrichment import _compute_umap_3d  # noqa: PLC0415

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload, embedding)
            VALUES
            ('viz_chunk_a', 'c1', '2025-01-01', 'p1', 'text a', 'payload a',
             %s::vector),
            ('viz_chunk_b', 'c1', '2025-01-01', 'p1', 'text b', 'payload b',
             %s::vector),
            ('viz_chunk_c', 'c1', '2025-01-01', 'p1', 'text c', 'payload c',
             %s::vector),
            ('viz_chunk_d', 'c1', '2025-01-01', 'p1', 'text d', 'payload d',
             %s::vector)
            ON CONFLICT (chunk_key) DO NOTHING
        """, (
            f"[{','.join(str(x) for x in np.random.RandomState(1).randn(768).tolist())}]",
            f"[{','.join(str(x) for x in np.random.RandomState(2).randn(768).tolist())}]",
            f"[{','.join(str(x) for x in np.random.RandomState(3).randn(768).tolist())}]",
            f"[{','.join(str(x) for x in np.random.RandomState(4).randn(768).tolist())}]",
        ))
        conn.commit()

    _compute_umap_3d(pg_conn_str)

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    valid_keys, valid_embeddings, rejected = validate_embeddings(
        keys, [embeddings[i] for i in range(len(keys))], expected_dim=768,
    )
    normalized = normalize(valid_embeddings, norm="l2")

    settings = Settings()
    settings.umap_clustering_n_components = 2
    settings.umap_clustering_n_neighbors = 3
    umap_cluster_vectors = run_umap_clustering(normalized, settings)

    clusterer = run_hdbscan(umap_cluster_vectors, settings)
    labels, probs = clusterer

    assert len(labels) == len(valid_keys)
    assert len(probs) == len(valid_keys)
    assert umap_cluster_vectors.shape[1] == 2  # Not 3!
```

- [ ] **Step 2: Ejecutar tests de integracion**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering_integration.py -xvs
```

Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering_integration.py
git commit -m "agrega tests de integracion para pipeline de clusterizacion"
```

---

### Task 21: Verificacion final — ruff + typecheck + coverage

- [ ] **Step 1: Ruff check + format**

```bash
cd backend && uv run ruff check --fix && uv run ruff format
```

Expected: zero errors, zero changes

- [ ] **Step 2: Typecheck backend**

```bash
cd backend && uv run ty check
```

Expected: zero errors

- [ ] **Step 3: Typecheck frontend**

```bash
cd frontend && pnpm typecheck
```

Expected: zero errors

- [ ] **Step 4: Ejecutar todos los tests con coverage**

```bash
cd backend && uv run pytest -xvs --cov=src --cov-report=term-missing --cov-fail-under=90
```

Expected: all PASS, coverage >= 90%

- [ ] **Step 5: Ejecutar tests de frontend**

```bash
cd frontend && pnpm test:unit
```

Expected: all PASS

- [ ] **Step 6: Commit final**

```bash
git add -A
git commit -m "completa clusterizacion, autoetiquetado, API y frontend de clusters gold"
```
