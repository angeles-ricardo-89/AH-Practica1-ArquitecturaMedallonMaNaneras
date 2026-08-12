# Spec — Separación de Clustering y Autoetiquetado Semántico

## 1. Objetivo

Separar en dos fases independientes el proceso de clusterizacion semantica (UMAP + HDBSCAN) y el
autoetiquetado con LLM local que actualmente se ejecutan juntos al final de `pipeline enrich`.
Cada fase debe poder ejecutarse de forma independiente mediante dos flags nuevos de `enrich`:
`--run-clustering` y `--run-semantic-cluster-labeling`.

El comportamiento por defecto de `enrich` (sin flags) se conserva: ejecuta clustering + etiquetado
automaticamente cuando hay embeddings nuevos.

## 2. Estado actual

- `pipeline/clustering.py` expone `run_clustering_pipeline(settings, force)` que hace clustering
  (UMAP+HDBSCAN, persistencia de asignaciones) y luego llama `label_clusters()` en la misma corrida.
- `EnrichService.run()` llama `run_clustering_pipeline()` dentro de `if result["embedded"] > 0:`.
- CLI `enrich` en `cli.py` no expone control sobre las fases.
- **Bug detectado:** el orquestador arma los `chunks` para etiquetado sin `chunk_text`, por lo que
  `format_labeling_prompt()` envia ejemplos vacios al LLM (etiquetas sin contenido real).

## 3. Decisiones de diseno

| Decision | Eleccion |
|---|---|
| Separacion | Dos orquestadores: `run_clustering()` y `run_labeling()` en `pipeline/clustering.py` |
| Default de `enrich` | Ambos auto (status quo), gated por `embedded > 0` |
| `--run-clustering` | Fuerza re-clustering (`force=True`), sin etiquetar, corre aunque `embedded == 0` |
| `--run-semantic-cluster-labeling` | Etiqueta clusters pendientes de la ultima corrida `completed`/`partial`, sin clusterizar |
| Ambas flags | Fuerza clustering y luego etiqueta esa corrida |
| Objetivo del etiquetado | Ultima corrida con clusters pendientes (sin label `completed`); reintenta `failed` |
| Idempotencia del etiquetado | Por cluster: se salta los que ya tienen label `completed` |
| Bug de chunk_text | Se corrige: `run_labeling()` carga `chunk_text` desde la DB antes de etiquetar |
| Nombre | Se renombra `run_clustering_pipeline` -> `run_clustering` |

## 4. Flujo

### 4.1 `run_clustering(settings, force=False)` — clustering puro

```
1. ensure_clustering_schema()
2. load_embeddings() + validate_embeddings()  →  abortar si < 4 validos
3. compute_corpus_fingerprint() + compute_parameters_hash()
4. Idempotencia: si existe corrida completed equivalente y not force → skip
5. INSERT gold.clustering_runs (status='running')
6. UMAP clustering + HDBSCAN
7. persist_cluster_assignments()
8. UPDATE run: cluster_count, noise_count, status='completed'
9. NO etiqueta (antes hacia label_clusters)
10. Retorna {"run_id", "clusters", "noise"} | {"run_id", "skipped": True} | None (abort)
```

### 4.2 `run_labeling(settings, run_id=None)` — etiquetado independiente

```
1. Resolver run objetivo:
   - Si run_id es None → SELECT run_id FROM gold.clustering_runs
     WHERE status IN ('completed','partial') ORDER BY started_at DESC LIMIT 1
   - Si run_id es dado → verificar que exista con status IN ('completed','partial');
     si no existe o tiene otro status (ej: 'running'/'failed') → log y return None
   - Si no hay corrida → log y return None
2. Cargar chunks de esa corrida:
   SELECT chunk_key, chunk_text, cluster_id, cluster_pertenencia
   FROM gold.rag_corpus WHERE clustering_run_id = %s AND cluster_id >= 0
3. cluster_ids = distinct(cluster_id) de los chunks
4. ya_etiquetados = SELECT cluster_id FROM gold.cluster_labels
   WHERE clustering_run_id = %s AND label_status = 'completed'
5. targets = cluster_ids - ya_etiquetados
6. Si no hay targets → log y return
7. completed, failed = label_clusters(pg_conn_str, run_id, targets, chunks_con_texto, settings)
8. Recalcular conteos desde gold.cluster_labels:
   labeled_cluster_count = COUNT(* WHERE label_status='completed')
   failed_label_count    = COUNT(* WHERE label_status='failed')
9. UPDATE run: labeled_cluster_count, failed_label_count,
   status = 'partial' si failed_label_count > 0 else 'completed', finished_at = NOW()
10. Retorna {"run_id", "clusters", "completed", "failed"}
```

### 4.3 `EnrichService.run()` — logica de flags

```python
flags = run_clustering_flag or run_labeling_flag
do_cluster = run_clustering_flag or not flags
do_label   = run_labeling_flag or not flags

if do_cluster:
    cluster_result = run_clustering(settings, force=run_clustering_flag)
else:
    cluster_result = None

if do_label:
    run_labeling(settings, run_id=cluster_result["run_id"] if cluster_result else None)
```

