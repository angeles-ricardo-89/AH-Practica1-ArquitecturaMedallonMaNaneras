# Concurrencia en Enrich con --workers

## Problema

`enrich_interventions` procesa las intervenciones de forma secuencial: por cada una, llama a `embed_text` (Ollama) esperando la respuesta HTTP antes de pasar a la siguiente. Con miles de intervenciones y un GPU disponible, el tiempo de enriquecimiento esta dominado por la latencia de las llamadas seriales a Ollama. El GPU queda subutilizado porque nunca hay mas de una request en vuelo.

```
for intervention in interventions:
    embedding = embed_text(...)  # bloquea hasta que Ollama responde
    cur.execute(INSERT ...)      # luego inserta
```

## Solucion

Agregar un argumento `--workers` al comando `pipeline enrich` que controla cuantas llamadas a Ollama se ejecutan en paralelo. Default `1` (comportamiento actual intacto). Con `workers > 1`, se usa un `ThreadPoolExecutor` donde cada worker calcula SOLO el embedding; el hilo principal drena los resultados y hace los INSERTs.

**Principio clave:** los workers paralelizan unicamente las llamadas a Ollama. Todos los INSERTs a Postgres ocurren en el hilo principal, eliminando riesgo de race conditions y lock contention en `gold.rag_corpus`.

## Diseno

### 1. Helper `_embed_one` (nuevo)

Extrae la logica por-intervencion de generar payload + embedding:

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
        return payload, embedding          # exito: (payload, embedding)
    except (ConnectionError, ValueError):
        return payload, None               # fallo: (payload, None)
```

**Nota:** el manejo de `effective_date` vacia (intervencion sin fecha → `failed += 1` y `continue`) se mantiene en el bucle principal, NO dentro de `_embed_one`, porque no requiere llamada a Ollama y no debe consumir un worker.

### 2. Helper `_store_gold` (nuevo)

Extrae el INSERT a `gold.rag_corpus`:

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
        (... params identicos a los de hoy ...),
    )
```

El `try/except psycopg.errors.UniqueViolation` se mantiene en el llamador (cuenta como `embedded` con warning), igual que hoy.

### 3. `enrich_interventions` con `workers`

Firma nueva: `enrich_interventions(interventions, conference_date, pg_conn_str, ollama_base_url, ollama_model, workers: int = 1) -> dict`.

**Validacion:** `workers = max(1, workers)` para garantizar `workers >= 1`.

#### Path `workers == 1` (secuencial, igual que hoy)

```python
for intervention in interventions:
    effective_date = conference_date or intervention.conference_date
    if not effective_date:
        failed += 1
        reporter.tick()
        continue
    payload, embedding = _embed_one(intervention, effective_date, ollama_base_url, ollama_model)
    if embedding is None:
        failed += 1
        reporter.tick()
        continue
    try:
        _store_gold(cur, intervention, effective_date, payload, embedding)
    except psycopg.errors.UniqueViolation:
        logger.warning("Chunk duplicado en Gold, omitido", chunk_key=intervention.intervention_key)
    embedded += 1
    reporter.tick()
```

`reporter.update(idx + 1)` se reemplaza por `reporter.tick()` llamado tras cada intervencion procesada (mantiene la semantica de progreso por indice en el path secuencial).

#### Path `workers > 1` (paralelo)

```python
with ThreadPoolExecutor(max_workers=workers) as pool:
    futures: dict[Future, InterventionRecord] = {}
    for intervention in interventions:
        effective_date = conference_date or intervention.conference_date
        if not effective_date:
            failed += 1
            continue
        future = pool.submit(_embed_one, intervention, effective_date, ollama_base_url, ollama_model)
        futures[future] = intervention

    for future in as_completed(futures):
        intervention = futures[future]
        payload, embedding = future.result()
        if embedding is None:
            failed += 1
        else:
            try:
                effective_date = conference_date or intervention.conference_date
                _store_gold(cur, intervention, effective_date, payload, embedding)
            except psycopg.errors.UniqueViolation:
                logger.warning("Chunk duplicado en Gold, omitido", chunk_key=intervention.intervention_key)
            embedded += 1
        reporter.tick()
```

- Los workers (`_embed_one`) solo tocan `build_embedding_payload`, `build_embedding_text`, `embed_text` (httpx) — nada de DB.
- El hilo principal hace `_store_gold` y `reporter.tick()`, que son thread-safe porque solo el los ejecuta.
- `reporter.tick()` cuenta intervenciones COMPLETADAS (embedding listo, insertado o fallido).

**Imports nuevos:** `from concurrent.futures import Future, ThreadPoolExecutor, as_completed`.

### 4. CLI `pipeline enrich`

```python
workers: int = typer.Option(default=1, help="Parallel Ollama embedding workers")
```

Pasa `workers=workers` a `service.run(...)`.

### 5. `EnrichService.run`

```python
def run(self, dry_run: bool = False, conference_date: str | None = None, clean: bool = False, workers: int = 1) -> dict:
```

Pasa `workers=workers` a `enrich_interventions(...)`.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/pipeline/enrichment.py` | + `_embed_one`, + `_store_gold`, `enrich_interventions` con `workers` y path paralelo |
| `backend/src/lakehouse/services/enrich_service.py` | `run()` acepta `workers` y lo propaga |
| `backend/src/lakehouse/cli.py` | `--workers` en comando `enrich` |
| `backend/tests/test_pipeline/test_enrichment.py` | Tests `_embed_one`, `_store_gold`, path paralelo |
| `backend/tests/test_services/test_enrich_service.py` | Tests propagacion de `workers` |
| `backend/tests/test_cli.py` | Test `--workers` en CLI |

## Verificacion

1. `ruff check` + `ruff format` en archivos modificados
2. `ty check src/` sin errores
3. `pytest --cov=src --cov-fail-under=90` (260+ tests)
4. Manual: `make pipeline-enrich ARGS="--clean --workers 4"` reduce el tiempo ~4x vs `workers 1`, con los mismos `embedded`/`failed`

## No incluido en este feature

- Paralelizar los INSERTs a Postgres (los workers solo tocan Ollama)
- Batching de embeddings en una sola request a Ollama (`input: [text1, text2, ...]`)
- Concurrencia asincrona con httpx async/await
- Limpieza del modelo de embedding o el payload (feature anterior)
- Cambios al evaluador RAG o al chat
