# Paralelizacion de Silver Layer con ProcessPoolExecutor

## Problema

`ParseService.run()` procesa las filas de `bronze.raw_html` de forma secuencial: un loop `for` itera
sobre cada `(source_url, raw_html)`, parsea el HTML con regex, y escribe los resultados a DuckDB con
`INSERT OR IGNORE`. Con ~300 conferencias y ~40 intervenciones cada una, la capa Silver tarda ~15s
en completar. El parseo es CPU-bound (regex, hashing SHA256, stripping HTML) y el GIL de CPython
impide que `ThreadPoolExecutor` ofrezca paralelismo real.

```
for idx, (source_url, raw_html) in enumerate(rows):
    reporter.update(idx + 1)                    # asume orden secuencial
    interventions, dlq = self._process_row(...)  # CPU-bound
```

## Solucion

Agregar un argumento `--workers` al comando `pipeline parse` que controla cuantos procesos
paralelos ejecutan el parseo de HTML. Default `1` (comportamiento actual intacto). Con `workers > 1`,
se usa `ProcessPoolExecutor` donde cada worker parsea exclusivamente; el proceso principal recolecta
los resultados y serializa los INSERTs a DuckDB.

**Principio clave:** los workers solo parsean HTML (CPU-bound). Todos los INSERTs ocurren en el
proceso principal, eliminando riesgo de race conditions y lock contention en DuckDB.

## Diseno

### 1. Worker function `_parse_one_row` (nueva, nivel modulo)

Funcion pickleable que recibe `(source_url, raw_html, conference_date)` y retorna resultados de
parseo sin tocar DuckDB:

```python
def _parse_one_row(
    source_url: str,
    raw_html: str,
    conference_date: str | None,
) -> tuple[ConferenceRecord | None, list[InterventionRecord], list[DLQRejectRecord]]:
    date = conference_date or parse_conference_date(raw_html, source_url)
    if date is None:
        conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
        dlq = DLQRejectRecord(
            source_record_id=conference_id,
            rejection_reason="unknown_date",
            raw_data=source_url,
        )
        return None, [], [dlq]

    records = parse_html_to_interventions(raw_html, source_url, date)
    conference = build_conference_record(source_url, date, raw_html)
    interventions = [r for r in records if isinstance(r, InterventionRecord)]
    dlq = [r for r in records if isinstance(r, DLQRejectRecord)]
    return conference, interventions, dlq
```

**Ubicacion:** `backend/src/lakehouse/services/parse_service.py`, a nivel modulo (fuera de la clase).

Todos los imports usados por la funcion ya existen en el modulo (`hashlib`, `parse_conference_date`,
`parse_html_to_interventions`, `build_conference_record`, `ConferenceRecord`, `InterventionRecord`,
`DLQRejectRecord`). No se requieren nuevos imports.

Las Pydantic models (`ConferenceRecord`, `InterventionRecord`, `DLQRejectRecord`) son picklables
porque Pydantic v2 soporta `__reduce__` nativamente.

### 2. `ParseService.run()` con `workers`

Firma nueva: `run(self, dry_run, conference_date, clean, workers: int = 1) -> dict`.

**Validacion:** `workers = max(1, workers)`.

#### Path `workers == 1` (secuencial, igual que hoy)

Sin cambios, excepto que `reporter.update(idx + 1)` se reemplaza por `reporter.tick()` por
consistencia con el path paralelo.

#### Path `workers > 1` (paralelo con ProcessPoolExecutor)

```python
# 1. Leer todas las filas de Bronze en memoria
conn = self._conn
rows = conn.execute(
    "SELECT source_url, raw_html FROM bronze.raw_html"
).fetchall()
conn.close()

# 2. Despachar parseo a ProcessPoolExecutor
reporter = ProgressReporter(total=len(rows), label="silver")
with ProcessPoolExecutor(max_workers=workers) as pool:
    futures: dict[Future, tuple[str, str]] = {}
    for source_url, raw_html in rows:
        future = pool.submit(
            _parse_one_row, source_url, raw_html, conference_date
        )
        futures[future] = (source_url, raw_html)

    # 3. Nuevo connection para escritura (proceso principal)
    write_conn = get_connection(self._settings.ducklake_data_path)

    # 4. Drenar resultados
    for future in as_completed(futures):
        conference, interventions, dlq_records = future.result()
        if conference is not None:
            merge_conference(write_conn, conference)
        for record in interventions:
            merge_intervention(write_conn, record)
        for dlq in dlq_records:
            insert_dlq_record(write_conn, dlq)
        total_interventions += len(interventions)
        total_dlq += len(dlq_records)
        if conference is None:
            total_dlq += 1
        reporter.tick()

    write_conn.close()
```

