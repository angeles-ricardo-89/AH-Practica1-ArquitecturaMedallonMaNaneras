# Ventana Deslizante por Conferencia en Gold

## Problema

El RAG tiene fidelidad ~31% con relevancia ~99%. La causa raiz es un mismatch de granularidad:

1. **Las referencias del golden dataset son sintesis** (p.ej. "la estrategia se basa en coordinacion + atencion a causas + Guardia Nacional") que combinan hechos de multiples intervenciones.
2. **Cada chunk en Gold es un Q&A individual** (~89 chars promedio). El LLM recibe 8 fragmentos inconexos sin la narrativa completa.
3. **El corpus esta contaminado:** 47.7% de los chunks tienen < 50 caracteres ("Sí, seguridad.", "¡Seguridad!", "…de seguridad."). La similitud cosena premia estos fragmentos que repiten la keyword sobre los chunks sustanciales.

**Evidencia experimental:** filtrar chunks < 50 caracteres de la busqueda sube la fidelidad de 31.33% → 40.10% (+8.8 puntos). El filtro solo no basta: el LLM sigue viendo Q&A individuales sin contexto de la conferencia.

**Restriccion del modelo:** el modelo de embedding (`embeddinggemma`, gemma3) tiene contexto de **2048 tokens**. Una conferencia completa no cabe (mediana ~750 tokens, max ~5,168 tokens).

## Solucion

Construir **ventanas deslizantes por conferencia** en la capa Gold: agrupar las intervenciones consecutivas de una conferencia en ventanas de ≤1600 tokens con solapamiento de ~200 tokens. Cada ventana se convierte en UN chunk de Gold con la narrativa completa. Las intervenciones cortas (< 50 chars) se excluyen ANTES de construir la ventana.

**Principio:** Silver sigue siendo la verdad de las intervenciones individuales (auditoria, DLQ intactos). La ventana es un artefacto de busqueda puro de la capa Gold.

## Diseno

### 1. Constantes y funcion `build_windows` (en `enrichment.py`)

**Import nuevo:** `from lakehouse.services.token_estimator import estimate_tokens`

```python
WINDOW_MAX_TOKENS = 1600   # margen bajo el contexto de 2048 del modelo
WINDOW_OVERLAP_TOKENS = 200
MIN_CHUNK_LENGTH = 50      # filtro de fragmentos cortos

def build_windows(
    interventions: list[InterventionRecord],
    max_tokens: int = WINDOW_MAX_TOKENS,
    overlap_tokens: int = WINDOW_OVERLAP_TOKENS,
) -> list[list[InterventionRecord]]:
    """Agrupa intervenciones consecutivas en ventanas de <= max_tokens con solapamiento.

    Entrada: intervenciones de UNA conferencia, ordenadas por chunk_index,
    ya filtradas (>= MIN_CHUNK_LENGTH chars).
    """
    windows: list[list[InterventionRecord]] = []
    current: list[InterventionRecord] = []
    current_tokens = 0
    overlap_buf: list[InterventionRecord] = []

    for iv in interventions:
        t = estimate_tokens(iv.text)
        if current and current_tokens + t > max_tokens:
            windows.append(current)
            overlap_buf, acc = [], 0
            for it in reversed(current):
                acc += estimate_tokens(it.text)
                overlap_buf.insert(0, it)
                if acc >= overlap_tokens:
                    break
            current, current_tokens = list(overlap_buf), acc
        current.append(iv)
        current_tokens += t
    if current:
        windows.append(current)
    return windows
```

### 2. Helpers de ventana

```python
def build_window_text(interventions: list[InterventionRecord]) -> str:
    """Narrativa completa de la ventana: pregunta activa + participante + texto."""
    blocks = []
    for iv in interventions:
        if iv.pregunta_activa:
            blocks.append(f"P: {iv.pregunta_activa}\n{iv.participant}: {iv.text}")
        else:
            blocks.append(f"{iv.participant}: {iv.text}")
    return "\n\n".join(blocks)


def build_window_key(conference_id: str, window_index: int, window_text: str) -> str:
    """chunk_key determinista e idempotente para la ventana."""
    h = hashlib.sha256(window_text.encode()).hexdigest()[:6]
    return f"{conference_id}_w{window_index:03d}_{h}"
```

### 3. `WindowRecord` (esquema gold)

```python
class WindowRecord(BaseModel):
    chunk_key: str = Field(..., min_length=1)
    conference_id: str = Field(..., min_length=1)
    conference_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    participant: str = Field(default="DESCONOCIDO")
    pregunta_activa: str = Field(default="")
    text: str = Field(..., min_length=1)  # narrativa completa (build_window_text)
    url: str = Field(default="")
    window_index: int = Field(..., ge=0)
```

**Nota:** `pregunta_activa` de la ventana es `""` (vacio). La narrativa con todas las `P:` vive dentro de `text`.

**Nota:** `text` es requerido (`min_length=1`): la ventana siempre tiene contenido narrativo porque se construye solo con intervenciones filtradas (>= 50 chars). `conference_date` es requerido: `build_windows_from_conference` siempre lo pasa, igual que `RagCorpusRecord`. No se referencia `ConferenceRecord`; la ventana ya lleva fecha y url en campos propios.

