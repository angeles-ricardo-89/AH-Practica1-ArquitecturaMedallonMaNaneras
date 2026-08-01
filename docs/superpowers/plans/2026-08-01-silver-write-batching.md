# Batching de Escrituras DuckDB en Silver (Single Transaction) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the Silver write phase in a single DuckDB transaction (BEGIN/COMMIT/ROLLBACK) via a new `_run_with_transaction` helper, reducing writes from ~42ms each to ~2.3ms each (~18x), cutting full-run time from ~35 min to ~90s.

**Architecture:** Extract `_run_with_transaction(dispatch, dry_run)` in `ParseService` that opens `write_conn`, issues `BEGIN TRANSACTION`, runs the dispatch callback (sequential or parallel), then `COMMIT` on success or `ROLLBACK` + re-raise on exception, closing the connection in `finally`. `run()` calls it from both branches, preserving the fork-safety ordering (pool created before `write_conn`).

**Tech Stack:** Python 3.13, DuckDB, concurrent.futures, pytest, ruff, pyright.

---

### Task 1: Add `_run_with_transaction` helper and use it in `run()`

**Files:**
- Modify: `backend/src/lakehouse/services/parse_service.py`

- [ ] **Step 1: Write the failing tests for `_run_with_transaction`**

Add a new test class to `backend/tests/test_services/test_parse_service.py`, after `TestParseServiceWorkers`. The file already imports `Future`, `MagicMock`, `patch`, `Settings`, `ParseService`, and `_parse_one_row` — no new imports are needed for this test class:

```python
class TestRunWithTransaction:
    @staticmethod
    def _service() -> ParseService:
        return ParseService(settings=Settings(), duckdb_conn=MagicMock())

    def test_opens_connection_and_commits(self):
        service = self._service()
        mock_write_conn = MagicMock()

        def dispatch(write_conn):
            assert write_conn is mock_write_conn
            return (3, 1)

        with patch(
            "lakehouse.services.parse_service.get_connection",
            return_value=mock_write_conn,
        ) as mock_get_conn:
            total_int, total_dlq = service._run_with_transaction(dispatch, dry_run=False)

        assert (total_int, total_dlq) == (3, 1)
        mock_get_conn.assert_called_once()
        mock_write_conn.execute.assert_any_call("BEGIN TRANSACTION")
        mock_write_conn.execute.assert_any_call("COMMIT")
        mock_write_conn.close.assert_called_once()

    def test_rolls_back_on_exception_and_reraises(self):
        service = self._service()
        mock_write_conn = MagicMock()

        def dispatch(write_conn):
            raise RuntimeError("boom")

        with (
            patch(
                "lakehouse.services.parse_service.get_connection",
                return_value=mock_write_conn,
            ),
            patch.object(service, "_logger"),
        ):
            try:
                service._run_with_transaction(dispatch, dry_run=False)
                raise AssertionError("should have raised")
            except RuntimeError as exc:
                assert str(exc) == "boom"

        mock_write_conn.execute.assert_any_call("BEGIN TRANSACTION")
        mock_write_conn.execute.assert_any_call("ROLLBACK")
        mock_write_conn.close.assert_called_once()

    def test_dry_run_no_connection_no_transaction(self):
        service = self._service()

        def dispatch(write_conn):
            assert write_conn is None
            return (0, 0)

        with patch(
            "lakehouse.services.parse_service.get_connection"
        ) as mock_get_conn:
            total_int, total_dlq = service._run_with_transaction(dispatch, dry_run=True)

        assert (total_int, total_dlq) == (0, 0)
        mock_get_conn.assert_not_called()

    def test_no_dispatch_on_empty_rows_no_transaction(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = ParseService(settings=settings, duckdb_conn=conn)

        with patch("lakehouse.services.parse_service.get_connection") as mock_get_conn:
            result = service.run(dry_run=False)
        assert result == {"interventions": 0, "dlq": 0}
        mock_get_conn.assert_not_called()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_services/test_parse_service.py::TestRunWithTransaction -xvs`
Expected: FAIL with `AttributeError: 'ParseService' object has no attribute '_run_with_transaction'`.

- [ ] **Step 3: Implement `_run_with_transaction` and refactor `run()`**

Add `Callable` to the `typing` imports at the top of `parse_service.py`:

```python
from typing import Callable
```

Add the helper method to `ParseService` (place it after `_run_parallel`):

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

Refactor the `if rows:` block in `run()` (currently lines 83-113) to use the helper:

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

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_services/test_parse_service.py::TestRunWithTransaction -xvs`
Expected: 4 tests PASS.

- [ ] **Step 5: Run the full parse service test suite**

Run: `cd backend && uv run pytest tests/test_services/test_parse_service.py -xvs`
Expected: all tests pass (existing 17 + 4 new = 21).

- [ ] **Step 6: Run ruff and pyright**

Run: `cd backend && uv run ruff check --fix src/lakehouse/services/parse_service.py tests/test_services/test_parse_service.py && uv run ruff format src/lakehouse/services/parse_service.py tests/test_services/test_parse_service.py`
Expected: clean.

Run: `cd backend && uv run pyright src/lakehouse/services/parse_service.py`
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add backend/src/lakehouse/services/parse_service.py backend/tests/test_services/test_parse_service.py
git commit -m "agrega helper _run_with_transaction con single BEGIN/COMMIT/ROLLBACK en parse"
```

---

### Task 2: Full verification

- [ ] **Step 1: Run lint and format on all changed files**

```bash
cd backend && uv run ruff check --fix src/lakehouse/services/parse_service.py tests/ && uv run ruff format src/lakehouse/services/parse_service.py tests/
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

- [ ] **Step 4: Verify performance and idempotency manually (if data available)**

```bash
make pipeline-parse ARGS="--clean --workers 4"
```
Expected: completes in ~90s for 933 rows (vs ~35 min before). Then re-run:
```bash
make pipeline-parse
```
Expected: inserts 0 new rows (INSERT OR IGNORE idempotency preserved). Compare `interventions`/`dlq` counts with `workers=1`:
```bash
make pipeline-parse ARGS="--clean"
```
Expected: identical `interventions`/`dlq` as the parallel run.

- [ ] **Step 5: Commit verification results**

```bash
git add -A
git commit -m "verifica quality gates y rendimiento de single transaction en parse"
```
