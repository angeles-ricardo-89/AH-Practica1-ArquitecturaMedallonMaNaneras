# Concurrencia en Enrich con --workers — Plan de Implementacion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar `--workers` al comando `pipeline enrich` para paralelizar las llamadas a Ollama durante el enriquecimiento, con default 1 (comportamiento actual intacto).

**Architecture:** `enrich_interventions` gana parametro `workers`. Con `workers==1` mantiene el loop secuencial exacto. Con `workers>1` usa `ThreadPoolExecutor` donde cada worker calcula solo el embedding (`_embed_one`); el hilo principal drena con `as_completed` y hace los INSERTs (`_store_gold`) y el progreso.

**Tech Stack:** Python 3.13, `concurrent.futures` (ThreadPoolExecutor), psycopg, Ollama, typer

---

### File Structure

| Archivo | Accion | Responsabilidad |
|---------|--------|-----------------|
| `backend/src/lakehouse/pipeline/enrichment.py` | Modify | + `_embed_one`, + `_store_gold`, `enrich_interventions` con `workers` y path paralelo |
| `backend/src/lakehouse/services/enrich_service.py` | Modify | `run()` acepta `workers` y lo propaga |
| `backend/src/lakehouse/cli.py` | Modify | `--workers` en comando `enrich` |
| `backend/tests/test_pipeline/test_enrichment.py` | Modify | Tests `_embed_one`, `_store_gold`, path paralelo |
| `backend/tests/test_services/test_enrich_service.py` | Modify | Tests propagacion de `workers` |
| `backend/tests/test_cli.py` | Modify | Test `--workers` en CLI, actualizar asserts existentes |

---

### Task 1: Helper `_embed_one`

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Agregar tests de `_embed_one`**

Agrega al final de `backend/tests/test_pipeline/test_enrichment.py` (despues de `TestBuildEmbeddingText`):

```python
class TestEmbedOne:
    def test_returns_payload_and_embedding_on_success(self, sample_intervention: InterventionRecord) -> None:
        from lakehouse.pipeline.enrichment import _embed_one

        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.return_value = [0.1] * 768
            payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert "Contexto: Conferencia del 2024-10-01" in payload
        assert "Participante:" in payload
        assert embedding == [0.1] * 768
        mock_embed.assert_called_once_with(
            build_embedding_text(sample_intervention),
            "http://localhost:11434",
            "nomic-embed-text",
        )

    def test_returns_none_on_connection_error(self, sample_intervention: InterventionRecord) -> None:
        from lakehouse.pipeline.enrichment import _embed_one

        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ConnectionError("Ollama embedding failed after 3 retries")
            payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert embedding is None
        assert "Contexto: Conferencia del 2024-10-01" in payload

    def test_returns_none_on_value_error(self, sample_intervention: InterventionRecord) -> None:
        from lakehouse.pipeline.enrichment import _embed_one

        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ValueError("Ollama returned empty embeddings")
            _payload, embedding = _embed_one(
                sample_intervention,
                "2024-10-01",
                "http://localhost:11434",
                "nomic-embed-text",
            )
        assert embedding is None
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEmbedOne -v
```

Expected: FAIL con `ImportError: cannot import name '_embed_one'`.

- [ ] **Step 3: Implementar `_embed_one`**

En `backend/src/lakehouse/pipeline/enrichment.py`, agrega despues de `build_embedding_text` (la funcion que retorna `"P: ...\nR: ..."`):

```python
def _embed_one(
    intervention: InterventionRecord,
    effective_date: str,
    ollama_base_url: str,
    ollama_model: str,
) -> tuple[str, list[float] | None]:
    payload = build_embedding_payload(intervention, effective_date)
    embedding_text = build_embedding_text(intervention)
    try:
        embedding = embed_text(embedding_text, ollama_base_url, ollama_model)
        return payload, embedding
    except (ConnectionError, ValueError):
        return payload, None
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEmbedOne -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "feat: extrae _embed_one para generar payload y embedding por intervencion"
```

