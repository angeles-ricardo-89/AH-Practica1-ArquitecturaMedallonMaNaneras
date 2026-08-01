# Silver ProcessPoolExecutor Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--workers` flag to `pipeline parse` using `ProcessPoolExecutor` so Silver HTML parsing runs in parallel processes, with writes serialized on the main process.

**Architecture:** Main process reads all Bronze rows into memory, dispatches parsing to worker processes via `ProcessPoolExecutor`, collects results via `as_completed()`, and writes to DuckDB sequentially on a fresh connection. Workers never touch DuckDB.

**Tech Stack:** Python 3.13, `concurrent.futures.ProcessPoolExecutor`, Pydantic v2 pickleable models, DuckDB, Typer CLI.

---

### Task 1: Add `_parse_one_row` worker function and refactor `ParseService.run()`

**Files:**
- Modify: `backend/src/lakehouse/services/parse_service.py`

- [ ] **Step 1: Add imports for `ProcessPoolExecutor`**

At the top of the file, alongside existing imports:

```python
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
```

- [ ] **Step 2: Add `_parse_one_row` at module level (outside the class)**

Place after imports, before the `ParseService` class:

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

    records = parse_html_to_interventions(raw_html=raw_html, source_url=source_url, conference_date=date)
    conference = build_conference_record(source_url=source_url, conference_date=date, raw_html=raw_html)
    interventions = [r for r in records if isinstance(r, InterventionRecord)]
    dlq = [r for r in records if isinstance(r, DLQRejectRecord)]
    return conference, interventions, dlq
```

- [ ] **Step 3: Add `workers` parameter to `run()`**

Change `run()` signature:

```python
def run(
    self,
    dry_run: bool = False,
    conference_date: str | None = None,
    clean: bool = False,
    workers: int = 1,
) -> dict:
```

- [ ] **Step 4: Refactor `run()` — both paths use `_parse_one_row`, writes on fresh connection**

Replace the entire `run()` method body with:

```python
def run(
    self,
    dry_run: bool = False,
    conference_date: str | None = None,
    clean: bool = False,
    workers: int = 1,
) -> dict:
    workers = max(1, workers)

    if clean:
        if dry_run:
            self._logger.warning("--clean es ignorado en dry-run")
        else:
            drop_silver_tables(self._conn)
    if not dry_run:
        ensure_silver_tables(self._conn)

    rows = self._conn.execute("SELECT source_url, raw_html FROM bronze.raw_html").fetchall()
    self._conn.close()

    total_interventions = 0
    total_dlq = 0
    self._logger.info("Iniciando parseo Silver", html_count=len(rows), workers=workers)
    reporter = ProgressReporter(total=len(rows), label="silver")

    if rows:
        write_conn = None
        if not dry_run:
            write_conn = get_connection(self._settings.ducklake_data_path)
        try:
            if workers > 1:
                total_interventions, total_dlq = self._run_parallel(
                    rows=rows, write_conn=write_conn, conference_date=conference_date,
                    reporter=reporter, workers=workers
                )
            else:
                total_interventions, total_dlq = self._run_sequential(
                    rows=rows, write_conn=write_conn, conference_date=conference_date, reporter=reporter
                )
        finally:
            if write_conn is not None:
                write_conn.close()

    reporter.finish()
    self._logger.info(
        "Parseo Silver completado",
        interventions=total_interventions,
        dlq=total_dlq,
    )
    return {"interventions": total_interventions, "dlq": total_dlq}
```

- [ ] **Step 5: Add `_run_sequential` method to `ParseService`**

```python
def _run_sequential(
    self,
    rows: list[tuple[str, str]],
    write_conn,
    conference_date: str | None,
    reporter: ProgressReporter,
) -> tuple[int, int]:
    total_interventions = 0
    total_dlq = 0
    for source_url, raw_html in rows:
        conference, interventions, dlq_records = _parse_one_row(source_url, raw_html, conference_date)
        if write_conn is not None:
            if conference is not None:
                merge_conference(write_conn, conference)
            for record in interventions:
                merge_intervention(write_conn, record)
        for dlq in dlq_records:
            if write_conn is not None:
                insert_dlq_record(write_conn, dlq)
        total_interventions += len(interventions)
        total_dlq += len(dlq_records)
        if conference is None:
            total_dlq += 1
        reporter.tick()
    return total_interventions, total_dlq
