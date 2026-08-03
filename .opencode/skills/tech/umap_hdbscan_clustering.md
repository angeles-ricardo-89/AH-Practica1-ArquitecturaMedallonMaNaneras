# Skill: UMAP + HDBSCAN Clustering
**Domain**: Semantic clustering of embeddings in Gold layer.
**Tech**: umap-learn, hdbscan, scikit-learn, numpy.

## Overview
Use this skill when implementing UMAP dimensionality reduction followed by HDBSCAN density-based clustering on embedding vectors. The UMAP instance used for clustering MUST be independent from any UMAP instance used for 3D visualization.

## Key Architecture Rule

Two separate UMAP instances, two different purposes:

| Instance | `n_components` | `min_dist` | Purpose |
|---|---|---|---|
| Visualization UMAP | 3 | default (0.1) | Populate `embedding_3d` for the dashboard |
| Clustering UMAP | 15 (configurable) | 0.0 | Feed HDBSCAN for density detection |

Never reuse the same fitted UMAP object for both purposes.

## Implementation Patterns

### 1. Load and validate embeddings from PostgreSQL/pgvector

```python
from psycopg import connect
import numpy as np

def load_embeddings(conn_str: str) -> tuple[list[str], np.ndarray]:
    with connect(conn_str) as conn:
        cur = conn.execute(
            "SELECT chunk_key, embedding FROM gold.rag_corpus"
        )
        keys, vectors = [], []
        for row in cur:
            parsed = _parse_pgvector_to_list(row[1])
            if parsed is not None:
                keys.append(row[0])
                vectors.append(parsed)
    return keys, np.array(vectors, dtype=np.float64)
```

### 2. Validate embeddings before clustering

```python
def validate_embeddings(
    keys: list[str],
    embeddings: np.ndarray,
    expected_dim: int = 768,
) -> tuple[list[str], np.ndarray, list[tuple[str, str]]]:
    valid_keys, valid_vecs, rejected = [], [], []
    for i, (key, vec) in enumerate(zip(keys, embeddings)):
        if vec is None:
            rejected.append((key, "null"))
        elif vec.shape[0] != expected_dim:
            rejected.append((key, f"dimension:{vec.shape[0]}"))
        elif not np.isfinite(vec).all():
            rejected.append((key, "non_finite"))
        elif np.all(vec == 0):
            rejected.append((key, "zero_vector"))
        elif np.linalg.norm(vec) == 0:
            rejected.append((key, "zero_norm"))
        else:
            valid_keys.append(key)
            valid_vecs.append(vec)
    return valid_keys, np.array(valid_vecs, dtype=np.float64), rejected
```

### 3. Normalize embeddings with L2 norm

```python
from sklearn.preprocessing import normalize

normalized = normalize(embeddings, norm="l2")
```

Always normalize in memory. Never overwrite embeddings stored in PostgreSQL.

### 4. UMAP for clustering (independent from visualization UMAP)

```python
import umap

umap_clusterer = umap.UMAP(
    n_components=15,       # Configurable: UMAP_CLUSTERING_N_COMPONENTS
    n_neighbors=30,        # Configurable: UMAP_CLUSTERING_N_NEIGHBORS
    min_dist=0.0,          # Must be 0.0 for density detection
    metric="cosine",       # Semantic similarity metric
    random_state=42,       # For reproducibility
)
clustering_vectors = umap_clusterer.fit_transform(normalized_embeddings)
# Shape: (n_chunks, n_components) = (N, 15)
```

### 5. HDBSCAN on UMAP-reduced vectors

```python
from hdbscan import HDBSCAN

clusterer = HDBSCAN(
    min_cluster_size=15,                 # Configurable
    min_samples=5,                        # Configurable
    metric="euclidean",                   # Euclidean on UMAP space
    algorithm="auto",
    cluster_selection_method="eom",
    n_jobs=-1,
)
cluster_ids = clusterer.fit_predict(clustering_vectors)
cluster_membership = clusterer.probabilities_  # Strength of membership

# Map noise to explicit values
cluster_ids = np.where(cluster_ids == -1, -1, cluster_ids)
cluster_membership = np.where(cluster_ids == -1, 0.0, cluster_membership)
```

### 6. Persist assignments with bulk UPDATE

```python
def persist_cluster_assignments(
    conn,
    run_id: str,
    assignments: list[tuple[str, int, float]],
) -> None:
    """Bulk UPDATE via VALUES + FROM. Never UPDATE row-by-row."""
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE _cluster_assignments (chunk_key VARCHAR, cluster_id INT, pertenencia REAL) ON COMMIT DROP")
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

## Anti-Patterns

- **Don't reuse visualization UMAP for clustering** — separate instance, separate parameters.
- **Don't run HDBSCAN on raw embeddings** — always reduce with UMAP first.
- **Don't run HDBSCAN on `embedding_3d`** — that's for visualization only.
- **Don't UPDATE row-by-row** — use temp table + bulk UPDATE FROM.
- **Don't split corpus into batches for multiple HDBSCAN fits** — single fit on all data.
- **Don't run HDBSCAN inside PostgreSQL** — run in Python memory.

## Idempotency

Compute fingerprints before execution:

```python
import hashlib, json

def compute_corpus_fingerprint(chunk_keys: list[str], embeddings: np.ndarray, model: str) -> str:
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

Check for existing equivalent run before executing:

```python
cur.execute("""
    SELECT run_id FROM gold.clustering_runs
    WHERE status = 'completed'
      AND corpus_fingerprint = %s
      AND parameters_hash = %s
    LIMIT 1
""", (corpus_fp, params_hash))
existing = cur.fetchone()
if existing and not force:
    logger.info("corrida_equivalente_existente", run_id=existing[0])
    return existing[0]
```
