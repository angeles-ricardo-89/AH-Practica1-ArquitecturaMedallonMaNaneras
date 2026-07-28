# Pipeline Services Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract pipeline logic from `cli.py` into `IngestService`, `ParseService`, `EnrichService` classes in `services/`.

**Architecture:** Each service receives dependencies (Settings, DuckDB connection, pg connection string) via constructor. CLI commands instantiate the service and call `run()`, which returns a metrics dict. Los servicios se testean con mocks de conexiones y pipeline functions.

**Tech Stack:** Python 3.13, structlog, DuckDB, psycopg, typer

**Convenciones:** Commits en español imperativo. Tests con pytest + unittest.mock.

---

### Task 0: Preparar directorio de tests

**Files:**
- Create: `backend/tests/test_services/__init__.py` (vacio)

- [ ] **Step 1: Crear __init__.py**

```bash
mkdir -p backend/tests/test_services
touch backend/tests/test_services/__init__.py
```

- [ ] **Step 2: Commit**

```bash
git add backend/tests/test_services/__init__.py
git commit -m "chore: prepara directorio test_services"
```

### Task 1: Crear IngestService

**Files:**
- Create: `backend/src/lakehouse/services/ingest_service.py`
- Create: `backend/tests/test_services/test_ingest_service.py`

- [ ] **Step 1: Escribir tests que fallan**

```python
# tests/test_services/test_ingest_service.py
from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.ingest_service import IngestService


class TestIngestService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        service = IngestService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert isinstance(result, dict)
        assert "html_count" in result
        assert "records_inserted" in result

    def test_run_no_dry_run_ensures_table_and_inserts(self):
        settings = Settings()
        conn = MagicMock()
        service = IngestService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.ingest_service.ensure_bronze_table") as mock_ensure,
            patch("lakehouse.services.ingest_service.Ingestor") as mock_ingestor_cls,
        ):
            mock_ingestor = mock_ingestor_cls.return_value
            mock_ingestor.run.return_value = {"html_count": 3, "records_inserted": 3}
            result = service.run(dry_run=False)
        assert result["records_inserted"] == 3
        mock_ensure.assert_called_once_with(conn)
        mock_ingestor.run.assert_called_once_with(dry_run=False)
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

Run: `uv run pytest tests/test_services/test_ingest_service.py -v`
Expected: FAIL con `ImportError: No module named 'lakehouse.services.ingest_service'`

- [ ] **Step 3: Escribir implementacion de IngestService**

```python
# src/lakehouse/services/ingest_service.py
from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import ensure_bronze_table
from lakehouse.log_config import get_logger
from lakehouse.pipeline.ingestion import Ingestor


class IngestService:
    def __init__(self, settings: Settings, duckdb_conn):
        self._settings = settings
        self._conn = duckdb_conn
        self._logger = get_logger(__name__, layer="service")

    def run(self, dry_run: bool = False, max_articles: int | None = None) -> dict:
        self._logger.info("Ejecutando ingesta Bronze", dry_run=dry_run)
        if not dry_run:
            ensure_bronze_table(self._conn)
        ingestor = Ingestor(
            db_path=self._settings.ducklake_data_path,
            source_archive_url=self._settings.source_archive_url,
            max_articles=max_articles,
        )
        result = ingestor.run(dry_run=dry_run)
        self._logger.info("Ingesta Bronze finalizada", **result)
        return result
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Run: `uv run pytest tests/test_services/test_ingest_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/ingest_service.py backend/tests/test_services/test_ingest_service.py
git commit -m "feat: crea IngestService"
```

### Task 2: Crear ParseService

**Files:**
- Create: `backend/src/lakehouse/services/parse_service.py`
- Create: `backend/tests/test_services/test_parse_service.py`

- [ ] **Step 1: Escribir tests que fallan**

