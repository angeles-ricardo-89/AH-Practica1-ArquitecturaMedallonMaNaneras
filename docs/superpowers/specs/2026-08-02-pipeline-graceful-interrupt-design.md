# Spec — Interrupción graceful de pipelines

## 1. Objetivo

Si un pipeline (`ingest`, `parse`, `enrich`) es interrumpido por el usuario con `Ctrl+C` (SIGINT) o con
`kill` (SIGTERM), debe terminar **gracefully**: dejar de tomar trabajo nuevo, drenar el trabajo en vuelo,
hacer el cleanup de conexiones/executors, y **reflejar su estado al terminar** escribiendo la corrida en
`observability.pipeline_runs` como `interrupted` con los conteos parciales alcanzados.

Hoy no existe manejo de señales: la interrupción mata el proceso abruptamente y la corrida queda clavada en
`status='running'` para siempre, mostrando "En curso" en el dashboard de observabilidad.

## 2. Estado actual

- Los comandos en `backend/src/lakehouse/cli.py` (`ingest:72`, `parse:110`, `enrich:155`) escriben
  `pipeline_runs` con `running` al inicio y `ok`/`error` al final vía `_write_pipeline_run` (`cli.py:30`).
- El schema en `backend/src/lakehouse/db/observability_conn.py` tiene `CHECK (status IN ('running','ok','error'))`.
- Loops de trabajo: `_worker` en `ingestion.py:31`, `_run_sequential`/`_run_parallel` en `parse_service.py:122/149`,
  `enrich_interventions` en `enrichment.py:270`.
- No hay ningún handler de señales en el codebase (grep de `signal|KeyboardInterrupt|SIGINT|SIGTERM` = 0 resultados).
- Frontend: `PipelineCard.vue`, `PipelineTimeline.vue`, `SemaforoEstado.vue` mapean estados; hoy el backend emite
  `ok`/`error` pero el frontend busca `complete`/`failed`, mostrando el estado crudo.

## 3. Decisiones de diseño

| Decisión | Elección |
|---|---|
| Estado de corrida interrumpida | Nuevo estado `interrupted` (distinto de `ok`/`error`) |
| Semántica del cierre | Drenar trabajo en vuelo (terminar unidad actual, luego cleanup) |
| Conteos parciales | Sí, registrar `records_in/out` y `dlq_count` parciales |
| Exit code del CLI | `130` (128+SIGINT) al interrumpirse gracefulmente |
| Drive-by fix frontend | Mapear `ok`→Completo y `error`→Falló además de `interrupted` |

## 4. Componentes

### 4.1 Nuevo módulo `backend/src/lakehouse/pipeline/interrupt.py`

```python
class InterruptState:
    def requested(self) -> bool: ...
    def reset(self) -> None: ...

@contextmanager
def install_graceful_interrupt() -> Iterator[None]: ...
```

- `InterruptState` usa un `threading.Event` interno (thread-safe, inmune al GIL).
- `install_graceful_interrupt()`:
  - Registra handlers para `SIGINT` y `SIGTERM` con `signal.signal` (solo válido en el hilo principal).
  - **Primera señal:** setea el flag (cooperativo). No mata el proceso.
  - **Segunda señal:** `os._exit(128 + signum)` (force quit, para desbloquear trabajo atascado).
  - `finally`: restaura los handlers originales con `signal.signal(sig, previous)`.
- Si `signal.signal` falla (hilo no principal), loguea warning y continúa sin tracking de interrupción
  (comportamiento degradado idéntico al de `ensure_observability_tables`).

### 4.2 Puntos de chequeo del flag en los loops

Cada loop que procesa trabajo pregunta `interrupt_state.requested()` **entre unidades** de trabajo; si está
seteado, deja de tomar trabajo nuevo. La unidad actual termina de procesarse (drenado).

**`_worker` en `backend/src/lakehouse/pipeline/ingestion.py:31`:**

