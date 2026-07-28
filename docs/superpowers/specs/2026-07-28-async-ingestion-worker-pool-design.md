# Design Spec: Async Ingestion with Worker Pool

**Date:** 2026-07-28
**Status:** Draft (Pending User Review)

## Overview
Transform the current sequential ingestion process into an asynchronous, highly efficient process using a worker pool pattern. This allows for controlled concurrency and improved throughput.

## Goals
- Implement asynchronous HTTP requests using `httpx`.
- Use a worker pool pattern with `asyncio.Queue` to manage concurrency.
- Control concurrency via a configurable environment variable `MAX_INGEST_POOL` (default=10).
- Implement a retry mechanism for individual article downloads.
- Maintain non-blocking execution for the main event loop.

## Proposed Changes

### 1. Configuration (`backend/src/lakehouse/config.py`)
- Add `MAX_INGEST_POOL: int = 10` to the `Settings` class in `backend/src/lakehouse/config.py`.

### 2. Ingestor Refactor (`backend/src/lakehouse/pipeline/ingestion.py`)
- Change `Ingestor.run` to `async def run`.
- Replace sequential `for` loop with a worker pool pattern:
    - Use `asyncio.Queue` to manage URLs.
    - Spawn $N$ worker tasks where $N$ is `MAX_INGEST_POOL`.
    - Each worker consumes URLs, fetches HTML using `httpx.AsyncClient`, and inserts into DB.
- Integrate retry logic for `fetch_article_html`.
- Use `asyncio.to_thread` for DuckDB operations to avoid blocking the event loop.

### 3. IngestionService Refactor (`backend/src/lakehouse/services/ingest_service.py`)
- Change `IngestService.run` to `async def run`.
- Use `await ingestor.run(...)`.

### 4. Dependencies
- Ensure `httpx` is available in the environment.

## Success Criteria
- [ ] Ingestion is asynchronous and concurrent.
- [ ] Concurrency is strictly limited to `MAX_INGEST_POOL`.
- [ ] Errors in individual articles are handled with retries and don't stop the whole process.
- [ ] Memory usage remains stable during large ingestion runs.