```python
# tests/test_services/test_parse_service.py
from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.parse_service import ParseService
from lakehouse.schemas.silver import DLQRejectRecord, InterventionRecord


class TestParseService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert result == {"interventions": 0, "dlq": 0}

    def test_run_with_data_returns_counts(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse:
            mock_parse.return_value = [
                InterventionRecord(
                    intervention_key="k_000_abc", conference_id="cid",
                    participant="P", text="t", chunk_index=0, url="u",
                ),
            ]
            result = service.run(dry_run=True)
        assert result["interventions"] == 1
        assert result["dlq"] == 0

    def test_unknown_date_sends_to_dlq(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/no-date", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.parse_conference_date") as mock_date:
            mock_date.return_value = None
            result = service.run(dry_run=True)
        assert result["interventions"] == 0
        assert result["dlq"] == 1

    def test_run_no_dry_run_calls_merge(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.parse_html_to_interventions") as mock_parse,
            patch("lakehouse.services.parse_service.build_conference_record") as mock_build,
            patch("lakehouse.services.parse_service.merge_conference") as mock_merge_conf,
            patch("lakehouse.services.parse_service.merge_intervention") as mock_merge_int,
            patch("lakehouse.services.parse_service.ensure_silver_tables") as mock_ensure,
        ):
            mock_parse.return_value = [
                InterventionRecord(
                    intervention_key="k_000_abc", conference_id="cid",
                    participant="P", text="t", chunk_index=0, url="u",
                ),
            ]
            mock_build.return_value = MagicMock()
            result = service.run(dry_run=False)
        assert result["interventions"] == 1
        mock_ensure.assert_called_once()
        mock_merge_conf.assert_called_once()
        mock_merge_int.assert_called_once()
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

Run: `uv run pytest tests/test_services/test_parse_service.py -v`
Expected: FAIL con import error

- [ ] **Step 3: Escribir implementacion de ParseService**

```python
# src/lakehouse/services/parse_service.py
import hashlib

from lakehouse.config import Settings
from lakehouse.db.merge import ensure_silver_tables, insert_dlq_record, merge_conference, merge_intervention
from lakehouse.log_config import get_logger
from lakehouse.pipeline.parsing import build_conference_record, parse_conference_date, parse_html_to_interventions
from lakehouse.schemas.silver import DLQRejectRecord


class ParseService:
    def __init__(self, settings: Settings, duckdb_conn):
        self._settings = settings
        self._conn = duckdb_conn
        self._logger = get_logger(__name__, layer="service")

    def run(self, dry_run: bool = False, conference_date: str | None = None) -> dict:
        if not dry_run:
            ensure_silver_tables(self._conn)
        rows = self._conn.execute(
            "SELECT source_url, raw_html FROM bronze.raw_html"
        ).fetchall()
        total_interventions = 0
        total_dlq = 0
        self._logger.info("Iniciando parseo Silver", html_count=len(rows))
        for source_url, raw_html in rows:
            date = conference_date or parse_conference_date(raw_html, source_url)
            if date is None:
                conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
                dlq = DLQRejectRecord(
                    source_record_id=conference_id,
                    rejection_reason="unknown_date",
                    raw_data=source_url,
                )
                if not dry_run:
                    insert_dlq_record(self._conn, dlq)
                total_dlq += 1
                self._logger.warning(
                    "Fecha desconocida, articulo enviado a DLQ", source_url=source_url
                )
                continue
            records = parse_html_to_interventions(
                raw_html=raw_html, source_url=source_url, conference_date=date,
            )
            if not dry_run:
                conference = build_conference_record(
                    source_url=source_url, conference_date=date, raw_html=raw_html,
                )
                merge_conference(self._conn, conference)
            for record in records:
                if not dry_run:
                    if isinstance(record, DLQRejectRecord):
                        self._logger.warning("Registro rechazado, insertando en DLQ", record=record)
                        insert_dlq_record(self._conn, record)
                        total_dlq += 1
                    else:
                        merge_intervention(self._conn, record)
                        total_interventions += 1
                elif isinstance(record, DLQRejectRecord):
                    total_dlq += 1
                else:
                    total_interventions += 1
        self._logger.info(
            "Parseo Silver completado", interventions=total_interventions, dlq=total_dlq,
        )
        return {"interventions": total_interventions, "dlq": total_dlq}
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Run: `uv run pytest tests/test_services/test_parse_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/parse_service.py backend/tests/test_services/test_parse_service.py
git commit -m "feat: crea ParseService"
```

