# Interrupción Graceful de Pipelines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que los pipelines `ingest`/`parse`/`enrich` terminen gracefulmente ante SIGINT/SIGTERM, escribiendo su corrida como `interrupted` con conteos parciales.

**Architecture:** Un flag thread-safe compartido (`interrupt.py`) es seteado por handlers de SIGINT/SIGTERM (1ª señal = cooperativo, 2ª = force-exit). Los loops de trabajo checan el flag entre unidades y drenan lo en vuelo. El CLI decide `ok`/`interrupted`/`error` tras el run. Se agrega `'interrupted'` al CHECK constraint vía ALTER idempotente.

**Tech Stack:** Python 3.13 + typer + signal, PostgreSQL (psycopg), asyncio/ProcessPool/ThreadPool, Vue 3 + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-02-pipeline-graceful-interrupt-design.md`

---

### Task 1: Módulo `interrupt.py` con InterruptState + install_graceful_interrupt

**Files:**
- Create: `backend/src/lakehouse/pipeline/interrupt.py`
- Test: `backend/tests/test_pipeline/test_interrupt.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pipeline/test_interrupt.py`:

```python
from __future__ import annotations

import os
import signal
from unittest.mock import patch

import pytest

from lakehouse.pipeline.interrupt import InterruptState, install_graceful_interrupt, interrupt_state


@pytest.fixture
def clean_state() -> None:
    interrupt_state.reset()
    yield
    interrupt_state.reset()


class TestInterruptState:
    def test_starts_not_requested(self) -> None:
        assert InterruptState().requested() is False

    def test_request_and_reset(self) -> None:
        state = InterruptState()
        state._request()
        assert state.requested() is True
        state.reset()
        assert state.requested() is False


class TestInstallGracefulInterrupt:
    def test_sigterm_sets_flag_then_restores_handler(self, clean_state: None) -> None:
        previous = signal.getsignal(signal.SIGTERM)
        with install_graceful_interrupt():
            os.kill(os.getpid(), signal.SIGTERM)
            assert interrupt_state.requested() is True
        assert signal.getsignal(signal.SIGTERM) is previous

    def test_second_signal_force_exits(self, clean_state: None) -> None:
        with (
            patch("lakehouse.pipeline.interrupt.os._exit") as mock_exit,
            install_graceful_interrupt(),
        ):
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGINT)
        mock_exit.assert_called_once_with(130)

    def test_restores_original_handlers(self) -> None:
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)
        with install_graceful_interrupt():
            pass
        assert signal.getsignal(signal.SIGINT) is previous_int
        assert signal.getsignal(signal.SIGTERM) is previous_term
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline/test_interrupt.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'lakehouse.pipeline.interrupt'`

- [ ] **Step 3: Write the implementation**

`backend/src/lakehouse/pipeline/interrupt.py`:

```python
from __future__ import annotations

import os
import signal
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from lakehouse.log_config import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__, layer="pipeline")