**Notas:**
- `reporter.tick()` — cuenta filas COMPLETADAS conforme `as_completed()` las drena. Orden no
  deterministico, pero el contador final es exacto.
- La conexion de escritura se abre DESPUES de cerrar la de lectura, y se cierra al final. DuckDB
  permite multiples conexiones al mismo archivo `.duckdb` sin problema.
- `dry_run` usa el mismo camino que el path paralelo: los workers parsean normalmente, el
  proceso principal cuenta `interventions`/`dlq` pero no escribe a DuckDB (no llama a
  `merge_conference`, `merge_intervention`, ni `insert_dlq_record`). `ensure_silver_tables` y
  `drop_silver_tables` tampoco se ejecutan en dry_run. El resultado devuelto es identico al path
  no-dry-run pero sin modificar la base de datos.
- `clean` aplica `drop_silver_tables()` y `ensure_silver_tables()` en el proceso principal antes de
  despachar workers (sin cambios respecto a hoy).
- **Fork-safety:** en Linux fork, `ProcessPoolExecutor` fork-ea los workers de forma lazy en el
  primer `submit()`, que ocurre despues de que `write_conn` se abrio. Los workers heredan el file
  descriptor de DuckDB, pero NUNCA lo usan: `_parse_one_row` es una funcion pura sin acceso a
  conexiones. La seguridad no depende de que el pool se cree antes de la conexion, sino de la
  invariante "los workers nunca tocan DuckDB". Documentar esta invariante como requisito permanente.

**Imports nuevos:** `from concurrent.futures import Future, ProcessPoolExecutor, as_completed`.

### 3. CLI `pipeline parse`

```python
workers: int = typer.Option(default=1, help="Parallel parse workers (ProcessPoolExecutor)")
```

Pasa `workers=workers` a `service.run(...)`.

### 4. `ParseService.__init__`

Sin cambios. El `_conn` se usa para lectura inicial (SELECT) y se cierra. Para escritura se abre una
nueva conexion via `get_connection()`.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/services/parse_service.py` | + `_parse_one_row`, `run()` acepta `workers` y path paralelo |
| `backend/src/lakehouse/cli.py` | `--workers` en comando `parse` |
| `backend/tests/test_services/test_parse_service.py` | Tests `_parse_one_row`, path paralelo con `workers>1` |
| `backend/tests/test_cli.py` | Test `--workers` en CLI |

## Verificacion

1. `ruff check --fix && ruff format` en archivos modificados
2. `uv run ty src/` sin errores
3. `uv run pytest -xvs --cov=src --cov-report=term-missing` (coverage >= 90% en modulo modificado)
4. Manual: `make pipeline-parse ARGS="--clean --workers 4"` produce los mismos `interventions`/`dlq`
   que `make pipeline-parse ARGS="--clean --workers 1"`, en ~1/4 del tiempo.

## Casos borde

- **Bronze vacio (0 filas):** `len(rows) == 0`, `ProcessPoolExecutor` se crea pero no se submittea
  nada. Resultado: `{"interventions": 0, "dlq": 0}`.
- **Workers > filas:** `ProcessPoolExecutor` maneja esto nativamente — se crean menos procesos que
  workers.
- **Workers = 0 o negativo:** `workers = max(1, workers)` lo fuerza a 1.
- **Error de memoria en worker:** `ProcessPoolExecutor` es robusto ante crashes de worker — el
  `future.result()` levanta la excepcion. Se loggea y se continua con el resto.
- **DuckDB lock durante escritura concurrente:** No aplica — solo el proceso principal escribe.

## No incluido en este feature

- Paralelizar los INSERTs a DuckDB (los workers solo parsean)
- Cambiar el modelo de concurrencia de Bronze o Gold
- Batching de INSERTs (INSERT multiple rows en una sola statement)
- Cambios a la logica de parseo o schemas