### Task 3: Crear EnrichService

**Files:**
- Create: `backend/src/lakehouse/services/enrich_service.py`
- Create: `backend/tests/test_services/test_enrich_service.py`

- [ ] **Step 1: Escribir tests que fallan**

```python
# tests/test_services/test_enrich_service.py
from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.services.enrich_service import EnrichService
from lakehouse.schemas.silver import InterventionRecord


class TestEnrichService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = EnrichService(
            settings=settings, duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        result = service.run(dry_run=True)
        assert result["total"] == 0

    def test_run_no_dry_run_calls_enrich(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("k1", "c1", "P", "t", "", 0, "https://example.com"),
        ]
        service = EnrichService(
            settings=settings, duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables") as mock_ensure,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(dry_run=False)
        assert result["embedded"] == 1
        mock_ensure.assert_called_once()
        mock_enrich.assert_called_once()
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

Run: `uv run pytest tests/test_services/test_enrich_service.py -v`
Expected: FAIL

- [ ] **Step 3: Escribir implementacion de EnrichService**

```python
# src/lakehouse/services/enrich_service.py
from datetime import UTC, datetime

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import enrich_interventions, ensure_gold_tables
from lakehouse.schemas.silver import InterventionRecord


class EnrichService:
    def __init__(self, settings: Settings, duckdb_conn, pg_conn_str: str):
        self._settings = settings
        self._conn = duckdb_conn
        self._pg_conn_str = pg_conn_str
        self._logger = get_logger(__name__, layer="service")

    def run(self, dry_run: bool = False, conference_date: str | None = None) -> dict:
        rows = self._conn.execute(
            "SELECT intervention_key, conference_id, participant, text, "
            "pregunta_activa, chunk_index, url "
            "FROM silver.interventions"
        ).fetchall()
        self._conn.close()

        interventions = [
            InterventionRecord(
                intervention_key=r[0], conference_id=r[1], participant=r[2],
                text=r[3], pregunta_activa=r[4], chunk_index=r[5], url=r[6],
            )
            for r in rows
        ]

        if not interventions:
            self._logger.warning("No hay intervenciones en Silver para enriquecer")
            return {"embedded": 0, "failed": 0, "total": 0}

        if dry_run:
            self._logger.info(
                "Simulacion: intervenciones listas para Gold", cantidad=len(interventions),
            )
            return {"embedded": 0, "failed": 0, "total": len(interventions)}

        date = conference_date or str(datetime.now(UTC).date())
        self._logger.info(
            "Iniciando enriquecimiento Gold",
            intervenciones=len(interventions), conference_date=date,
        )
        ensure_gold_tables(self._pg_conn_str)
        result = enrich_interventions(
            interventions=interventions,
            conference_date=date,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
        )
        return result
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

Run: `uv run pytest tests/test_services/test_enrich_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/enrich_service.py backend/tests/test_services/test_enrich_service.py
git commit -m "feat: crea EnrichService"
```

### Task 4: Refactorizar CLI para usar servicios

**Files:**
- Modify: `backend/src/lakehouse/cli.py`

**Contexto:** `cli.py` actualmente importa `hashlib`, `datetime`, `DLQRejectRecord`, `InterventionRecord`, `build_conference_record`, `parse_html_to_interventions`, `ensure_silver_tables`, `insert_dlq_record`, `merge_conference`, `merge_intervention`, `Ingestor`. Tras el refactor, todos esos imports sobran y se reemplazan por los 3 servicios.

- [ ] **Step 1: Reescribir cli.py**