```

- [ ] **Step 6: Add `_run_parallel` method to `ParseService`**

```python
def _run_parallel(
    self,
    rows: list[tuple[str, str]],
    write_conn,
    conference_date: str | None,
    reporter: ProgressReporter,
    workers: int,
) -> tuple[int, int]:
    total_interventions = 0
    total_dlq = 0

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures: dict[Future, tuple[str, str]] = {}
        for source_url, raw_html in rows:
            future = pool.submit(_parse_one_row, source_url, raw_html, conference_date)
            futures[future] = (source_url, raw_html)

        for future in as_completed(futures):
            conference, interventions, dlq_records = future.result()
            if write_conn is not None:
                if conference is not None:
                    merge_conference(write_conn, conference)
                for record in interventions:
                    merge_intervention(write_conn, record)
            for dlq in dlq_records:
                if write_conn is not None:
                    insert_dlq_record(write_conn, dlq)

            total_interventions += len(interventions)
            total_dlq += len(dlq_records)
            if conference is None:
                total_dlq += 1
            reporter.tick()

    return total_interventions, total_dlq
```



- [ ] **Step 7: Add `get_connection` import**

Add to existing imports from `lakehouse.db.duckdb_conn`:

At the top, find the line:
```python
from lakehouse.db.merge import (
```
and add above it:
```python
from lakehouse.db.duckdb_conn import get_connection
```

- [ ] **Step 8: Run ruff check and format**

Run: `cd backend && uv run ruff check --fix src/lakehouse/services/parse_service.py && uv run ruff format src/lakehouse/services/parse_service.py`
Expected: no errors.

- [ ] **Step 9: Run typecheck**

Run: `cd backend && uv run pyright src/lakehouse/services/parse_service.py`
Expected: 0 errors.

- [ ] **Step 10: Commit**

```bash
git add backend/src/lakehouse/services/parse_service.py
git commit -m "agrega --workers y ProcessPoolExecutor a ParseService.run()"
```

---

### Task 2: Add `--workers` to CLI `pipeline parse`

**Files:**
- Modify: `backend/src/lakehouse/cli.py`

- [ ] **Step 1: Add `--workers` option to `parse` command**

In `cli.py`, in the `parse` function, after the `clean` option:

```python
workers: int = typer.Option(default=1, help="Parallel parse workers (ProcessPoolExecutor)"),
```

- [ ] **Step 2: Pass `workers` to `service.run()`**

Change the `service.run()` call from:
```python
result = service.run(dry_run=dry_run, conference_date=conference_date, clean=clean)
```
to:
```python
result = service.run(dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers)
```

- [ ] **Step 3: Run ruff check and format**

Run: `cd backend && uv run ruff check --fix src/lakehouse/cli.py && uv run ruff format src/lakehouse/cli.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/src/lakehouse/cli.py
git commit -m "agrega --workers al comando pipeline parse"
```

---

### Task 3: Add tests for `_parse_one_row`

**Files:**
- Modify: `backend/tests/test_services/test_parse_service.py`

- [ ] **Step 1: Add import for `_parse_one_row`**

At the top of the file, change the import line:
```python
from lakehouse.services.parse_service import ParseService
```
to:
```python
from lakehouse.services.parse_service import ParseService, _parse_one_row
```

- [ ] **Step 2: Add test class `TestParseOneRow`**

Add at the end of the file, after `TestParseServiceClean`:

```python
class TestParseOneRow:
    def test_returns_conference_and_interventions(self):
        conference, interventions, dlq = _parse_one_row(
            source_url="https://example.com/27-de-julio-de-2026",
            raw_html=(
                "<html><title>Titulo</title><main>"
                "<strong>PERIODISTA:</strong> Buenos dias.</p>"
                "</main></html>"
            ),
            conference_date=None,
        )
        assert conference is not None
        assert conference.date == "2026-07-27"
        assert len(interventions) >= 1
        assert dlq == []

    def test_unknown_date_returns_dlq(self):
        conference, interventions, dlq = _parse_one_row(
            source_url="https://example.com/no-date",
            raw_html="<html></html>",
            conference_date=None,
        )
        assert conference is None
        assert interventions == []
        assert len(dlq) == 1
        assert dlq[0].rejection_reason == "unknown_date"

    def test_respects_conference_date_override(self):
        conference, interventions, dlq = _parse_one_row(
            source_url="https://example.com/articulo",
            raw_html="<html><title>T</title><main></main></html>",
            conference_date="2026-01-15",
        )
        assert conference is not None
        assert conference.date == "2026-01-15"
```

- [ ] **Step 3: Run tests to verify**

Run: `cd backend && uv run pytest tests/test_services/test_parse_service.py::TestParseOneRow -xvs`
Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_services/test_parse_service.py
git commit -m "agrega tests para _parse_one_row"
```

---

### Task 4: Add tests for `ParseService.run()` with `workers`

**Files:**
- Modify: `backend/tests/test_services/test_parse_service.py`

**Strategy:** Mock `_run_sequential` and `_run_parallel` to verify correct dispatch without spawning real OS processes. Test `_parse_one_row` independently (done in Task 3).

- [ ] **Step 1: Add tests for workers dispatch**

Add after `TestParseOneRow`:

```python
class TestParseServiceWorkers:
    def test_run_dispatches_to_sequential_when_workers_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(0, 0)) as mock_seq,
            patch.object(service, "_run_parallel") as mock_par,
        ):
            result = service.run(dry_run=False, workers=1)
        assert result == {"interventions": 0, "dlq": 0}
        mock_seq.assert_called_once()
        mock_par.assert_not_called()

    def test_run_dispatches_to_parallel_when_workers_gt_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential") as mock_seq,
            patch.object(service, "_run_parallel", return_value=(0, 0)) as mock_par,
        ):
            result = service.run(dry_run=False, workers=4)
        assert result == {"interventions": 0, "dlq": 0}
        mock_par.assert_called_once()
        mock_seq.assert_not_called()

    def test_run_workers_0_clamped_to_1(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(0, 0)) as mock_seq,
            patch.object(service, "_run_parallel") as mock_par,
        ):
            result = service.run(dry_run=False, workers=0)
        assert result == {"interventions": 0, "dlq": 0}
        mock_seq.assert_called_once()
        mock_par.assert_not_called()

    def test_run_workers_dry_run_no_write_conn(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/a", "<html></html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection") as mock_get_conn,
            patch.object(service, "_run_sequential", return_value=(1, 0)),
        ):
            result = service.run(dry_run=True, workers=1)
        assert result == {"interventions": 1, "dlq": 0}
        mock_get_conn.assert_not_called()
```

- [ ] **Step 2: Update existing tests to work with refactored `run()`**

The existing tests in `TestParseService` mock `parse_html_to_interventions`, `parse_conference_date`, `build_conference_record`, etc. After the refactor, `run()` no longer calls `_process_row` — it delegates to `_run_sequential` or `_run_parallel`. These tests need to be adapted.

Replace the existing `TestParseService` class with tests that use the mock delegation pattern:

```python
class TestParseService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        result = service.run(dry_run=True)
        assert result == {"interventions": 0, "dlq": 0}

    def test_run_sequential_counts_correctly(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("https://example.com/27-de-julio-de-2026", "<html>...</html>"),
        ]
        service = ParseService(settings=settings, duckdb_conn=conn)
        with (
            patch("lakehouse.services.parse_service.get_connection"),
            patch("lakehouse.services.parse_service.ensure_silver_tables"),
            patch.object(service, "_run_sequential", return_value=(3, 1)),
        ):
            result = service.run(dry_run=False)
        assert result["interventions"] == 3
        assert result["dlq"] == 1

    def test_run_clean_drops_silver_tables(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.drop_silver_tables") as mock_drop:
            result = service.run(clean=True)
        assert result == {"interventions": 0, "dlq": 0}
        mock_drop.assert_called_once()

    def test_run_clean_ignored_in_dry_run(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)
        with patch("lakehouse.services.parse_service.drop_silver_tables") as mock_drop:
            service.run(clean=True, dry_run=True)
        mock_drop.assert_not_called()
```

**Nota:** Los tests de `TestParseServiceClean` se consolidan en `TestParseService`. Los tests que verificaban comportamiento interno de `_process_row` (merge_conference, insert_dlq_record, etc.) pasan a ser tests de integracion de `_parse_one_row` (ya cubiertos en Task 3) y de `_run_sequential`/`_run_parallel` (que se prueban con datos reales o mocks de mas bajo nivel).

---

### Task 5: Update CLI tests for `--workers`

**Files:**
- Modify: `backend/tests/test_cli.py`

- [ ] **Step 1: Add `--workers` test to `TestPipelineParse`**

Add at the end of `TestPipelineParse` class, after `test_parse_clean`:

```python
@patch("lakehouse.cli.ParseService")
@patch("lakehouse.cli.get_connection")
def test_parse_with_workers(self, mock_conn, mock_svc_cls):
    mock_svc = mock_svc_cls.return_value
    mock_svc.run.return_value = {"interventions": 5, "dlq": 1}
    result = runner.invoke(app, ["pipeline", "parse", "--workers", "4"])
    assert result.exit_code == 0
    mock_svc.run.assert_called_once_with(
        dry_run=False, conference_date=None, clean=False, workers=4
    )
```

- [ ] **Step 2: Update existing tests to expect `workers=1`**

In each existing test in `TestPipelineParse`, update `assert_called_once_with` to include `workers=1`:

- `test_parse_dry_run`: change to `mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None, clean=False, workers=1)`
- `test_parse_no_dry_run`: change to `mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=False, workers=1)`
- `test_parse_with_date`: change to `mock_svc.run.assert_called_once_with(dry_run=False, conference_date="2024-10-01", clean=False, workers=1)`
- `test_parse_clean`: change to `mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=True, workers=1)`

- [ ] **Step 3: Run CLI tests**

Run: `cd backend && uv run pytest tests/test_cli.py::TestPipelineParse -xvs`
Expected: 5 tests pass (4 existing updated + 1 new).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_cli.py
git commit -m "agrega test de --workers en CLI parse"
```

---

### Task 6: Full verification

- [ ] **Step 1: Run lint and format on all changed files**

```bash
cd backend && uv run ruff check --fix src/lakehouse/services/parse_service.py src/lakehouse/cli.py tests/ && uv run ruff format src/lakehouse/services/parse_service.py src/lakehouse/cli.py tests/
```
Expected: no errors, no changes.

- [ ] **Step 2: Run typecheck**

```bash
cd backend && uv run pyright src/
```
Expected: 0 errors.

- [ ] **Step 3: Run all backend tests**

```bash
cd backend && uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90 -xvs
```
Expected: all tests pass, coverage >= 90%.

- [ ] **Step 4: Verify idempotency manually (if data available)**

```bash
make pipeline-parse ARGS="--clean"
make pipeline-parse ARGS="--workers 4"
make pipeline-parse
```
Expected: second run (after clean+parallel) should insert 0 new rows (INSERT OR IGNORE).

- [ ] **Step 5: Commit verification results**

```bash
git add -A
git commit -m "verifica quality gates: ruff, pyright, pytest >=90% coverage"
```
