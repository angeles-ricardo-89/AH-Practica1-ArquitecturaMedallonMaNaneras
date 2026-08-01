# Batching de Escrituras DuckDB en Silver con Single Transaction

## Problema

`merge.py` ejecuta cada `INSERT OR IGNORE` como una sentencia auto-commit sobre un archivo DuckDB
en ext4. Cada commit independiente cuesta ~42ms (sync a disco), y cada conferencia genera ~40
escrituras (1 conference + ~39 interventions). Resultado: ~1.7s de escritura por row, dominando
totalmente el tiempo del pipeline Silver.

Medido sobre `ducklake_files.duckdb` (ext4):

```
auto-commit:  400 writes en 16.85s = 42.1ms/write
single tx:    400 writes en 0.92s  = 2.3ms/write   (~18x mas rapido)
```

Para 933 rows de Bronze (~40 escrituras/row) el pipeline tarda ~35 min, de los cuales ~86% es
escritura auto-commit y ~1% es parseo. El fix de escrituras es el cuello de botella real.

## Solucion

Envolver la fase de escritura de `ParseService.run()` en una sola transaccion
`BEGIN TRANSACTION ... COMMIT`, con `ROLLBACK` ante excepcion. Todos los INSERTs de
conferencias, intervenciones y DLQ de un run comparten un unico commit.

## Diseno

### 1. Restructurar `run()` con helper `_run_with_transaction`

En `backend/src/lakehouse/services/parse_service.py`, el bloque `if rows:` actual crea `write_conn`
por separado en cada branch (paralelo y secuencial) con su propio `try/finally`. Se extrae un helper
`_run_with_transaction(dispatch, dry_run)` que abre `write_conn`, inicia la transaccion, despacha
via callback, hace COMMIT/ROLLBACK y cierra la conexion:

```python
def _run_with_transaction(
    self,
    dispatch: Callable[[duckdb.DuckDBPyConnection | None], tuple[int, int]],
    dry_run: bool,
) -> tuple[int, int]:
    write_conn = None
    if not dry_run:
        write_conn = get_connection(self._settings.ducklake_data_path)
        write_conn.execute("BEGIN TRANSACTION")
    try:
        result = dispatch(write_conn)
        if write_conn is not None:
            write_conn.execute("COMMIT")
        return result
    except Exception:
        if write_conn is not None:
            write_conn.execute("ROLLBACK")
        raise
    finally:
        if write_conn is not None:
            write_conn.close()
```

Y `run()` usa el helper en cada branch:

```python
if rows:
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            total_interventions, total_dlq = self._run_with_transaction(
                lambda wc: self._run_parallel(
                    rows=rows,
                    write_conn=wc,
                    conference_date=conference_date,
                    reporter=reporter,
                    pool=pool,
                ),
                dry_run=dry_run,
            )
    else:
        total_interventions, total_dlq = self._run_with_transaction(
            lambda wc: self._run_sequential(
                rows=rows,
                write_conn=wc,
                conference_date=conference_date,
                reporter=reporter,
            ),
            dry_run=dry_run,
        )
```

**Notas:**
- **Fork-safety:** en Linux fork, `ProcessPoolExecutor` fork-ea los workers de forma lazy en el
  primer `submit()`, que ocurre despues de que `_run_with_transaction` abrio `write_conn`. Los
  workers heredan el file descriptor de DuckDB, pero NUNCA lo usan: `_parse_one_row` es una funcion
  pura sin acceso a conexiones. La seguridad no depende de que el pool se cree antes de la conexion,
  sino de la invariante "los workers nunca tocan DuckDB". Documentar esta invariante como requisito
  permanente.
- `dry_run` → `_run_with_transaction` recibe `dry_run=True`, no abre conexion, no inicia
  transaccion, y `dispatch` recibe `write_conn=None` (los paths ya saben no escribir).
- El `except Exception` hace `ROLLBACK` y re-lanza, preservando atomicidad todo-o-nada.
- `dispatch` es un `Callable` que se ejecuta solo en el proceso principal (no se picklea ni se
  envia a workers). Los closures capturan `rows`, `conference_date`, `reporter`, `pool`.

### 2. Sin cambios en `merge.py`, schemas, CLI ni worker function

- `merge_intervention`, `merge_conference`, `insert_dlq_record` siguen haciendo su `INSERT`
  individual; ahora todos caen dentro de la misma transaccion.
- `_run_sequential` y `_run_parallel` no cambian: reciben `write_conn` y escriben igual que hoy.
- `INSERT OR IGNORE` dentro de una transaccion preserva la semantica de idempotencia (el conflict
  check se mantiene).
- Los inserts de DLQ van en la misma transaccion (coherentes con el resto del run).

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/services/parse_service.py` | + helper `_run_with_transaction(dispatch, dry_run)`, `run()` lo usa en ambos branches |
| `backend/tests/test_services/test_parse_service.py` | Tests: transaccion se inicia, COMMIT en exito, ROLLBACK en excepcion, dry_run no abre transaccion |

## Verificacion

1. `ruff check --fix && ruff format` en archivos modificados
2. `uv run pyright src/` sin errores
3. `uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90` (coverage >= 90%)
4. Manual: `make pipeline-parse ARGS="--clean --workers 4"` reduce el tiempo de ~35 min a ~90s
   para 933 rows, con los mismos `interventions`/`dlq`.

## Casos borde

- **Bronze vacio (0 filas):** `if rows:` es falso, no se abre `write_conn` ni se inicia transaccion.
  Resultado `{"interventions": 0, "dlq": 0}`.
- **dry_run:** `write_conn is None`, no hay transaccion, no hay escrituras.
- **Excepcion a mitad del dispatch (worker error o INSERT fallido):** `ROLLBACK` descarta TODO el
  run; no quedan escrituras parciales. Re-ejecutar es seguro (idempotente).
- **COMMIT exitoso:** todas las escrituras del run quedan persistidas atomicamente.
- **Excepcion en `BEGIN` o antes de `try`:** propagada, sin efectos (write_conn cerrado en finally).

## No incluido en este feature

- Batching multi-row (`INSERT INTO ... VALUES (...), (...)`) — deja el auto-commit resuelto; si se
  requiere mas rendimiento seria un feature futuro.
- Cambios al modelo de concurrencia de Bronze o Gold
- Cambios a la logica de parseo, schemas o CLI