```python
import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.log_config import get_logger
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.services.enrich_service import EnrichService
from lakehouse.services.ingest_service import IngestService
from lakehouse.services.parse_service import ParseService

logger = get_logger(__name__, layer="cli")
app = typer.Typer()
pipeline_app = typer.Typer()
app.add_typer(pipeline_app, name="pipeline", help="Pipeline commands")


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    result = service.run(dry_run=dry_run, max_articles=max_articles)
    if dry_run:
        typer.echo(f"Simulacion: {result['html_count']} articulos encontrados")
    else:
        typer.echo(f"Ingesta completada: {result['records_inserted']} registros insertados")


@pipeline_app.command()
def parse(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(
        None, "--date", help="Conference date (default: from data)"
    ),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    service = ParseService(settings=settings, duckdb_conn=conn)
    result = service.run(dry_run=dry_run, conference_date=conference_date)
    typer.echo(
        f"Parsing completado: {result['interventions']} intervenciones, {result['dlq']} DLQ"
    )


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(None, "--date", help="Conference date"),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    pg_conn_str = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    service = EnrichService(
        settings=settings, duckdb_conn=conn, pg_conn_str=pg_conn_str,
    )
    result = service.run(dry_run=dry_run, conference_date=conference_date)
    typer.echo(
        f"Enriquecimiento completado: {result['embedded']} incrustados, "
        f"{result['failed']} fallidos de {result['total']} totales"
    )


@app.command()
def evaluate_rag() -> None:
    logger.info("Iniciando evaluacion RAG (LLM-as-a-Judge)")
    result = evaluate_rag_fn()
    if result.get("status") == "error":
        logger.error("Evaluacion RAG fallo", message=result.get("message"))
        typer.echo(f"RAG Evaluation failed: {result.get('message', 'unknown error')}")
        raise typer.Exit(code=1)
    logger.info(
        "Evaluacion RAG completada",
        total=result["total"],
        fidelidad=result["avg_fidelity"],
        relevancia=result["avg_relevance"],
    )
    typer.echo(
        f"RAG Evaluation: {result['total']} preguntas, "
        f"fidelidad={result['avg_fidelity']}%, "
        f"relevancia={result['avg_relevance']}%"
    )
```

- [ ] **Step 2: Verificar que el CLI responde**

Run: `uv run python -m lakehouse.cli --help`
Expected: Muestra comandos pipeline y evaluate-rag

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/cli.py
git commit -m "refactor: cli delega logica a servicios"
```

### Task 5: Simplificar tests de CLI

**Files:**
- Modify: `backend/tests/test_cli.py`

**Contexto:** Los tests actuales mockean conexiones y pipeline functions directamente. Ahora solo necesitan verificar que el servicio correcto se instancia y llama con los parámetros correctos.

- [ ] **Step 1: Reescribir test_cli.py**

```python
from unittest.mock import patch

from typer.testing import CliRunner

from lakehouse.cli import app

runner = CliRunner()


class TestPipelineIngest:
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"html_count": 5, "records_inserted": 0}
        result = runner.invoke(app, ["pipeline", "ingest", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, max_articles=None)

    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    def test_ingest_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"html_count": 5, "records_inserted": 5}
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, max_articles=None)


class TestPipelineParse:
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None)

    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    def test_parse_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None)

    @patch("lakehouse.cli.get_connection")
    @patch("lakehouse.cli.ParseService")
    def test_parse_with_date(self, mock_svc_cls, mock_conn):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 0, "dlq": 0}
        result = runner.invoke(app, ["pipeline", "parse", "--date", "2024-10-01"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date="2024-10-01")


class TestPipelineEnrich:
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 0, "failed": 0, "total": 0}
        result = runner.invoke(app, ["pipeline", "enrich", "--dry-run"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None)

    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_no_dry_run(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None)
```

- [ ] **Step 2: Ejecutar tests de CLI**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_cli.py
git commit -m "test: simplifica tests de CLI para usar servicios"
```

### Task 6: Suite completa de verificacion

- [ ] **Step 1: Ejecutar ruff check**

Run: `uv run ruff check --fix`
Expected: 0 errores (solo pre-existing TRY400 en rag_search.py)

- [ ] **Step 2: Ejecutar tests de servicios nuevos**

Run: `uv run pytest tests/test_services/ -v`
Expected: Todos PASS

- [ ] **Step 3: Ejecutar tests completos**

Run: `uv run pytest -xvs tests/`
Expected: Todos PASS

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "chore: verificacion final post refactor"
```