### 4. `build_windows_from_conference` (orquestador)

En `enrich_service.py`, agrupa por conferencia, filtra cortos, construye ventanas y las convierte en `WindowRecord`:

```python
def build_windows_from_conference(
    interventions: list[InterventionRecord],
    conference_date: str,
) -> list[WindowRecord]:
    """Filtra cortos, ordena por chunk_index, construye ventanas y las tipa."""
    filtered = sorted(
        (i for i in interventions if len(i.text) >= MIN_CHUNK_LENGTH),
        key=lambda i: i.chunk_index,
    )
    if not filtered:
        return []
    windows = build_windows(filtered)
    records = []
    for idx, window in enumerate(windows):
        text = build_window_text(window)
        records.append(
            WindowRecord(
                chunk_key=build_window_key(window[0].conference_id, idx, text),
                conference_id=window[0].conference_id,
                conference_date=conference_date,
                participant=window[0].participant,
                pregunta_activa="",
                text=text,
                url=window[0].url,
                window_index=idx,
            )
        )
    return records
```

### 5. Cambios en `enrich_service.run`

- Lee intervenciones agrupadas por conferencia (SQL agrega `ORDER BY i.conference_id, i.chunk_index`)
- Por cada conferencia, llama `build_windows_from_conference` → lista de `WindowRecord`
- Pasa las ventanas a `enrich_interventions`
- Los `InterventionRecord` individuales ya no se pasan; se pasan `WindowRecord`

### 6. Cambios en `enrich_interventions`

- La firma acepta `list[WindowRecord]` en vez de `list[InterventionRecord]`
- El flujo por ventana: el texto a embedder ES `record.text` (la narrativa completa con `P:` y participantes inline, ya sin metadata de Q&A individual). NO se usa `build_embedding_payload` ni `build_embedding_text` (esos son para `InterventionRecord` con pregunta_activa separada). `embed_text(record.text, ...)`, luego `_store_gold`
- El INSERT a Gold usa: `chunk_key`, `conference_id`, `conference_date`, `participant`, `chunk_text=record.text`, `payload=record.text` (mismo texto, sin metadata extra), `url`, `pregunta_activa=""`, `embedding`
- `_store_gold` se adapta para aceptar `WindowRecord` (params: chunk_key, conference_id, effective_date, participant, text, payload=text, url, pregunta_activa="", embedding)
- `_embed_one` se adapta para aceptar `WindowRecord` (embedde `record.text` directamente)
- El path `workers` (ThreadPoolExecutor) sigue igual: cada ventana se embedde como un chunk

### 7. Filtro en la busqueda (`search_gold_corpus`)

Se agrega `WHERE LENGTH(chunk_text) >= MIN_CHUNK_LENGTH` a la query de busqueda. Es un doble seguro: las ventanas ya indexadas se vuelven a filtrar en busqueda, y cubre el caso de chunks legacy (si no se re-indexa con `--clean`).

## Impacto en el corpus

| Metrica | Hoy | Con ventanas |
|---------|-----|--------------|
| Chunks | 38,782 | ~7,000-9,000 (est.) |
| Chunk promedio | 89 chars | ~800-1,500 chars |
| Conferencia mediana | 39 chunks fragmentados | 1 chunk coherente |

**Costo de re-indexacion:** requiere `make pipeline-enrich ARGS="--clean"` para regenerar Gold con las ventanas. La re-indexacion con `--workers 4` es ~4x mas rapida (feature previa).

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/schemas/gold.py` | + `WindowRecord` |
| `backend/src/lakehouse/pipeline/enrichment.py` | + `build_windows`, + `build_window_text`, + `build_window_key`, adaptar `_embed_one`, `_store_gold`, `enrich_interventions` |
| `backend/src/lakehouse/services/enrich_service.py` | + `build_windows_from_conference`, agrupar por conferencia en `run()` |
| `backend/src/lakehouse/services/rag_search.py` | + filtro `LENGTH(chunk_text) >= MIN_CHUNK_LENGTH` en query |
| `backend/tests/test_pipeline/test_enrichment.py` | Tests de `build_windows`, `build_window_text`, `build_window_key` |
| `backend/tests/test_services/test_enrich_service.py` | Tests de `build_windows_from_conference` |
| `backend/tests/test_services/test_rag_search.py` | Test del filtro en query |

## Verificacion

1. `ruff check` + `ruff format` en archivos modificados
2. `ty check src/` sin errores
3. `pytest --cov=src --cov-fail-under=90` (271+ tests)
4. Manual: `make pipeline-enrich ARGS="--clean --workers 4"` regenera Gold con ventanas
5. `make evaluate-rag` mide fidelidad post-cambio (baseline: 31.33%, con filtro solo: 40.10%)

## No incluido en este feature

- Cambios al parseo de Silver (las intervenciones individuales se mantienen)
- Cambios al modelo de embedding (contexto 2048 sigue siendo el limite)
- Hybrid search (BM25 + vector) — feature futura si la ventana no basta
- Reescribir el golden dataset para que las referencias sean mono-conferencia
- Cambios al chat API o al context builder