- Al inicio de cada iteración del `while True`, chequear `interrupt_state.requested()` → `break`.
- Como `await queue.get()` es bloqueante, usar un poll corto: `asyncio.wait_for(queue.get(), timeout=0.5)`
  atrapando `asyncio.TimeoutError` para re-chequear el flag. Si `requested()` está seteado y el timeout
  ocurre, `break` sin procesar el siguiente URL.
- El URL ya en vuelo (descargado/computado) se procesa y cuenta.

**`_run_sequential` en `backend/src/lakehouse/services/parse_service.py:122`:**

- Chequeo al tope del `for source_url, raw_html in rows:` → `break`. La fila en curso se procesa y cuenta.

**`_run_parallel` en `backend/src/lakehouse/services/parse_service.py:149`:**

- En el bucle que hace `pool.submit(...)`, chequear `requested()` → dejar de enviar futures nuevos (`break`).
- Los futures ya enviados se drenan en el `for future in as_completed(futures)`; el `ProcessPoolExecutor.__exit__`
  (`shutdown(wait=True)`) ya garantiza que terminen.
- `_run_with_transaction` (`parse_service.py:199`) hace **COMMIT parcial** al salir normalmente, persistiendo
  lo ya mergeado.

**`enrich_interventions` en `backend/src/lakehouse/pipeline/enrichment.py:270`:**

- Rama parallel (`:293`): igual que `_run_parallel` — dejar de `pool.submit`, drenar en `as_completed`.
- Rama sequential (`:339`): chequeo al tope del `for record in windows:` → `break`.
- El `conn.commit()` final (`:375`) persiste lo ya almacenado en Gold.

### 4.3 CLI (`backend/src/lakehouse/cli.py`)

Los tres comandos (`ingest`, `parse`, `enrich`) adoptan el mismo patrón:

```python
with install_graceful_interrupt():
    result = service.run(...)
    if interrupt_state.requested():
        _write_pipeline_run(pg_conn_str, CAPA, "interrupted", started_at,
                            records_in=..., records_out=..., dlq_count=...)
        typer.echo("Pipeline interrumpido tras N registros")
        raise typer.Exit(code=130)
    _write_pipeline_run(pg_conn_str, CAPA, "ok", started_at, ...)
```

- El `started_at` se calcula ANTES de instalar los handlers (para no contaminar el run_id determinista).
- El manejo de `except Exception` para `error` se conserva intacto.
- En `dry_run` no se escribe `pipeline_runs` (comportamiento actual intacto).

### 4.4 Migración de schema (`backend/src/lakehouse/db/observability_conn.py`)

- `PIPELINE_RUNS_DDL`: cambiar el CHECK a `('running','ok','error','interrupted')` (bases frescas).
- En `ensure_observability_tables`, tras el DDL, ejecutar un `ALTER` idempotente para bases existentes:

```sql
ALTER TABLE observability.pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;
ALTER TABLE observability.pipeline_runs
    ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN ('running','ok','error','interrupted'));
```

> Nota: el DDL de la tabla no nombra explícitamente la constraint; Postgres la auto-nombra
> `pipeline_runs_status_check`. El `ALTER` usa ese nombre canónico.

### 4.5 Frontend

**`frontend/src/components/pipeline/PipelineCard.vue`:**

```ts
if (s === 'ok' || s === 'Completo') return 'Completo'
if (s === 'error' || s === 'Falló') return 'Falló'
if (s === 'interrupted') return 'Interrumpido'        // label
if (s === 'interrupted') return 'bg-amber-100 text-amber-700 border-amber-200'  // class
```

**`frontend/src/components/pipeline/PipelineTimeline.vue`:**

```ts
'border-amber-500': layer.status === 'interrupted',
// e incluir 'interrupted' en el fallback stone-300
```

**`frontend/src/components/dashboard/SemaforoEstado.vue`:**

```ts
interrupted: 'bg-amber-500',
// label: 'Interrumpido'
```

