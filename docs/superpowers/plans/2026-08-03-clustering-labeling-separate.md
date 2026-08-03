# Separación de Clustering y Autoetiquetado Semántico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar `run_clustering_pipeline()` en dos orquestadores independientes (`run_clustering` y `run_labeling`) y exponerlos desde `pipeline enrich` mediante `--run-clustering` y `--run-semantic-cluster-labeling`, conservando el comportamiento automático por defecto.

**Architecture:** `pipeline/clustering.py` pasa a tener `run_clustering(settings, force)` (solo UMAP+HDBSCAN+persistencia, sin etiquetar) y `run_labeling(settings, run_id=None)` (etiqueta clusters pendientes de una corrida, cargando `chunk_text` desde la DB — corrige bug de ejemplos vacíos). `EnrichService.run()` recibe dos flags y aplica la lógica: sin flags → ambos auto (gated por `embedded > 0`); `--run-clustering` → fuerza clustering sin etiquetar; `--run-semantic-cluster-labeling` → solo etiqueta; ambas → clustering forzado + etiquetado.

**Tech Stack:** Python 3.13, umap-learn, hdbscan, scikit-learn, psycopg, Typer, pytest.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/src/lakehouse/pipeline/clustering.py` | Modify | Split orchestrators + helper `_build_pg_conn_str` + new `run_labeling` |
| `backend/src/lakehouse/services/enrich_service.py` | Modify | Flag logic en `run()` |
| `backend/src/lakehouse/cli.py` | Modify | Dos flags en `enrich` |
| `backend/tests/test_pipeline/test_clustering.py` | Modify | Renombrar tests + `test_run_clustering_does_not_label` + tests de `run_labeling` |
| `backend/tests/test_pipeline/test_umap.py` | Modify | Tests de EnrichService con flags |
| `backend/tests/test_cli.py` | Modify | Tests de flags de CLI |
| `backend/tests/test_pipeline/test_clustering_integration.py` | Modify | Tests de integración independientes |

---

### Task 1: Renombrar `run_clustering_pipeline` → `run_clustering` (clustering puro)

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Actualizar tests — renombrar y agregar test de "no etiqueta"**

En `backend/tests/test_pipeline/test_clustering.py`, en el bloque de imports cambiar:

```python
from lakehouse.pipeline.clustering import (
    compute_corpus_fingerprint,
    compute_parameters_hash,
    ensure_clustering_schema,
    format_labeling_prompt,
    load_embeddings,
    load_prompt_template,
    persist_cluster_assignments,
    run_clustering,
    select_representative_chunks,
    validate_embeddings,
    validate_label,
)
```

Renombrar las funciones de test (solo el nombre y el cuerpo que usa `run_clustering_pipeline(Settings())` → `run_clustering(Settings())`):

- `test_run_clustering_pipeline_aborts_with_fewer_than_4` → `test_run_clustering_aborts_with_fewer_than_4`
- `test_run_clustering_pipeline_skips_existing_run` → `test_run_clustering_skips_existing_run`
- `test_run_clustering_pipeline_success` → `test_run_clustering_success` (y **eliminar** el patch `clustering, "label_clusters"`)
- `test_run_clustering_pipeline_marks_failed_on_error` → `test_run_clustering_marks_failed_on_error`
- `test_run_clustering_pipeline_all_noise_no_labeling` → `test_run_clustering_all_noise_no_labeling`

Agregar al final del archivo:

```python
def test_run_clustering_does_not_label(monkeypatch):
    keys, arr = _valid_embeddings(n=4)
    monkeypatch.setattr(clustering, "load_embeddings", lambda *_args: (keys, arr, []))

    _mock_pg_connect(monkeypatch, select_fetchone=None, insert_fetchone=("run-1",))

    labels = np.array([0, 0, 1, -1], dtype=np.int64)
    probs = np.array([0.9, 0.8, 0.7, 0.0], dtype=np.float64)
    monkeypatch.setattr(
        clustering, "run_umap_clustering", lambda _emb, _settings: np.zeros((4, 15))
    )
    monkeypatch.setattr(
        clustering, "run_hdbscan", lambda _vecs, _settings: (labels, probs)
    )
    monkeypatch.setattr(
        clustering, "persist_cluster_assignments", lambda *_args, **_kwargs: None
    )
    labeled = MagicMock()
    monkeypatch.setattr(clustering, "label_clusters", labeled)

    result = run_clustering(Settings())
    assert result["clusters"] == 2
    labeled.assert_not_called()
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs --no-cov -k "run_clustering"
```

Expected: FAIL — `ImportError: cannot import name 'run_clustering'` (o `AttributeError` al recolectar).

- [ ] **Step 3: Refactorizar en clustering.py**

Agregar helper `_build_pg_conn_str` justo después de `logger = ...`:

```python
def _build_pg_conn_str(settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
```

Renombrar `run_clustering_pipeline(settings, force: bool = False)` → `run_clustering(settings, force: bool = False)`, reemplazar el primer bloque por `pg_conn_str = _build_pg_conn_str(settings)`, **eliminar** el dict `labeling_params`, cambiar `all_params = {**umap_params, **hdbscan_params}`, y **eliminar** `labeling_parameters` del INSERT. El nuevo cuerpo completo:

```python
def run_clustering(settings, force: bool = False) -> dict | None:
    pg_conn_str = _build_pg_conn_str(settings)

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    keys, embeddings, null_keys = load_embeddings(pg_conn_str)
    input_count = len(keys) + len(null_keys)

    valid_keys, valid_embeddings, rejected = validate_embeddings(
        keys,
        [embeddings[i] for i in range(len(keys))],
        expected_dim=768,
    )
    rejected_count = len(rejected) + len(null_keys)

    if len(valid_keys) < 4:
        logger.warning(
            "clustering_abortado", motivo="menos de 4 embeddings validos", validos=len(valid_keys)
        )
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

    all_params = {**umap_params, **hdbscan_params}
    corpus_fp = compute_corpus_fingerprint(
        valid_keys, valid_embeddings, settings.ollama_embed_model
    )
    params_hash = compute_parameters_hash(all_params)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT run_id FROM gold.clustering_runs
            WHERE status = 'completed'
              AND corpus_fingerprint = %s
              AND parameters_hash = %s
            LIMIT 1
        """,
            (corpus_fp, params_hash),
        )
        existing = cur.fetchone()
        if existing and not force:
            logger.info("corrida_equivalente_existente", run_id=existing[0])
            return {"run_id": existing[0], "skipped": True}

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gold.clustering_runs
                (status, input_count, valid_count, rejected_count,
                 corpus_fingerprint, parameters_hash, embedding_model,
                 umap_parameters, hdbscan_parameters)
            VALUES ('running', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
        """,
            (
                input_count,
                len(valid_keys),
                rejected_count,
                corpus_fp,
                params_hash,
                settings.ollama_embed_model,
                json.dumps(umap_params),
                json.dumps(hdbscan_params),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("No se pudo crear el run de clusterizacion")
        run_id = row[0]
        conn.commit()

    try:
        normalized = normalize(valid_embeddings, norm="l2")

        umap_vectors = run_umap_clustering(normalized, settings)

        labels, probs = run_hdbscan(umap_vectors, settings)

        unique_clusters = sorted({int(lb) for lb in labels if lb >= 0})
        noise_count = int((labels == -1).sum())

        assignments = [
            (valid_keys[i], int(labels[i]), float(probs[i])) for i in range(len(valid_keys))
        ]
        persist_cluster_assignments(pg_conn_str, run_id, assignments)

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE gold.clustering_runs
                SET cluster_count = %s, noise_count = %s, status = 'completed',
                    finished_at = NOW()
                WHERE run_id = %s
            """,
                (len(unique_clusters), noise_count, run_id),
            )
            conn.commit()

        logger.info(
            "clusterizacion_completada",
            run_id=run_id,
            clusters=len(unique_clusters),
            noise=noise_count,
        )
        return {"run_id": run_id, "clusters": len(unique_clusters), "noise": noise_count}

    except Exception as e:
        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE gold.clustering_runs
                SET status = 'failed', error_message = %s, finished_at = NOW()
                WHERE run_id = %s
            """,
                (str(e)[:500], run_id),
            )
            conn.commit()
        raise
```

(Esto elimina el bloque `chunks = [...]` y el `if unique_clusters:` completo de `label_clusters`.)

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs --no-cov -k "run_clustering"
```

Expected: 6 PASS (`test_run_clustering_aborts_with_fewer_than_4`, `test_run_clustering_skips_existing_run`, `test_run_clustering_success`, `test_run_clustering_marks_failed_on_error`, `test_run_clustering_all_noise_no_labeling`, `test_run_clustering_does_not_label`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/clustering.py backend/tests/test_pipeline/test_clustering.py
git commit -m "separa run_clustering del etiquetado y renombra a run_clustering"
```

---

### Task 2: Orquestador `run_labeling()` independiente

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering.py`
- Modify: `backend/src/lakehouse/pipeline/clustering.py`

- [ ] **Step 1: Agregar helper de mock y tests de run_labeling**

En `backend/tests/test_pipeline/test_clustering.py`, agregar al final:

```python
def _mock_labeling_connect(monkeypatch, run_row, chunk_rows=None, completed_rows=None, count_rows=None):
    captured: dict[str, list] = {"cursors": []}

    def _connect(*_args, **_kwargs):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        captured["cursors"].append(cursor)

        def _execute(sql, params=None):
            result = MagicMock()
            if "FROM gold.clustering_runs" in sql:
                result.fetchone.return_value = run_row
            elif "FROM gold.rag_corpus" in sql:
                result.fetchall.return_value = chunk_rows or []
            elif "GROUP BY label_status" in sql:
                result.fetchall.return_value = count_rows or []
            elif "FROM gold.cluster_labels" in sql:
                result.fetchall.return_value = completed_rows or []
            else:
                result.fetchall.return_value = []
            conn.execute.return_value = result
            return result

        conn.execute.side_effect = _execute
        cm = MagicMock()
        cm.__enter__.return_value = conn
        return cm

    monkeypatch.setattr(clustering.psycopg, "connect", _connect)
    return captured


def test_run_labeling_targets_latest_run(monkeypatch):
    chunk_rows = [
        ("k1", "texto uno sobre salud", 0, 0.9),
        ("k2", "texto dos sobre salud", 0, 0.8),
        ("k3", "texto tres sobre economia", 1, 0.7),
    ]
    _mock_labeling_connect(
        monkeypatch,
        run_row=("run-latest",),
        chunk_rows=chunk_rows,
        count_rows=[("completed", 2)],
    )
    captured: dict = {}

    def _fake_label(pg_conn_str, run_id, cluster_ids, chunks, settings):
        captured["run_id"] = run_id
        captured["cluster_ids"] = cluster_ids
        captured["chunks"] = chunks
        return (2, 0)

    monkeypatch.setattr(clustering, "label_clusters", _fake_label)

    result = clustering.run_labeling(Settings())

    assert result["run_id"] == "run-latest"
    assert result["completed"] == 2
    assert result["failed"] == 0
    assert captured["run_id"] == "run-latest"
    assert captured["cluster_ids"] == [0, 1]
    assert captured["chunks"][0]["chunk_text"] == "texto uno sobre salud"


def test_run_labeling_skips_completed_labels(monkeypatch):
    chunk_rows = [
        ("k1", "t1", 0, 0.9),
        ("k2", "t2", 1, 0.8),
    ]
    _mock_labeling_connect(
        monkeypatch,
        run_row=("run-1",),
        chunk_rows=chunk_rows,
        completed_rows=[(0,)],
        count_rows=[("completed", 1)],
    )
    captured: dict = {}

    def _fake_label(pg_conn_str, run_id, cluster_ids, chunks, settings):
        captured["ids"] = cluster_ids
        return (1, 0)

    monkeypatch.setattr(clustering, "label_clusters", _fake_label)

    result = clustering.run_labeling(Settings())
    assert result["run_id"] == "run-1"
    assert captured["ids"] == [1]


def test_run_labeling_with_explicit_run_id(monkeypatch):
    chunk_rows = [("k1", "t1", 0, 0.9)]
    _mock_labeling_connect(
        monkeypatch,
        run_row=("run-explicit",),
        chunk_rows=chunk_rows,
        count_rows=[("completed", 1)],
    )
    captured: dict = {}

    def _fake_label(pg_conn_str, run_id, cluster_ids, chunks, settings):
        captured["run_id"] = run_id
        return (1, 0)

    monkeypatch.setattr(clustering, "label_clusters", _fake_label)

    result = clustering.run_labeling(Settings(), run_id="run-explicit")
    assert result["run_id"] == "run-explicit"
    assert captured["run_id"] == "run-explicit"


def test_run_labeling_no_runs_returns_none(monkeypatch):
    _mock_labeling_connect(monkeypatch, run_row=None)
    labeled = MagicMock()
    monkeypatch.setattr(clustering, "label_clusters", labeled)

    assert clustering.run_labeling(Settings()) is None
    labeled.assert_not_called()


def test_run_labeling_no_pending_returns_none(monkeypatch):
    chunk_rows = [("k1", "t1", 0, 0.9)]
    _mock_labeling_connect(
        monkeypatch,
        run_row=("run-1",),
        chunk_rows=chunk_rows,
        completed_rows=[(0,)],
    )
    labeled = MagicMock()
    monkeypatch.setattr(clustering, "label_clusters", labeled)

    assert clustering.run_labeling(Settings()) is None
    labeled.assert_not_called()


def test_run_labeling_updates_status_partial(monkeypatch):
    chunk_rows = [("k1", "t1", 0, 0.9)]
    captured = _mock_labeling_connect(
        monkeypatch,
        run_row=("run-1",),
        chunk_rows=chunk_rows,
        count_rows=[("failed", 1)],
    )
    monkeypatch.setattr(clustering, "label_clusters", lambda *_args, **_kwargs: (0, 1))

    result = clustering.run_labeling(Settings())
    assert result["failed"] == 1

    update_calls = [
        c
        for cursor in captured["cursors"]
        for c in cursor.execute.call_args_list
        if "status = 'partial'" in c[0][0]
    ]
    assert len(update_calls) == 1
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs --no-cov -k "run_labeling"
```

Expected: FAIL — `AttributeError: module 'lakehouse.pipeline.clustering' has no attribute 'run_labeling'`.

- [ ] **Step 3: Implementar run_labeling()**

Agregar en `backend/src/lakehouse/pipeline/clustering.py`, después de `run_clustering`:

```python
def run_labeling(settings, run_id: str | None = None) -> dict | None:
    pg_conn_str = _build_pg_conn_str(settings)

    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)

    with psycopg.connect(pg_conn_str) as conn:
        if run_id:
            cur = conn.execute(
                """
                SELECT run_id FROM gold.clustering_runs
                WHERE run_id = %s AND status IN ('completed', 'partial')
                """,
                (run_id,),
            )
        else:
            cur = conn.execute(
                """
                SELECT run_id FROM gold.clustering_runs
                WHERE status IN ('completed', 'partial')
                ORDER BY started_at DESC LIMIT 1
                """
            )
        row = cur.fetchone()
    if row is None:
        logger.info("etiquetado_sin_corrida_objetivo", run_id=run_id)
        return None
    target_run_id = row[0]

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT chunk_key, chunk_text, cluster_id, cluster_pertenencia
            FROM gold.rag_corpus
            WHERE clustering_run_id = %s AND cluster_id >= 0
            """,
            (target_run_id,),
        )
        chunk_rows = cur.fetchall()

    chunks = [
        {
            "chunk_key": r[0],
            "chunk_text": r[1] or "",
            "cluster_id": int(r[2]),
            "cluster_pertenencia": float(r[3]) if r[3] is not None else 0.0,
        }
        for r in chunk_rows
    ]
    if not chunks:
        logger.info("etiquetado_sin_chunks", run_id=target_run_id)
        return None

    cluster_ids = sorted({c["cluster_id"] for c in chunks})

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT cluster_id FROM gold.cluster_labels
            WHERE clustering_run_id = %s AND label_status = 'completed'
            """,
            (target_run_id,),
        )
        done = {r[0] for r in cur.fetchall()}

    targets = [cid for cid in cluster_ids if cid not in done]
    if not targets:
        logger.info("etiquetado_sin_pendientes", run_id=target_run_id)
        return None

    completed, failed = label_clusters(pg_conn_str, target_run_id, targets, chunks, settings)

    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.execute(
            """
            SELECT label_status, COUNT(*) FROM gold.cluster_labels
            WHERE clustering_run_id = %s GROUP BY label_status
            """,
            (target_run_id,),
        )
        counts = {r[0]: r[1] for r in cur.fetchall()}
        labeled_count = counts.get("completed", 0)
        failed_count = counts.get("failed", 0)
        final_status = "partial" if failed_count > 0 else "completed"
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE gold.clustering_runs
            SET labeled_cluster_count = %s, failed_label_count = %s,
                status = %s, finished_at = NOW()
            WHERE run_id = %s
            """,
            (labeled_count, failed_count, final_status, target_run_id),
        )
        conn.commit()

    logger.info(
        "etiquetado_completado",
        run_id=target_run_id,
        clusters=len(targets),
        completed=completed,
        failed=failed,
    )
    return {
        "run_id": target_run_id,
        "clusters": len(targets),
        "completed": completed,
        "failed": failed,
    }
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering.py -xvs --no-cov -k "run_labeling"
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/clustering.py backend/tests/test_pipeline/test_clustering.py
git commit -m "agrega run_labeling para etiquetado semantico independiente"
```

---

### Task 3: Lógica de flags en EnrichService.run()

**Files:**
- Modify: `backend/tests/test_pipeline/test_umap.py`
- Modify: `backend/src/lakehouse/services/enrich_service.py`

- [ ] **Step 1: Actualizar y agregar tests de EnrichService**

En `backend/tests/test_pipeline/test_umap.py`, reemplazar TODA la clase `TestEnrichServiceCallsUmap` (líneas ~280-366) por:

```python
class TestEnrichServiceCallsUmap:
    def _service(self) -> EnrichService:
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        return EnrichService(
            settings=MagicMock(),
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )

    def test_run_calls_umap_when_embedded(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            mock_cluster.return_value = {"run_id": "r1", "clusters": 2, "noise": 1}
            result = self._service().run(dry_run=False)

        assert result["embedded"] == 2
        mock_umap.assert_called_once_with("postgresql://u:p@h:5433/d")
        mock_cluster.assert_called_once()
        assert mock_cluster.call_args.kwargs["force"] is False
        mock_label.assert_called_once()
        assert mock_label.call_args.kwargs["run_id"] == "r1"

    def test_run_skips_umap_when_nothing_embedded(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
        ):
            mock_enrich.return_value = {"embedded": 0, "failed": 0, "total": 2}
            result = self._service().run(dry_run=False)

        assert result["embedded"] == 0
        mock_umap.assert_not_called()
        mock_cluster.assert_not_called()
        mock_label.assert_not_called()

    def test_run_logs_skipped_clustering(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d"),
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
            patch("lakehouse.services.enrich_service.get_logger"),
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            mock_cluster.return_value = {"run_id": "run-1", "skipped": True}
            self._service().run(dry_run=False)

        mock_cluster.assert_called_once()
        mock_label.assert_called_once()
        assert mock_label.call_args.kwargs["run_id"] == "run-1"

    def test_run_logs_completed_clustering(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d"),
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
            patch("lakehouse.services.enrich_service.get_logger") as mock_logger,
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            mock_cluster.return_value = {"run_id": "run-1", "clusters": 3, "noise": 1}
            self._service().run(dry_run=False)

        logger_instance = mock_logger.return_value
        infos = [c.args[0] for c in logger_instance.info.call_args_list]
        assert "clusterizacion_completada" in infos

    def test_run_swallows_clustering_failure(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d"),
            patch(
                "lakehouse.pipeline.clustering.run_clustering",
                side_effect=RuntimeError("db down"),
            ) as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
            patch("lakehouse.services.enrich_service.get_logger") as mock_logger,
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            result = self._service().run(dry_run=False)

        assert result["embedded"] == 2
        mock_cluster.assert_called_once()
        mock_label.assert_called_once()
        assert mock_label.call_args.kwargs["run_id"] is None
        mock_logger.return_value.exception.assert_called_once()

    def test_run_clustering_flag_forces_and_skips_labeling(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
        ):
            mock_enrich.return_value = {"embedded": 0, "failed": 0, "total": 0}
            self._service().run(dry_run=False, run_clustering=True)

        mock_umap.assert_not_called()
        mock_cluster.assert_called_once()
        assert mock_cluster.call_args.kwargs["force"] is True
        mock_label.assert_not_called()

    def test_run_labeling_flag_only(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
        ):
            mock_enrich.return_value = {"embedded": 0, "failed": 0, "total": 0}
            self._service().run(dry_run=False, run_semantic_cluster_labeling=True)

        mock_umap.assert_not_called()
        mock_cluster.assert_not_called()
        mock_label.assert_called_once()
        assert mock_label.call_args.kwargs["run_id"] is None

    def test_run_both_flags_cluster_then_label(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d"),
            patch("lakehouse.pipeline.clustering.run_clustering") as mock_cluster,
            patch("lakehouse.pipeline.clustering.run_labeling") as mock_label,
        ):
            mock_enrich.return_value = {"embedded": 0, "failed": 0, "total": 0}
            mock_cluster.return_value = {"run_id": "r9", "clusters": 1, "noise": 0}
            self._service().run(
                dry_run=False,
                run_clustering=True,
                run_semantic_cluster_labeling=True,
            )

        mock_cluster.assert_called_once()
        assert mock_cluster.call_args.kwargs["force"] is True
        mock_label.assert_called_once()
        assert mock_label.call_args.kwargs["run_id"] == "r9"
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_umap.py -xvs --no-cov
```

Expected: FAIL — `TypeError: EnrichService.run() got an unexpected keyword argument 'run_clustering'`.

- [ ] **Step 3: Implementar flags en EnrichService.run()**

En `backend/src/lakehouse/services/enrich_service.py`, cambiar la firma de `run()`:

```python
    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
        clean: bool = False,
        workers: int = 1,
        run_clustering: bool = False,
        run_semantic_cluster_labeling: bool = False,
    ) -> dict:
```

Y reemplazar el bloque `if result.get("embedded", 0) > 0:` (desde `if result.get("embedded", 0) > 0:` hasta `return result`) por:

```python
        if result.get("embedded", 0) > 0:
            self._logger.info("Ejecutando UMAP 3D sobre embeddings")
            from lakehouse.pipeline.enrichment import _compute_umap_3d  # noqa: PLC0415

            _compute_umap_3d(self._pg_conn_str)

        flags = run_clustering or run_semantic_cluster_labeling
        do_cluster = run_clustering or (not flags and result.get("embedded", 0) > 0)
        do_label = run_semantic_cluster_labeling or (not flags and result.get("embedded", 0) > 0)

        cluster_result: dict | None = None
        if do_cluster:
            self._logger.info("Ejecutando clusterizacion semantica")
            try:
                from lakehouse.pipeline.clustering import run_clustering as _run_clustering  # noqa: PLC0415

                cluster_result = _run_clustering(self._settings, force=run_clustering)
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
                cluster_result = None

        if do_label:
            self._logger.info("Ejecutando autoetiquetado semantico")
            try:
                from lakehouse.pipeline.clustering import run_labeling  # noqa: PLC0415

                label_result = run_labeling(
                    self._settings,
                    run_id=cluster_result["run_id"] if cluster_result else None,
                )
                if label_result:
                    self._logger.info(
                        "etiquetado_completado",
                        run_id=label_result.get("run_id"),
                        completed=label_result.get("completed"),
                        failed=label_result.get("failed"),
                    )
            except Exception:
                self._logger.exception("etiquetado_fallido")
        return result
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_umap.py -xvs --no-cov && uv run pytest tests/test_services/test_enrich_service.py -q --no-cov
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/enrich_service.py backend/tests/test_pipeline/test_umap.py
git commit -m "integra flags de clustering y etiquetado en EnrichService"
```

---

### Task 4: Flags en CLI `pipeline enrich`

**Files:**
- Modify: `backend/tests/test_cli.py`
- Modify: `backend/src/lakehouse/cli.py`

- [ ] **Step 1: Actualizar y agregar tests de CLI**

En `backend/tests/test_cli.py`, en `TestPipelineEnrich`, actualizar los cuatro `assert_called_once_with` existentes para incluir los nuevos kwargs:

`test_enrich_dry_run`:

```python
        mock_svc.run.assert_called_once_with(
            dry_run=True,
            conference_date=None,
            clean=False,
            workers=1,
            run_clustering=False,
            run_semantic_cluster_labeling=False,
        )
```

`test_enrich_no_dry_run`:

```python
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=False,
            workers=1,
            run_clustering=False,
            run_semantic_cluster_labeling=False,
        )
```

`test_enrich_clean`:

```python
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=True,
            workers=1,
            run_clustering=False,
            run_semantic_cluster_labeling=False,
        )
```

`test_enrich_with_workers`:

```python
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=False,
            workers=4,
            run_clustering=False,
            run_semantic_cluster_labeling=False,
        )
```

Agregar al final de `TestPipelineEnrich`:

```python
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_run_clustering_flag(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--run-clustering"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=False,
            workers=1,
            run_clustering=True,
            run_semantic_cluster_labeling=False,
        )

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_run_labeling_flag(
        self, mock_conn, mock_ensure, mock_write, mock_svc_cls
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--run-semantic-cluster-labeling"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=False,
            workers=1,
            run_clustering=False,
            run_semantic_cluster_labeling=True,
        )

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_both_flags(self, mock_conn, mock_ensure, mock_write, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(
            app,
            ["pipeline", "enrich", "--run-clustering", "--run-semantic-cluster-labeling"],
        )
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(
            dry_run=False,
            conference_date=None,
            clean=False,
            workers=1,
            run_clustering=True,
            run_semantic_cluster_labeling=True,
        )
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_cli.py -xvs --no-cov -k "enrich"
```

Expected: FAIL — `AssertionError: Expected call ... run_clustering=...` o `KeyError`.

- [ ] **Step 3: Implementar flags en cli.py**

En `backend/src/lakehouse/cli.py`, en `def enrich(...)`, agregar tras el parámetro `workers`:

```python
    run_clustering: bool = typer.Option(
        default=False,
        help="Fuerza re-clusterizacion semantica (UMAP+HDBSCAN) sobre el corpus",
    ),
    run_semantic_cluster_labeling: bool = typer.Option(
        default=False,
        help="Ejecuta autoetiquetado LLM sobre clusters existentes de la ultima corrida",
    ),
```

Y cambiar la llamada a `service.run(...)`:

```python
            result = service.run(
                dry_run=dry_run,
                conference_date=conference_date,
                clean=clean,
                workers=workers,
                run_clustering=run_clustering,
                run_semantic_cluster_labeling=run_semantic_cluster_labeling,
            )
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_cli.py -xvs --no-cov -k "enrich"
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/cli.py backend/tests/test_cli.py
git commit -m "agrega flags --run-clustering y --run-semantic-cluster-labeling a enrich"
```

---

### Task 5: Tests de integración independientes

**Files:**
- Modify: `backend/tests/test_pipeline/test_clustering_integration.py`

- [ ] **Step 1: Agregar imports y tests**

En `backend/tests/test_pipeline/test_clustering_integration.py`, agregar al bloque de imports:

```python
from lakehouse.pipeline import clustering
```

Agregar al final del archivo:

```python
def test_run_clustering_no_label_rows(pg_conn_str):
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(
            "DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'clust_only_%' "
            "OR chunk_key LIKE 'viz_chunk_%' OR chunk_key LIKE 'ck_test_%'"
        )
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        vectors = [np.random.RandomState(i).randn(768).tolist() for i in (11, 12, 13, 14)]
        cur.executemany(
            """
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload, embedding)
            VALUES (%s, 'c1', '2025-01-01', 'p1', 'texto', 'payload', %s::vector)
            """,
            [
                (f"clust_only_{i}", "[" + ",".join(str(x) for x in v) + "]")
                for i, v in enumerate(vectors)
            ],
        )
        conn.commit()

    run_id = None
    try:
        settings = Settings()
        settings.umap_clustering_n_components = 2
        settings.umap_clustering_n_neighbors = 3
        settings.hdbscan_min_cluster_size = 2
        settings.hdbscan_min_samples = 2

        result = clustering.run_clustering(settings)
        assert result is not None
        run_id = result["run_id"]

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM gold.cluster_labels WHERE clustering_run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 0
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'clust_only_%'")
            if run_id:
                conn.execute(
                    "DELETE FROM gold.cluster_labels WHERE clustering_run_id = %s", (run_id,)
                )
                conn.execute(
                    "DELETE FROM gold.clustering_runs WHERE run_id = %s", (run_id,)
                )
            conn.commit()


def test_labeling_independent_after_clustering(pg_conn_str, monkeypatch):
    run_id = "33333333-3333-3333-3333-333333333333"

    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'label_after_%'")
        ensure_clustering_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gold.clustering_runs
                (run_id, status, cluster_count, noise_count, corpus_fingerprint,
                 parameters_hash, embedding_model)
            VALUES (%s, 'completed', 1, 0, 'fp', 'ph', 'model')
            """,
            (run_id,),
        )
        cur.execute(
            """
            INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date,
                                         participant, chunk_text, payload,
                                         cluster_id, cluster_pertenencia, clustering_run_id)
            VALUES
            ('label_after_1', 'c1', '2025-01-01', 'p1', 'texto sobre salud publica', 'pl1',
             0, 0.95, %s),
            ('label_after_2', 'c1', '2025-01-01', 'p1', 'otro texto sobre salud', 'pl2',
             0, 0.85, %s),
            ('label_after_3', 'c1', '2025-01-01', 'p1', 'texto de economia', 'pl3',
             1, 0.75, %s)
            ON CONFLICT (chunk_key) DO NOTHING
            """,
            (run_id, run_id, run_id),
        )
        conn.commit()

    try:
        monkeypatch.setattr(
            clustering, "generate_label", lambda *_args, **_kwargs: "Salud Publica"
        )
        result = clustering.run_labeling(Settings(), run_id=run_id)

        assert result["run_id"] == run_id
        assert result["completed"] == 2
        assert result["failed"] == 0

        with psycopg.connect(pg_conn_str) as conn:
            cur = conn.execute(
                "SELECT cluster_id, cluster_label, label_status FROM gold.cluster_labels "
                "WHERE clustering_run_id = %s ORDER BY cluster_id",
                (run_id,),
            )
            rows = cur.fetchall()
            assert rows[0] == (0, "Salud Publica", "completed")
            assert rows[1] == (1, "Salud Publica", "completed")

            cur = conn.execute(
                "SELECT labeled_cluster_count, failed_label_count, status "
                "FROM gold.clustering_runs WHERE run_id = %s",
                (run_id,),
            )
            run_row = cur.fetchone()
            assert run_row is not None
            assert run_row[0] == 2
            assert run_row[1] == 0
            assert run_row[2] == "completed"
    finally:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'label_after_%'")
            conn.execute("DELETE FROM gold.cluster_labels WHERE clustering_run_id = %s", (run_id,))
            conn.execute("DELETE FROM gold.clustering_runs WHERE run_id = %s", (run_id,))
            conn.commit()
```

- [ ] **Step 2: Ejecutar tests de integración**

```bash
cd backend && uv run pytest tests/test_pipeline/test_clustering_integration.py -xvs --no-cov
```

Expected: 7 PASS (5 existentes + 2 nuevos).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pipeline/test_clustering_integration.py
git commit -m "agrega tests de integracion para fases independientes de clustering y etiquetado"
```

---

### Task 6: Verificación final — ruff + typecheck + coverage

- [ ] **Step 1: Ruff check + format**

```bash
cd backend && uv run ruff check --fix && uv run ruff format
```

Expected: zero errors.

- [ ] **Step 2: Typecheck backend**

```bash
cd backend && uv run ty check
```

Expected: zero errors.

- [ ] **Step 3: Suite completa con coverage**

```bash
cd backend && uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90
```

Expected: all PASS, coverage >= 90%.

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "separa clustering de autoetiquetado semantico con flags independientes"
```

---

## Referencias cruzadas (tipos/firmas usados)

- `run_clustering(settings, force: bool = False) -> dict | None` — definido en Task 1.
- `run_labeling(settings, run_id: str | None = None) -> dict | None` — definido en Task 2.
- `label_clusters(pg_conn_str, run_id, cluster_ids, chunks, settings) -> tuple[int, int]` — existente, recibe `chunks` con `chunk_text`.
- `EnrichService.run(..., run_clustering: bool, run_semantic_cluster_labeling: bool) -> dict` — Task 3.
- `_build_pg_conn_str(settings) -> str` — Task 1.
- Helper de test `_mock_labeling_connect` — Task 2.