---

### Task 2: Helper `_store_gold`

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Agregar test de `_store_gold`**

Agrega al final de `backend/tests/test_pipeline/test_enrichment.py` (despues de `TestEmbedOne`):

```python
class TestStoreGold:
    def test_executes_insert_with_correct_params(self, sample_intervention: InterventionRecord) -> None:
        from lakehouse.pipeline.enrichment import _store_gold

        cur = MagicMock()
        _store_gold(
            cur,
            sample_intervention,
            "2024-10-01",
            "payload metadata",
            [0.1] * 768,
        )
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO gold.rag_corpus" in sql
        assert params[0] == sample_intervention.intervention_key
        assert params[2] == "2024-10-01"
        assert params[5] == "payload metadata"
        assert params[8] == [0.1] * 768
```

- [ ] **Step 2: Verificar que falla**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestStoreGold -v
```

Expected: FAIL con `ImportError: cannot import name '_store_gold'`.

- [ ] **Step 3: Implementar `_store_gold`**

En `backend/src/lakehouse/pipeline/enrichment.py`, agrega despues de `_embed_one`:

```python
def _store_gold(
    cur: Any,
    intervention: InterventionRecord,
    effective_date: str,
    payload: str,
    embedding: list[float],
) -> None:
    cur.execute(
        """
            INSERT INTO gold.rag_corpus
                (chunk_key, conference_id, conference_date, participant, chunk_text, payload, url, pregunta_activa, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_key) DO UPDATE SET
                conference_id = EXCLUDED.conference_id,
                conference_date = EXCLUDED.conference_date,
                payload = EXCLUDED.payload,
                url = EXCLUDED.url,
                pregunta_activa = EXCLUDED.pregunta_activa
            """,
        (
            intervention.intervention_key,
            intervention.conference_id,
            effective_date,
            intervention.participant,
            intervention.text,
            payload,
            intervention.url,
            intervention.pregunta_activa,
            embedding,
        ),
    )
```

**Nota:** `Any` ya esta disponible via `from typing import TYPE_CHECKING`? No — necesitas importar `Any`. Cambia la linea 5 en `enrichment.py` de `from typing import TYPE_CHECKING` a `from typing import TYPE_CHECKING, Any`.

- [ ] **Step 4: Verificar que pasa**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestStoreGold -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "feat: extrae _store_gold para insertar chunks en gold.rag_corpus"
```

---

### Task 3: `enrich_interventions` con workers (refactor + path secuencial)

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

**Objetivo:** refactorizar `enrich_interventions` para usar `_embed_one` + `_store_gold` en el loop secuencial, agregando el parametro `workers`. Los tests existentes de `TestEnrichInterventions` deben seguir pasando.

- [ ] **Step 1: Verificar tests existentes pasan ANTES del refactor**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEnrichInterventions -v
```

Expected: todos pasan (baseline antes de tocar el loop).

- [ ] **Step 2: Refactorizar el loop secuencial de `enrich_interventions`**

En `backend/src/lakehouse/pipeline/enrichment.py`, reemplaza el cuerpo del loop en `enrich_interventions` (lineas ~173-233, desde `for idx, intervention in enumerate(interventions):` hasta `embedded += 1`) con:

```python
    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        reporter = ProgressReporter(total=total, label="gold")
        for intervention in interventions:
            effective_date = conference_date or intervention.conference_date
            if not effective_date:
                logger.error(
                    "Intervención sin fecha de conferencia, omitida",
                    intervention_key=intervention.intervention_key,
                )
                failed += 1
                reporter.tick()
                continue
            payload, embedding = _embed_one(
                intervention, effective_date, ollama_base_url, ollama_model
            )
            if embedding is None:
                failed += 1
                reporter.tick()
                continue
            logger.info(
                "Embedding generado para intervención",
                intervention_key=intervention.intervention_key,
                participant=intervention.participant,
                dim=len(embedding),
            )
            try:
                _store_gold(cur, intervention, effective_date, payload, embedding)
            except psycopg.errors.UniqueViolation:
                logger.warning(
                    "Chunk duplicado en Gold, omitido",
                    chunk_key=intervention.intervention_key,
                )
            embedded += 1
            reporter.tick()
        reporter.finish()
        conn.commit()