El drive-by fix `ok`→Completo / `error`→Falló aplica en los 3 componentes (hoy el backend emite
`ok`/`error` pero el frontend busca `complete`/`failed`/`Completo`/`Falló`).

## 5. Health global (endpoint `GET /observability/pipeline/layers`)

La lógica actual de `observability.py:134-144` se mantiene sin cambios:

| Estados | health_global |
|---|---|
| Sin datos | `sin datos` |
| Las 3 capas en `ok` | `Healthy` |
| Alguna `error` | `Failed` |
| Alguna `running` (sin errores) | `Degraded` |
| Alguna `interrupted` (sin errores) | `Degraded` (cae en el `else`) |
| Faltan capas | `Degraded` |

`interrupted` es una condición degradada, no un fallo: no debe teñir `health_global` como `Failed`.

## 6. Casos borde (Gate QA)

1. `Ctrl+C` durante `ingest` con pool de workers → los workers en vuelo terminan su URL, se escribe
   `interrupted` con `records_in/out` parciales, exit 130.
2. `kill -TERM` (SIGTERM) durante `parse` parallel → deja de enviar futures, drena, COMMIT parcial,
   `interrupted` con `interventions` y `dlq` parciales.
3. Doble señal (Ctrl+C dos veces) → fuerza `os._exit(130)`.
4. Señal durante `dry_run` → no se escribe `pipeline_runs`; solo mensaje y exit 130.
5. Señal antes de cualquier trabajo (pipeline casi no avanzó) → `interrupted` con conteos 0.
6. Postgres caído al intentar escribir `interrupted` → `_write_pipeline_run` ya es best-effort
   (try/except + warning), no rompe el exit 130.
7. Idempotencia: reejecutar el pipeline tras una interrupción funciona normal (MERGE upsert con claves
   deterministas), sin duplicados.
8. Señal en hilo no principal (ej. tests) → `install_graceful_interrupt` degrada sin crashear.

## 7. Tests (Gate Q, ≥90% coverage en módulos modificados)

- **`tests/test_interrupt.py`** (nuevo): `InterruptState.requested/reset`; `install_graceful_interrupt`
  setea el flag con `signal.raise_signal(SIGTERM)` y restaura handlers; doble señal hace `os._exit`
  (mockeado); degradación en hilo no principal.
- **`tests/test_cli.py`**: nuevos casos por comando — mock de `interrupt_state.requested()=True` →
  `_write_pipeline_run` llamado con `interrupted` y conteos parciales; `Exit(130)`.
- **`tests/test_parse_service.py` / `test_enrichment.py` / `test_ingestion.py`**: simular flag seteado
  a mitad del lote → los loops rompen temprano y devuelven conteos parciales.
- **`tests/test_observability_conn.py`**: el constraint acepta `interrupted` (consulta
  `pg_get_constraintdef`).
- **Frontend `frontend/tests/components/PipelineCard.test.ts`**: caso `status: 'interrupted'` →
  label "Interrumpido" y clase ámbar; casos `ok`/`error` → "Completo"/"Falló".

## 8. Fuera de alcance (YAGNI)

- Graceful shutdown de `evaluate_rag` (no escribe `pipeline_runs`).
- TTL/sweeper que reclasifique corridas huérfanas `running` de procesos muertos por `kill -9` u OOM.
- Retry/reanudación automática desde el punto de interrupción.
- `preemptive` cancelación de HTTP/embedding en curso (solo drenado cooperativo).

## 9. Criterios de éxito

1. `Ctrl+C`/`kill` en cualquiera de los 3 pipelines → la corrida aparece como `interrupted` con conteos
   parciales en la DB y en el dashboard, no como `running`.
2. Exit code 130 al interrumpirse; 0 en éxito; 1 en error (inalterado).
3. Los workers en vuelo terminan su unidad; no hay registros a medio escribir.
4. Reejecución posterior no duplica ni corrompe (idempotencia).
5. Gates: `ruff check`, `ty check`, pytest ≥90% coverage, `pnpm lint` y `pnpm typecheck` pasan.