class InterruptState:
    """Flag thread-safe que registra una solicitud cooperativa de interrupcion."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def requested(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()

    def _request(self) -> None:
        self._event.set()


interrupt_state = InterruptState()


def _handler(signum: int, _frame: object) -> None:
    if interrupt_state.requested():
        os._exit(128 + signum)
    interrupt_state._request()


@contextmanager
def install_graceful_interrupt() -> Iterator[None]:
    """Instala handlers de SIGINT/SIGTERM que piden cierre cooperativo.

    Primera senal: setea el flag (los loops drenan y el CLI escribe 'interrupted').
    Segunda senal: fuerza ``os._exit(128 + signum)``.
    """
    previous: dict[int, Callable] = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.getsignal(sig)
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                logger.warning("No se pudo instalar handler de senal", sig=sig)
        yield
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline/test_interrupt.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/interrupt.py backend/tests/test_pipeline/test_interrupt.py
git commit -m "agrega modulo de interrupcion graceful con flag cooperativo"
```

---

### Task 2: Punto de chequeo en `_worker` de ingest (asyncio)

**Files:**
- Modify: `backend/src/lakehouse/pipeline/ingestion.py:41-86`
- Test: `backend/tests/test_pipeline/test_ingestion.py`

- [ ] **Step 1: Write the failing test**

Agregar a `backend/tests/test_pipeline/test_ingestion.py` (imports ya existentes: `AsyncMock, MagicMock, patch`; agregar `from lakehouse.pipeline.interrupt import interrupt_state`):

```python
class TestIngestorInterrupt:
    @pytest.mark.asyncio
    async def test_worker_stops_taking_new_urls_on_interrupt(self):
        with (
            patch(
                "lakehouse.pipeline.ingestion.fetch_article_list",
                return_value=["http://test.com/1", "http://test.com/2"],
            ),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
            patch("lakehouse.db.duckdb_conn.get_connection"),
            patch("lakehouse.db.duckdb_conn.ensure_bronze_table"),
            patch(
                "lakehouse.pipeline.ingestion.insert_bronze_record",
                return_value=True,
            ),
            patch.object(interrupt_state, "requested", side_effect=[False, True]),
        ):
            mock_get.return_value = _mock_response("<html>test</html>")

            ingestor = Ingestor(
                db_path="test.db",
                source_archive_url="http://test.com",
                max_articles=2,
            )
            result = await ingestor.run()

        assert result["records_inserted"] == 1
        assert mock_get.call_count == 1
```

> `side_effect=[False, True]` simula que la señal llega tras la primera URL: el primer chequeo es `False`, el siguiente `True` (rompe el loop). El worker ya descargado termina de escribirse (1 registro), el segundo URL no se toma.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline/test_ingestion.py::TestIngestorInterrupt -v`
Expected: FAIL (el worker procesa ambas URLs → `records_inserted == 2`)

- [ ] **Step 3: Modify `_worker` en `ingestion.py`**

Agregar import: `from lakehouse.pipeline.interrupt import interrupt_state`

Reemplazar el loop de `_worker` (líneas 41-44):

```python
    async def _worker(
        self,
        queue: asyncio.Queue,
        client: httpx.AsyncClient,
        ingestion_run_id: str,
        conn,
        reporter: ProgressReporter,
    ) -> int:
        """Worker to consume URLs from the queue and process them."""
        records_inserted = 0
        while True:
            if interrupt_state.requested():
                break
            url = await queue.get()
            if url is None:
                queue.task_done()
                break
```

> Nota: el `await queue.get()` bloqueante no se toca; el flag se checa ANTES de tomar del queue. Como los workers drenan el URL en vuelo y luego rompen, no hace falta `asyncio.wait_for`. La señal llega al hilo principal (donde corre `asyncio.run`) entre `await`s y el chequeo es reactivo.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline/test_ingestion.py -v`
Expected: PASS (nuevo test + existentes)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/ingestion.py backend/tests/test_pipeline/test_ingestion.py
git commit -m "detiene ingesta bronze al recibir interrupcion cooperativa"
```

---

### Task 3: Puntos de chequeo en `ParseService` (sequential + parallel)

**Files:**
- Modify: `backend/src/lakehouse/services/parse_service.py:131-147` (sequential), `:160-163` (parallel)
- Test: `backend/tests/test_services/test_parse_service.py`

- [ ] **Step 1: Write the failing tests**

Agregar a `backend/tests/test_services/test_parse_service.py` (imports existentes; agregar `from lakehouse.pipeline.interrupt import interrupt_state`):

```python
class TestParseServiceInterrupt:
    def _service(self) -> ParseService:
        return ParseService(settings=Settings(), duckdb_conn=MagicMock())

    def test_run_sequential_stops_on_interrupt(self):
        service = self._service()
        conference = MagicMock()
        intervention = MagicMock()
        rows = [
            ("https://example.com/a", "<html>a</html>"),
            ("https://example.com/b", "<html>b</html>"),
        ]
        with (
            patch(
                "lakehouse.services.parse_service._parse_one_row",
                return_value=(conference, [intervention], []),
            ),
            patch("lakehouse.services.parse_service.merge_conference"),
            patch("lakehouse.services.parse_service.merge_intervention"),
            patch.object(interrupt_state, "requested", side_effect=[False, True]),
        ):
            total_int, total_dlq = service._run_sequential(
                rows=rows,
                write_conn=MagicMock(),
                conference_date=None,
                reporter=MagicMock(),
            )
        assert total_int == 1
        assert total_dlq == 0

    def test_run_parallel_stops_submitting_on_interrupt(self):
        service = self._service()
        future = Future()
        future.set_result((MagicMock(), [MagicMock()], []))
        pool = _FakePool([future])
        rows = [
            ("https://example.com/a", "<html>a</html>"),
            ("https://example.com/b", "<html>b</html>"),
        ]
        with (
            patch("lakehouse.services.parse_service.merge_conference"),
            patch("lakehouse.services.parse_service.merge_intervention"),
            patch.object(interrupt_state, "requested", side_effect=[False, True]),
        ):
            total_int, total_dlq = service._run_parallel(
                rows=rows,
                write_conn=MagicMock(),
                conference_date=None,
                reporter=MagicMock(),
                pool=pool,
            )
        assert total_int == 1
        assert total_dlq == 0
        assert len(pool.submit_calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_services/test_parse_service.py::TestParseServiceInterrupt -v`
Expected: FAIL (procesa ambas filas → `total_int == 2`, `submit_calls == 2`)

- [ ] **Step 3: Modify `parse_service.py`**

Agregar import: `from lakehouse.pipeline.interrupt import interrupt_state`

En `_run_sequential` (línea 131):

```python
        total_interventions = 0
        total_dlq = 0
        for source_url, raw_html in rows:
            if interrupt_state.requested():
                break
            conference, interventions, dlq_records = _parse_one_row(
                source_url, raw_html, conference_date
            )
```

En `_run_parallel` (línea 161):

```python
        futures: dict[Future, tuple[str, str]] = {}
        for source_url, raw_html in rows:
            if interrupt_state.requested():
                break
            future = pool.submit(_parse_one_row, source_url, raw_html, conference_date)
            futures[future] = (source_url, raw_html)
```

> Los futures ya enviados se drenan en el `as_completed` de `_run_parallel`; el `ProcessPoolExecutor.__exit__` (`shutdown(wait=True)`) garantiza que terminen. `_run_with_transaction` hace COMMIT de lo ya mergeado (parcial).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_services/test_parse_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/parse_service.py backend/tests/test_services/test_parse_service.py
git commit -m "detiene parseo silver al recibir interrupcion cooperativa"
```

---

### Task 4: Puntos de chequeo en `enrich_interventions` (sequential + parallel)

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py:296-312` (parallel), `:340-349` (sequential)
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Write the failing tests**

Agregar a `backend/tests/test_pipeline/test_enrichment.py` (imports existentes; agregar `from lakehouse.pipeline.interrupt import interrupt_state`):

```python
class TestEnrichInterrupt:
    def _window(self, i: int, text: str = "Texto de la ventana.") -> WindowRecord:
        return WindowRecord(
            chunk_key=f"conf1_w{i:03d}_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text=text,
            url="https://example.com",
            window_index=i,
        )

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_sequential_stops_on_interrupt(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        with patch.object(interrupt_state, "requested", side_effect=[False, True]):
            result = enrich_interventions(
                windows=[self._window(0), self._window(1)],
                conference_date="2024-10-01",
                pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
                ollama_base_url="http://localhost:11434",
                ollama_model="nomic-embed-text",
            )

        assert result["total"] == 2
        assert result["embedded"] == 1
        assert result["failed"] == 0
        assert mock_embed.call_count == 1

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_parallel_stops_submitting_on_interrupt(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        with patch.object(interrupt_state, "requested", side_effect=[False, True]):
            result = enrich_interventions(
                windows=[self._window(0), self._window(1)],
                conference_date="2024-10-01",
                pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
                ollama_base_url="http://localhost:11434",
                ollama_model="nomic-embed-text",
                workers=2,
            )

        assert result["total"] == 2
        assert result["embedded"] == 1
        assert result["failed"] == 0
        assert mock_embed.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline/test_enrichment.py::TestEnrichInterrupt -v`
Expected: FAIL (procesa ambas ventanas → `embedded == 2`, `mock_embed.call_count == 2`)

- [ ] **Step 3: Modify `enrichment.py`**

Agregar import: `from lakehouse.pipeline.interrupt import interrupt_state`

Rama parallel (línea 296):

```python
                futures: dict[Future, tuple[WindowRecord, str]] = {}
                for record in windows:
                    if interrupt_state.requested():
                        break
                    effective_date = conference_date or record.conference_date
```

Rama sequential (línea 340):

```python
            for record in windows:
                if interrupt_state.requested():
                    break
                effective_date = conference_date or record.conference_date
```

> En parallel, los futures ya enviados se drenan en `as_completed`; `ThreadPoolExecutor.__exit__` (`shutdown(wait=True)`) los espera. El `conn.commit()` final (`:375`) persiste lo ya almacenado en Gold.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline/test_enrichment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "detiene enriquecimiento gold al recibir interrupcion cooperativa"
```

---

### Task 5: Migración de schema — status `interrupted`

**Files:**
- Modify: `backend/src/lakehouse/db/observability_conn.py:5-23`
- Test: `backend/tests/test_pipeline/test_observability_conn.py`

- [ ] **Step 1: Write the failing test**

Agregar a `backend/tests/test_pipeline/test_observability_conn.py`:

```python
    def test_status_constraint_accepts_interrupted(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            ensure_observability_tables(conn_str)
            with psycopg.connect(conn_str) as conn:
                conn.execute(
                    """INSERT INTO observability.pipeline_runs
                    (run_id, capa, status)
                    VALUES ('run-interrupted', 'bronze', 'interrupted')"""
                )
                conn.commit()
                count = conn.execute(
                    "SELECT COUNT(*) FROM observability.pipeline_runs WHERE run_id = %s",
                    ("run-interrupted",),
                ).fetchone()[0]
            assert count == 1
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)

    def test_migrates_existing_constraint(self, conn_str: str) -> None:
        _prepare_gold_rag_corpus(conn_str)
        _drop_observability_schema(conn_str)
        try:
            with psycopg.connect(conn_str) as conn:
                conn.execute("CREATE SCHEMA IF NOT EXISTS observability")
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS observability.pipeline_runs (
                        run_id TEXT PRIMARY KEY,
                        capa TEXT NOT NULL
                             CHECK (capa IN ('bronze', 'silver', 'gold')),
                        status TEXT NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running', 'ok', 'error')),
                        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMPTZ,
                        records_in INTEGER NOT NULL DEFAULT 0,
                        records_out INTEGER NOT NULL DEFAULT 0,
                        dlq_count INTEGER NOT NULL DEFAULT 0,
                        error_message TEXT
                    )"""
                )
                conn.commit()
            ensure_observability_tables(conn_str)
            with psycopg.connect(conn_str) as conn:
                conn.execute(
                    """INSERT INTO observability.pipeline_runs
                    (run_id, capa, status)
                    VALUES ('run-interrupted', 'bronze', 'interrupted')"""
                )
                conn.commit()
        finally:
            _drop_observability_schema(conn_str)
            ensure_observability_tables(conn_str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline/test_observability_conn.py -v`
Expected: FAIL con `psycopg.errors.CheckViolation` (o similar) en `test_status_constraint_accepts_interrupted`

- [ ] **Step 3: Modify `observability_conn.py`**

Actualizar el DDL (bases frescas):

```python
PIPELINE_RUNS_DDL = """
CREATE SCHEMA IF NOT EXISTS observability;

CREATE TABLE IF NOT EXISTS observability.pipeline_runs (
    run_id         TEXT PRIMARY KEY,
    capa           TEXT NOT NULL CHECK (capa IN ('bronze', 'silver', 'gold')),
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'ok', 'error', 'interrupted')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    records_in     INTEGER NOT NULL DEFAULT 0,
    records_out    INTEGER NOT NULL DEFAULT 0,
    dlq_count      INTEGER NOT NULL DEFAULT 0,
    error_message  TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_capa_started
    ON observability.pipeline_runs (capa, started_at DESC);
"""

PIPELINE_RUNS_STATUS_MIGRATION = """
ALTER TABLE observability.pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_status_check;
ALTER TABLE observability.pipeline_runs
    ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN ('running', 'ok', 'error', 'interrupted'));
"""
```

Y en `ensure_observability_tables`:

```python
def ensure_observability_tables(pg_conn_str: str) -> None:
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute(PIPELINE_RUNS_DDL)
        conn.execute(PIPELINE_RUNS_STATUS_MIGRATION)
        conn.execute(EMBEDDING_3D_DDL)
        conn.commit()
```

> El `ALTER` es idempotente: `DROP IF EXISTS` + `ADD` con el mismo nombre canónico
> (`pipeline_runs_status_check`) funciona tanto en bases frescas como existentes. Postgres
> auto-nombra el CHECK de la columna `status` de `pipeline_runs` como `pipeline_runs_status_check`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline/test_observability_conn.py -v`
Expected: PASS (2 nuevos + existentes)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/db/observability_conn.py backend/tests/test_pipeline/test_observability_conn.py
git commit -m "permite estado interrupted en pipeline_runs via migracion idempotente"
```

---

### Task 6: CLI — escribir `interrupted` y exit 130 en `ingest`

**Files:**
- Modify: `backend/src/lakehouse/cli.py:72-107`
- Test: `backend/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Agregar a `backend/tests/test_cli.py` en `TestPipelineRunTracking`:

```python
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.IngestService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_ingest_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run = AsyncMock(return_value={"html_count": 5, "records_inserted": 3})
        result = runner.invoke(app, ["pipeline", "ingest"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 3
        assert interrupted.kwargs["records_out"] == 3
```

Agregar import: `from lakehouse.pipeline.interrupt import interrupt_state`

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestPipelineRunTracking::test_ingest_writes_interrupted_on_interrupt -v`
Expected: FAIL (`exit_code == 0`, `interrupted.args[2] == 'ok'`)

- [ ] **Step 3: Modify `cli.py` — import y comando `ingest`**

Agregar import: `from lakehouse.pipeline.interrupt import install_graceful_interrupt, interrupt_state`

Reemplazar el cuerpo de `ingest` (líneas 78-107):

```python
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="bronze"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "bronze", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    try:
        with install_graceful_interrupt():
            result = asyncio.run(
                service.run(dry_run=dry_run, max_articles=max_articles, clean=clean)
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "bronze", "error", started_at, error_message=str(e))
        raise

    if interrupt_state.requested():
        if not dry_run:
            records = result.get("records_inserted", 0)
            _write_pipeline_run(
                pg_conn_str, "bronze", "interrupted", started_at,
                records_in=records, records_out=records,
            )
        typer.echo("Pipeline interrumpido")
        raise typer.Exit(code=130)

    if dry_run:
        typer.echo(f"Simulacion: {result['html_count']} articulos encontrados")
    else:
        records = result.get("records_inserted", 0)
        _write_pipeline_run(pg_conn_str, "bronze", "ok", started_at, records_in=records, records_out=records)
        typer.echo(f"Ingesta completada: {records} registros insertados")
```

> El `started_at` se calcula ANTES de instalar handlers para no contaminar el run_id determinista.

- [ ] **Step 4: Run full CLI test suite**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (nuevo test + todos los existentes de ingest)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/cli.py backend/tests/test_cli.py
git commit -m "escribe estado interrupted en corridas de ingesta bronze"
```

---

### Task 7: CLI — escribir `interrupted` y exit 130 en `parse` y `enrich`

**Files:**
- Modify: `backend/src/lakehouse/cli.py:110-201`
- Test: `backend/tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Agregar a `backend/tests/test_cli.py` en `TestPipelineRunTracking`:

```python
    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.ParseService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_parse_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"interventions": 4, "dlq": 1}
        result = runner.invoke(app, ["pipeline", "parse"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 4
        assert interrupted.kwargs["records_out"] == 4
        assert interrupted.kwargs["dlq_count"] == 1

    @patch("lakehouse.cli.ensure_observability_tables")
    @patch("lakehouse.cli._write_pipeline_run")
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    @patch.object(interrupt_state, "requested", return_value=True)
    def test_enrich_writes_interrupted_on_interrupt(
        self, mock_interrupt, mock_conn, mock_svc_cls, mock_write, mock_ensure
    ):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 2, "failed": 1, "total": 3}
        result = runner.invoke(app, ["pipeline", "enrich"])
        assert result.exit_code == 130
        assert mock_write.call_count == 2
        running, interrupted = mock_write.call_args_list
        assert running.args[2] == "running"
        assert interrupted.args[2] == "interrupted"
        assert interrupted.kwargs["records_in"] == 3
        assert interrupted.kwargs["records_out"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "interrupted" -v`
Expected: FAIL para parse y enrich

- [ ] **Step 3: Modify `cli.py` — comandos `parse` y `enrich`**

Reemplazar el cuerpo de `parse` (líneas 119-152):

```python
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="silver"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "silver", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = ParseService(settings=settings, duckdb_conn=conn)
    try:
        with install_graceful_interrupt():
            result = service.run(
                dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "silver", "error", started_at, error_message=str(e))
        raise

    if interrupt_state.requested():
        if not dry_run:
            interventions = result.get("interventions", 0)
            _write_pipeline_run(
                pg_conn_str, "silver", "interrupted", started_at,
                records_in=interventions, records_out=interventions,
                dlq_count=result.get("dlq", 0),
            )
        typer.echo("Pipeline interrumpido")
        raise typer.Exit(code=130)

    if not dry_run:
        interventions = result.get("interventions", 0)
        _write_pipeline_run(
            pg_conn_str, "silver", "ok", started_at,
            records_in=interventions, records_out=interventions,
            dlq_count=result.get("dlq", 0),
        )
    typer.echo(f"Parsing completado: {result['interventions']} intervenciones, {result['dlq']} DLQ")
```

Reemplazar el cuerpo de `enrich` (líneas 161-201):

```python
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="gold"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "gold", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = EnrichService(
        settings=settings,
        duckdb_conn=conn,
        pg_conn_str=pg_conn_str,
    )
    try:
        with install_graceful_interrupt():
            result = service.run(
                dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "gold", "error", started_at, error_message=str(e))
        raise

    if interrupt_state.requested():
        if not dry_run:
            _write_pipeline_run(
                pg_conn_str, "gold", "interrupted", started_at,
                records_in=result.get("total", 0), records_out=result.get("embedded", 0),
            )
        typer.echo("Pipeline interrumpido")
        raise typer.Exit(code=130)

    if not dry_run:
        _write_pipeline_run(
            pg_conn_str, "gold", "ok", started_at,
            records_in=result.get("total", 0), records_out=result.get("embedded", 0),
        )
    typer.echo(
        f"Enriquecimiento completado: {result['embedded']} incrustados, "
        f"{result['failed']} fallidos de {result['total']} totales"
    )
```

- [ ] **Step 4: Run full CLI test suite**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/cli.py backend/tests/test_cli.py
git commit -m "escribe estado interrupted en corridas de parseo y enriquecimiento"
```

---

### Task 8: Frontend — mapear `interrupted`, `ok`, `error` en PipelineCard, Timeline y Semaforo

**Files:**
- Modify: `frontend/src/components/pipeline/PipelineCard.vue:13-27`
- Modify: `frontend/src/components/pipeline/PipelineTimeline.vue:47-51`
- Modify: `frontend/src/components/dashboard/SemaforoEstado.vue:9-27`
- Test: `frontend/tests/components/PipelineCard.test.ts`, `frontend/tests/components/SemaforoEstado.test.ts`

- [ ] **Step 1: Write the failing tests**

Agregar a `frontend/tests/components/PipelineCard.test.ts`:

```ts
  it('handles interrupted status', () => {
    const interruptedLayer: LayerRun = {
      ...bronzeLayer,
      status: 'interrupted',
    }
    const wrapper = mount(PipelineCard, {
      props: { layer: interruptedLayer },
    })
    expect(wrapper.text()).toContain('Interrumpido')
    const badge = wrapper.find('.bg-amber-100')
    expect(badge.exists()).toBe(true)
  })

  it('maps backend ok status to Completo', () => {
    const okLayer: LayerRun = { ...bronzeLayer, status: 'ok' }
    const wrapper = mount(PipelineCard, { props: { layer: okLayer } })
    expect(wrapper.text()).toContain('Completo')
    const badge = wrapper.find('.bg-green-100')
    expect(badge.exists()).toBe(true)
  })

  it('maps backend error status to Falló', () => {
    const errorLayer: LayerRun = { ...bronzeLayer, status: 'error' }
    const wrapper = mount(PipelineCard, { props: { layer: errorLayer } })
    expect(wrapper.text()).toContain('Falló')
    const badge = wrapper.find('.bg-red-100')
    expect(badge.exists()).toBe(true)
  })
```

Agregar a `frontend/tests/components/SemaforoEstado.test.ts`:

```ts
  it('shows amber dot for interrupted status', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'interrupted' },
    })
    expect(wrapper.find('.bg-amber-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('Interrumpido')
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm test:unit -- PipelineCard SemaforoEstado`
Expected: FAIL (labels raw `interrupted`/`ok`/`error`, sin clase ámbar)

- [ ] **Step 3: Modify los tres componentes**

`PipelineCard.vue` — reemplazar `statusLabel` y `statusClass`:

```ts
const statusLabel = computed(() => {
  const s = props.layer.status
  if (s === 'running' || s === 'En curso') return 'En curso'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'Completo'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'Falló'
  if (s === 'interrupted') return 'Interrumpido'
  return s || 'sin datos'
})

const statusClass = computed(() => {
  const s = props.layer.status
  if (s === 'running' || s === 'En curso') return 'bg-blue-100 text-blue-700 border-blue-200'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'bg-green-100 text-green-700 border-green-200'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'bg-red-100 text-red-700 border-red-200'
  if (s === 'interrupted') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-stone-100 text-stone-500 border-stone-200'
})
```

`PipelineTimeline.vue` — reemplazar el `:class` del punto (líneas 46-51):

```ts
            :class="{
              'border-blue-600': layer.status === 'running' || layer.status === 'En curso',
              'border-green-600': layer.status === 'ok' || layer.status === 'complete' || layer.status === 'Completo',
              'border-red-600': layer.status === 'error' || layer.status === 'failed' || layer.status === 'Falló',
              'border-amber-500': layer.status === 'interrupted',
              'border-stone-300': !['running', 'En curso', 'ok', 'complete', 'Completo', 'error', 'failed', 'Falló', 'interrupted'].includes(layer.status),
            }"
```

`SemaforoEstado.vue` — reemplazar maps:

```ts
const colorMap: Record<string, string> = {
  ok: 'bg-green-500',
  running: 'bg-yellow-500',
  error: 'bg-red-500',
  interrupted: 'bg-amber-500',
  unknown: 'bg-gray-400',
}
```

```ts
  const labelMap: Record<string, string> = {
    ok: 'OK',
    running: 'Ejecutando',
    error: 'Error',
    interrupted: 'Interrumpido',
    unknown: 'Desconocido',
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm test:unit -- PipelineCard SemaforoEstado`
Expected: PASS

- [ ] **Step 5: Run lint y typecheck**

Run: `pnpm lint && pnpm typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/pipeline/PipelineCard.vue frontend/src/components/pipeline/PipelineTimeline.vue frontend/src/components/dashboard/SemaforoEstado.vue frontend/tests/components/PipelineCard.test.ts frontend/tests/components/SemaforoEstado.test.ts
git commit -m "mapea estados ok error e interrupted en dashboard observabilidad"
```

---

### Task 9: Actualizar IMPLEMENTATION_PLAN.md y verificación final de gates

**Files:**
- Modify: `IMPLEMENTATION_PLAN.md`

- [ ] **Step 1: Documentar el checkpoint CP-16 en `IMPLEMENTATION_PLAN.md`**

Agregar después del CP-15 (Fase 5) una sección nueva:

```markdown
### FASE 6: Interrupcion Graceful

#### CP-16: Interrupcion Graceful de Pipelines

**Objetivo:** Que ingest/parse/enrich terminen gracefulmente ante SIGINT/SIGTERM,
escribiendo su corrida como `interrupted` con conteos parciales.

**Archivos:**
- `backend/src/lakehouse/pipeline/interrupt.py` (nuevo)
- `backend/src/lakehouse/cli.py`
- `backend/src/lakehouse/db/observability_conn.py`
- `backend/src/lakehouse/pipeline/ingestion.py`, `parse_service.py`, `enrichment.py`
- `frontend/src/components/pipeline/PipelineCard.vue`, `PipelineTimeline.vue`
- `frontend/src/components/dashboard/SemaforoEstado.vue`

**Evidencia Requerida:**
- `uv run pytest -xvs --cov=src --cov-report=term-missing` pasa (>= 90% coverage).
- `uv run ruff check --fix && uv run ruff format` sin errores.
- `uv run ty check` sin errores.
- `pnpm lint`, `pnpm typecheck`, `pnpm test:unit` pasan.
- Manual: `Ctrl+C` durante `pipeline ingest` escribe `status='interrupted'` con parciales y exit 130.
```

Y agregar la fila al `Resumen de Checkpoints`:

```markdown
| CP-16 | Cierre | Interrupcion Graceful de Pipelines | [ ] |
```

- [ ] **Step 2: Verificación completa de gates backend**

Run (desde `backend/`):
```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
uv run pytest -xvs --cov=src --cov-report=term-missing
```
Expected: ruff sin errores, ty sin errores, pytest con coverage >= 90% y 0 fallos.

- [ ] **Step 3: Verificación completa de gates frontend**

Run (desde `frontend/`):
```bash
pnpm lint
pnpm typecheck
pnpm test:unit
```
Expected: todos sin errores.

- [ ] **Step 4: Verificación manual de idempotencia tras interrupción**

Run: `python -m lakehouse pipeline ingest --max-articles 1` (completar), luego interrumpir uno
a mitad (`Ctrl+C`), luego re-ejecutar. Verificar en la tabla `observability.pipeline_runs`
que la corrida interrumpida quedó `interrupted` con `records_in/out` parciales y que la
reejecución posterior no duplica (MERGE upsert con claves deterministas).

- [ ] **Step 5: Commit**

```bash
git add IMPLEMENTATION_PLAN.md
git commit -m "documenta checkpoint CP-16 de interrupcion graceful"
```

---

## Self-Review

**Spec coverage:**
- §4.1 módulo interrupt.py → Task 1 ✓
- §4.2 loops ingest/parse/enrich → Tasks 2-4 ✓
- §4.3 CLI `interrupted` + exit 130 → Tasks 6-7 ✓
- §4.4 migración schema → Task 5 ✓
- §4.5 frontend + drive-by fix ok/error → Task 8 ✓
- §5 health_global sin cambios (Degraded) ✓ (no requiere tarea; verificado en revisión)
- §6 casos borde → cubiertos por tests (double signal Task 1, dry_run conservado, PG down best-effort ya existente)
- §7 tests → Tasks 1-5, 8 ✓
- CP-16 + gates → Task 9 ✓

**Placeholders:** ninguno; cada step incluye código completo.

**Type consistency:** `interrupt_state.requested()` usado uniformemente en tasks 2-7; `install_graceful_interrupt` importado en cli; `_write_pipeline_run` firma intacta; clases de test reutilizan fixtures/patrones existentes.