```

**Nota:** el `logger.info("Embedding generado para intervención %d/%d", idx + 1, total, ...)` se simplifica a un log sin el par `%d/%d` (el `idx` deja de existir como concepto con workers; el `ProgressReporter` ya muestra el progreso numerico). Se conserva el detalle `intervention_key`, `participant`, `dim` para observabilidad.

**Tambien agrega** el parametro `workers` a la firma (linea ~153):

```python
def enrich_interventions(
    interventions: list[InterventionRecord],
    conference_date: str | None,
    pg_conn_str: str,
    ollama_base_url: str,
    ollama_model: str,
    workers: int = 1,
) -> dict:
```

Y la validacion al inicio (despues de `logger.info("Iniciando enriquecimiento Gold", ...)`):

```python
    workers = max(1, workers)
```

- [ ] **Step 3: Verificar que todos los tests de TestEnrichInterventions pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEnrichInterventions -v
```

Expected: todos pasan. Si `test_partial_embedding_failure_logs_and_continues` falla, revisa que el `side_effect` de `mock_embed` (lista de 3) se consuma en orden — con `_embed_one` el orden se mantiene porque es secuencial.

- [ ] **Step 4: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py
git commit -m "refactor: enrich_interventions usa _embed_one y _store_gold en path secuencial"
```

---

### Task 4: Path paralelo con ThreadPoolExecutor

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Agregar tests del path paralelo**

Agrega al final de `backend/tests/test_pipeline/test_enrichment.py`:

```python
class TestEnrichInterventionsParallel:
    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_greater_than_one_embeds_all(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(5)
        ]

        result = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=3,
        )

        assert result["total"] == 5
        assert result["embedded"] == 5
        assert result["failed"] == 0
        assert mock_embed.call_count == 5
        insert_count = sum(
            1 for c in mock_cursor.execute.call_args_list if "INSERT INTO gold.rag_corpus" in c[0][0]
        )
        assert insert_count == 5

    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_workers_parallel_counts_failures(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        def side_effect(*args, **kwargs):
            text = args[0]
            if "Texto 1" in text:
                raise ConnectionError("Ollama embedding failed after 3 retries")
            return [0.5] * 768

        mock_embed.side_effect = side_effect

        records = [
            InterventionRecord(
                intervention_key=f"rec_{i:03d}_hash",
                conference_id="conf",
                participant=f"PARTICIPANTE {i}",
                text=f"Texto {i}",
                pregunta_activa="",
                chunk_index=i,
                url="https://example.com",
            )
            for i in range(3)
        ]

        result = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=2,
        )

        assert result["total"] == 3
        assert result["embedded"] == 2
        assert result["failed"] == 1

    def test_workers_zero_clamped_to_one(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        records = [
            InterventionRecord(
                intervention_key="rec_000_hash",
                conference_id="conf",
                participant="P",
                text="Texto",
                pregunta_activa="",
                chunk_index=0,
                url="https://example.com",
            )
        ]

        result = enrich_interventions(
            interventions=records,
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
            workers=0,
        )

        assert result["embedded"] == 1
        assert result["failed"] == 0
```

Este test verifica que `workers=0` se convierte en 1 via `max(1, workers)` inline (no se extrae helper `_clamp_workers`).

- [ ] **Step 2: Verificar que fallan los tests del path paralelo**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEnrichInterventionsParallel -v
```

Expected: FAIL (el path paralelo no existe aun; `workers` se ignora y el loop es secuencial, por lo que `test_workers_greater_than_one_embeds_all` podria pasar pero `test_workers_parallel_counts_failures` podria fallar si el orden del side_effect no coincide).

- [ ] **Step 3: Implementar el path paralelo**

En `backend/src/lakehouse/pipeline/enrichment.py`:

1. Agrega el import al inicio (linea ~5):
```python
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
```

2. Reemplaza la validacion `workers = max(1, workers)` (agregada en Task 3) por:

```python
    workers = max(1, workers)
```

(Si usaste la version inline, no hay helper `_clamp_workers`; el clamp queda inline. Si el test usa `_clamp_workers`, agrega la funcion helper.)

3. Despues del bloque `with psycopg.connect(pg_conn_str) as conn:` y del calculo de `total`, agrega la rama paralela. Reestructura `enrich_interventions` asi:

```python
    with psycopg.connect(pg_conn_str) as conn:
        cur = conn.cursor()
        reporter = ProgressReporter(total=total, label="gold")
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures: dict[Future, InterventionRecord] = {}
                for intervention in interventions:
                    effective_date = conference_date or intervention.conference_date
                    if not effective_date:
                        logger.error(
                            "Intervención sin fecha de conferencia, omitida",
                            intervention_key=intervention.intervention_key,
                        )
                        failed += 1
                        reporter.tick()
                        continue
                    future = pool.submit(
                        _embed_one,
                        intervention,
                        effective_date,
                        ollama_base_url,
                        ollama_model,
                    )
                    futures[future] = intervention

                for future in as_completed(futures):
                    intervention = futures[future]
                    payload, embedding = future.result()
                    if embedding is None:
                        failed += 1
                    else:
                        logger.info(
                            "Embedding generado para intervención",
                            intervention_key=intervention.intervention_key,
                            participant=intervention.participant,
                            dim=len(embedding),
                        )
                        try:
                            effective_date = conference_date or intervention.conference_date
                            _store_gold(cur, intervention, effective_date, payload, embedding)
                        except psycopg.errors.UniqueViolation:
                            logger.warning(
                                "Chunk duplicado en Gold, omitido",
                                chunk_key=intervention.intervention_key,
                            )
                        embedded += 1
                    reporter.tick()
        else:
            for intervention in interventions:
                effective_date = conference_date or intervention.conference_date
                if not effective_date:
                    logger.error(
                        "Intervención sin fecha de conferencia, omitida",
                        intervention_key=intervention.intervention_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                payload, embedding = _embed_one(
                    intervention, effective_date, ollama_base_url, ollama_model
                )
                if embedding is None:
                    failed += 1
                    reporter.tick()
                    continue
                logger.info(
                    "Embedding generado para intervención",
                    intervention_key=intervention.intervention_key,
                    participant=intervention.participant,
                    dim=len(embedding),
                )
                try:
                    _store_gold(cur, intervention, effective_date, payload, embedding)
                except psycopg.errors.UniqueViolation:
                    logger.warning(
                        "Chunk duplicado en Gold, omitido",
                        chunk_key=intervention.intervention_key,
                    )
                embedded += 1
                reporter.tick()
        reporter.finish()
        conn.commit()
```

**Nota:** `reporter.finish()` y `conn.commit()` se ejecutan UNA vez, despues del if/else, fuera de ambos branches. El `logger.info("Iniciando enriquecimiento Gold", total_intervenciones=total, modelo=ollama_model)` se mantiene antes del `with`. El log de resumen `"Enriquecimiento Gold completado"` se mantiene despues del `with`.

- [ ] **Step 4: Verificar que pasan los tests**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py -v
```

Expected: todos los tests de `TestEnrichInterventions`, `TestEnrichInterventionsParallel`, `TestEmbedOne`, `TestStoreGold` y `TestBuildEmbeddingText` pasan.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "feat: path paralelo en enrich_interventions con ThreadPoolExecutor"
```

---

### Task 5: Propagar workers en EnrichService

**Files:**
- Modify: `backend/src/lakehouse/services/enrich_service.py`
- Test: `backend/tests/test_services/test_enrich_service.py`

- [ ] **Step 1: Agregar tests**

Agrega al final de `backend/tests/test_services/test_enrich_service.py`:

```python
    def test_run_propaga_workers_a_enrich_interventions(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("k1", "c1", "P", "t", "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(workers=4)
        assert result["embedded"] == 1
        _, kwargs = mock_enrich.call_args
        assert kwargs["workers"] == 4

    def test_run_default_workers_is_one(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("k1", "c1", "P", "t", "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            service.run()
        _, kwargs = mock_enrich.call_args
        assert kwargs["workers"] == 1
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_services/test_enrich_service.py::TestEnrichService::test_run_propaga_workers_a_enrich_interventions -v
```

Expected: FAIL con `TypeError: run() got an unexpected keyword argument 'workers'`.

- [ ] **Step 3: Implementar**

En `backend/src/lakehouse/services/enrich_service.py`, cambia la firma de `run` (linea ~18):

```python
    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
        clean: bool = False,
        workers: int = 1,
    ) -> dict:
```

Y pasa `workers=workers` a `enrich_interventions` (linea ~71):

```python
        return enrich_interventions(
            interventions=interventions,
            conference_date=conference_date,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
            workers=workers,
        )
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_services/test_enrich_service.py -v
```

Expected: todos los tests pasan.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/enrich_service.py backend/tests/test_services/test_enrich_service.py
git commit -m "feat: EnrichService.run acepta y propaga workers"
```

---

### Task 6: Argumento --workers en CLI

**Files:**
- Modify: `backend/src/lakehouse/cli.py`
- Test: `backend/tests/test_cli.py`

- [ ] **Step 1: Actualizar tests de CLI existentes y agregar nuevo**

En `backend/tests/test_cli.py`, los 3 tests de `TestPipelineEnrich` usan `assert_called_once_with(dry_run=..., conference_date=None, clean=...)`. Deben actualizarse para incluir `workers=1`. Edita cada assert:

```python
mock_svc.run.assert_called_once_with(dry_run=True, conference_date=None, clean=False, workers=1)  # test_enrich_dry_run
mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=False, workers=1)  # test_enrich_no_dry_run
mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=True, workers=1)   # test_enrich_clean
```

Y agrega un nuevo test al final de `TestPipelineEnrich` (despues de `test_enrich_clean`):

```python
    @patch("lakehouse.cli.EnrichService")
    @patch("lakehouse.cli.get_connection")
    def test_enrich_with_workers(self, mock_conn, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.run.return_value = {"embedded": 1, "failed": 0, "total": 1}
        result = runner.invoke(app, ["pipeline", "enrich", "--workers", "4"])
        assert result.exit_code == 0
        mock_svc.run.assert_called_once_with(dry_run=False, conference_date=None, clean=False, workers=4)
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_cli.py::TestPipelineEnrich -v
```

Expected: FAIL. Los asserts existentes fallan (falta `workers=1`) y el nuevo test falla (no existe `--workers`).

- [ ] **Step 3: Implementar**

En `backend/src/lakehouse/cli.py`, agrega el parametro al comando `enrich` (linea ~54):

```python
    workers: int = typer.Option(default=1, help="Parallel Ollama embedding workers"),
```

Y pasa `workers=workers` en la llamada a `service.run` (linea ~67):

```python
    result = service.run(dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers)
```

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_cli.py -v
```

Expected: todos los tests pasan, incluido `test_enrich_with_workers`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/cli.py backend/tests/test_cli.py
git commit -m "feat: agrega --workers al comando pipeline enrich"
```

---

### Task 7: Verificacion completa

- [ ] **Step 1: Ruff + ty + suite completa**

```bash
cd backend && uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/
cd backend && uv tool run ty check src/
cd backend && uv run pytest -q --cov=src --cov-report=term-missing
```

Expected:
- ruff: All checks passed
- ty: All checks passed
- pytest: todos pasan, >=90% coverage

- [ ] **Step 2: Commit de verificacion**

```bash
git add -A
git commit -m "chore: verificacion post feature concurrencia enrich"
```