- **Sin flags**: el bloque solo se ejecuta si `embedded > 0` (status quo).
- **Solo `--run-clustering`**: `do_cluster=True`, `do_label=False`.
- **Solo `--run-semantic-cluster-labeling`**: `do_cluster=False`, `do_label=True` (corre aunque `embedded == 0`).
- **Ambas**: `do_cluster=True`, `do_label=True` con `force=True`.

Fallas de clustering/etiquetado NO revierten el enrich: se loguean y continúan (comportamiento actual).

## 5. CLI

```python
@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, ...),
    conference_date: str | None = typer.Option(None, "--date", ...),
    clean: bool = typer.Option(default=False, ...),
    workers: int = typer.Option(default=1, ...),
    run_clustering: bool = typer.Option(default=False,
        help="Fuerza re-clusterizacion semantica (UMAP+HDBSCAN)"),
    run_semantic_cluster_labeling: bool = typer.Option(default=False,
        help="Ejecuta autoetiquetado LLM sobre clusters existentes"),
) -> None:
    ...
    result = service.run(dry_run=..., conference_date=..., clean=..., workers=...,
                         run_clustering=run_clustering,
                         run_semantic_cluster_labeling=run_semantic_cluster_labeling)
```

## 6. Modulos del codigo

### 6.1 `backend/src/lakehouse/pipeline/clustering.py` — modificado

| Funcion | Cambio |
|---|---|
| `run_clustering_pipeline` → `run_clustering` | Renombrada; elimina la llamada a `label_clusters()` |
| `run_labeling` | Nueva: orquestador de etiquetado independiente |
| `label_clusters` | Sin cambios de firma; recibe chunks con `chunk_text` |
| `format_labeling_prompt` | Sin cambios (ya lee `chunk_text`) |

### 6.2 `backend/src/lakehouse/services/enrich_service.py` — modificado

- `EnrichService.run()` acepta `run_clustering: bool = False` y `run_semantic_cluster_labeling: bool = False`.
- Aplica la logica de flags de la seccion 4.3.

### 6.3 `backend/src/lakehouse/cli.py` — modificado

- Agrega las dos flags a `enrich` y las pasa a `service.run()`.

## 7. Pruebas

### 7.1 Unitarias (`backend/tests/test_pipeline/test_clustering.py`)

| Test | Verifica |
|---|---|
| `test_run_clustering_does_not_label` | `run_clustering` no invoca `label_clusters` (con mocks) |
| `test_run_labeling_targets_latest_run` | Sin run_id usa la ultima corrida completed/partial |
| `test_run_labeling_skips_completed_labels` | No re-etiqueta clusters con label completed |
| `test_run_labeling_retries_failed` | Reintenta clusters con label failed o sin fila |
| `test_run_labeling_no_runs_returns_none` | Sin corridas → None |
| `test_run_labeling_updates_run_status_partial` | Fallos → status partial, conteos recalculados |
| `test_run_labeling_loads_chunk_text` | Los samples enviados al prompt incluyen chunk_text real |

### 7.2 Unitarias de servicio (`backend/tests/test_pipeline/test_umap.py` o `test_services/test_enrich_service.py`)

| Test | Verifica |
|---|---|
| `test_enrich_default_runs_cluster_and_label` | Sin flags, con embedded>0 → clustering + etiquetado |
| `test_enrich_default_skips_when_no_embeddings` | embedded==0 → ni clustering ni etiquetado |
| `test_enrich_run_clustering_only` | `--run-clustering` fuerza clustering, no etiqueta |
| `test_enrich_run_labeling_only` | `--run-labeling` etiqueta sin clusterizar |
| `test_enrich_both_flags` | Ambas → clustering forzado + etiquetado |

### 7.3 Integracion (`backend/tests/test_pipeline/test_clustering_integration.py`)

| Test | Verifica |
|---|---|
| `test_labeling_independent_after_clustering` | Clustering manual, luego `run_labeling` etiqueta la ultima corrida |
| `test_run_clustering_no_label_rows` | Clustering puro no crea filas en `gold.cluster_labels` |

## 8. Casos borde

| Caso | Comportamiento |
|---|---|
| Sin corridas de clustering y `--run-semantic-cluster-labeling` | Log + return None, no error |
| Corrida objetivo sin clusters validos (todos ruido) | No targets → return, status intacto |
| Etiquetado re-ejecutado | Solo etiqueta clusters sin label completed |
| llamacpp no disponible | Labels fallan, run pasa a `partial`, conteos reflejan fallos |
| `embedded == 0` y `--run-clustering` | Re-clusteriza el corpus existente desde DB |
| Falla en clustering | Log y continua (no revierte enrich) |

## 9. Fuera de alcance

- Lock de concurrencia (MVP, igual que spec original)
- Re-etiquetado forzado de labels ya `completed`
- Etiquetado de corridas historicas especificas (sin `--run-id`)
- Cambios en API `/clusters/*` o en el frontend
