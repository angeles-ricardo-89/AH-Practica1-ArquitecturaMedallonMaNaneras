# Pipeline Services Refactor

## Problema

`cli.py` concentra lógica de pipeline que debería estar en servicios dedicados:
- Creación de conexiones
- Parseo de fechas con DLQ
- Iteración sobre registros
- Construcción de objetos de dominio
- Llamadas a merge/enrichment

Esto hace que `cli.py` sea difícil de testear y de mantener. Cada nuevo comando replica el patrón.

## Solución

Tres servicios con responsabilidad única, inyectando dependencias por constructor.

### IngestService

```python
# backend/src/lakehouse/services/ingest_service.py

class IngestService:
    def __init__(self, settings: Settings, duckdb_conn: DuckDBPyConnection): ...

    def run(self, dry_run: bool = False) -> dict:
        # Retorna {"html_count": N, "records_inserted": N}
```

Mueve la lógica de `cli.py:ingest` + `Ingestor` + `ensure_bronze_table`.

### ParseService

```python
# backend/src/lakehouse/services/parse_service.py

class ParseService:
    def __init__(self, settings: Settings, duckdb_conn: DuckDBPyConnection): ...

    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
    ) -> dict:
        # parse_conference_date + DLQ internos
        # Retorna {"interventions": N, "dlq": N}
```

Mueve la lógica de `cli.py:parse`: leer bronze, parsear fecha, parsear HTML, mergear silver, DLQ.

### EnrichService

```python
# backend/src/lakehouse/services/enrich_service.py

class EnrichService:
    def __init__(self, settings: Settings, duckdb_conn: DuckDBPyConnection, pg_conn_str: str): ...

    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
    ) -> dict:
        # Retorna {"embedded": N, "failed": N, "total": N}
```

Mueve la lógica de `cli.py:enrich`: leer silver, construir InterventionRecords, llamar `enrich_interventions`.

### CLI (`cli.py`)

Cada comando se reduce a:

```python
@pipeline_app.command()
def ingest(dry_run: bool = False, max_articles: int | None = None) -> None:
    service = IngestService(settings=Settings(), duckdb_conn=get_connection(...))
    result = service.run(dry_run=dry_run)
    typer.echo(...)
```

### Dependencias

```
CLI → IngestService → Ingestor, ensure_bronze_table, merge
CLI → ParseService → parse_conference_date, parse_html_to_interventions, merge, insert_dlq_record, ensure_silver_tables
CLI → EnrichService → enrich_interventions, ensure_gold_tables
```

### Pruebas

Cada servicio se testea mockeando sus dependencias externas (DuckDB, conexiones).
Los tests actuales de `test_cli.py` se mantienen pero recortados a solo validar invocación al servicio.

### Archivos a modificar/crear

| Archivo | Acción |
|---------|--------|
| `backend/src/lakehouse/services/ingest_service.py` | Crear |
| `backend/src/lakehouse/services/parse_service.py` | Crear |
| `backend/src/lakehouse/services/enrich_service.py` | Crear |
| `backend/src/lakehouse/cli.py` | Modificar — delegar a servicios |
| `backend/tests/test_services/test_ingest_service.py` | Crear |
| `backend/tests/test_services/test_parse_service.py` | Crear |
| `backend/tests/test_services/test_enrich_service.py` | Crear |
| `backend/tests/test_cli.py` | Modificar — simplificar |
