# Ventana Deslizante por Conferencia en Gold — Plan de Implementacion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar los chunks de Q&A individuales por ventanas deslizantes por conferencia (≤1600 tokens con solapamiento de 200) en la capa Gold, filtrando intervenciones < 50 chars, para que el LLM reciba la narrativa completa de la conferencia.

**Architecture:** Silver sigue intacto (verdad de intervenciones individuales). `enrich_service` agrupa intervenciones por conferencia, filtra cortos, construye ventanas (`build_windows`), y cada ventana se vuelve UN chunk en Gold. `enrich_interventions` y sus helpers `_embed_one`/`_store_gold` pasan de operar sobre `InterventionRecord` a `WindowRecord`. El path `workers` (ThreadPoolExecutor) se mantiene: cada ventana se embedde como un chunk.

**Tech Stack:** Python 3.13, Pydantic, psycopg, DuckDB, Ollama (embeddinggemma, ctx 2048)

---

### File Structure

| Archivo | Accion | Responsabilidad |
|---------|--------|-----------------|
| `backend/src/lakehouse/schemas/gold.py` | Modify | + `WindowRecord` |
| `backend/src/lakehouse/pipeline/enrichment.py` | Modify | + `build_windows`, + `build_window_text`, + `build_window_key`, adaptar `_embed_one`/`_store_gold`/`enrich_interventions`, `- build_embedding_payload`/`- build_embedding_text` |
| `backend/src/lakehouse/services/enrich_service.py` | Modify | + `build_windows_from_conference`, agrupar por conferencia en `run()` |
| `backend/src/lakehouse/services/rag_search.py` | Modify | + filtro `LENGTH(chunk_text) >= MIN_CHUNK_LENGTH` en query |
| `backend/tests/test_pipeline/test_enrichment.py` | Modify | Tests `build_windows`/`build_window_text`/`build_window_key`, reescribir `TestEmbedOne`/`TestStoreGold`/`TestEnrichInterventions`/`TestEnrichInterventionsParallel` a `WindowRecord`, `- TestBuildEmbeddingPayload`/`- TestBuildEmbeddingText` |
| `backend/tests/test_services/test_enrich_service.py` | Modify | Tests de `build_windows_from_conference` + `run()` con ventanas |
| `backend/tests/test_services/test_rag_search.py` | Modify | Test del filtro en query |

**Decisiones de diseño clave:**
- `_embed_one(record, ollama_base_url, ollama_model) -> list[float] | None`: embedde `record.text` directamente, retorna embedding o None. Ya NO retorna `(payload, embedding)` porque la ventana no tiene payload de metadata (`payload == text`). El warning log usa `chunk_key`.
- `_store_gold(cur, record, effective_date, embedding)`: deriva `payload=record.text` internamente. Ya NO recibe `payload` como parametro.
- `build_embedding_payload` y `build_embedding_text` se ELIMINAN: quedan como codigo muerto al pasar a ventanas (el embedding de ventana es `record.text` directo).

---

### Task 1: Commit del fix pendiente en `_call_ollama_embed`

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py:121`

- [ ] **Step 1: Verificar el diff pendiente**

```bash
cd backend && git diff src/lakehouse/pipeline/enrichment.py
```

Expected: el diff muestra `return embeddings[0]` → `return [float(x) for x in embeddings[0]]` en `_call_ollama_embed`. Este fix garantiza que el embedding de Ollama sea `list[float]`.

- [ ] **Step 2: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py
git commit -m "fix: garantiza list[float] en embedding de Ollama"
```

---

### Task 2: Esquema `WindowRecord` + constantes

**Files:**
- Modify: `backend/src/lakehouse/schemas/gold.py`
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`

- [ ] **Step 1: Agregar `WindowRecord` a gold.py**

En `backend/src/lakehouse/schemas/gold.py`, agrega despues de `RagCorpusRecord`:

```python
class WindowRecord(BaseModel):
    chunk_key: str = Field(..., min_length=1)
    conference_id: str = Field(..., min_length=1)
    conference_date: str = Field(default="", pattern=r"^\d{4}-\d{2}-\d{2}$")
    participant: str = Field(default="DESCONOCIDO")
    pregunta_activa: str = Field(default="")
    text: str = Field(..., min_length=1)
    url: str = Field(default="")
    window_index: int = Field(..., ge=0)
```

- [ ] **Step 2: Agregar constantes e imports a enrichment.py**

En `backend/src/lakehouse/pipeline/enrichment.py`:

1. Cambia el bloque de imports de:
```python
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any
```
a:
```python
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from lakehouse.services.token_estimator import estimate_tokens
```

2. En el bloque `if TYPE_CHECKING:`, agrega `WindowRecord`:
```python
if TYPE_CHECKING:
    from lakehouse.schemas.silver import InterventionRecord
    from lakehouse.schemas.gold import WindowRecord
```

3. Agrega las constantes despues de `logger = get_logger(__name__, layer="gold")`:
```python
WINDOW_MAX_TOKENS = 1600
WINDOW_OVERLAP_TOKENS = 200
MIN_CHUNK_LENGTH = 50
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/schemas/gold.py backend/src/lakehouse/pipeline/enrichment.py
git commit -m "feat: agrega WindowRecord y constantes de ventana"
```

---

### Task 3: Funciones de ventana

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Agregar tests de las funciones de ventana**

Agrega al final de `backend/tests/test_pipeline/test_enrichment.py`:

```python
class TestBuildWindows:
    def _iv(self, i: int, text: str, conference_id: str = "conf1") -> InterventionRecord:
        return InterventionRecord(
            intervention_key=f"k{i:03d}",
            conference_id=conference_id,
            participant="PRESIDENTA",
            text=text,
            pregunta_activa=f"Pregunta {i}",
            chunk_index=i,
            url="https://example.com",
            conference_date="2025-03-01",
        )

    def test_single_window_under_max_tokens(self) -> None:
        from lakehouse.pipeline.enrichment import build_windows

        ivs = [self._iv(0, "Hola."), self._iv(1, "Mundo."), self._iv(2, "Test.")]
        windows = build_windows(ivs, max_tokens=1600)
        assert len(windows) == 1
        assert len(windows[0]) == 3

    def test_splits_into_multiple_windows_with_overlap(self) -> None:
        from lakehouse.pipeline.enrichment import build_windows

        # 6 textos de ~200 tokens cada uno, max_tokens=500 → varias ventanas
        long_text = "palabra " * 200  # ~200 tokens
        ivs = [self._iv(i, long_text) for i in range(6)]
        windows = build_windows(ivs, max_tokens=500, overlap_tokens=50)
        assert len(windows) > 1
        # verificar solapamiento: ultima intervencion de la ventana 0 esta en ventana 1
        last_of_first = windows[0][-1].intervention_key
        first_keys_second = {iv.intervention_key for iv in windows[1]}
        assert last_of_first in first_keys_second

    def test_empty_list_returns_empty(self) -> None:
        from lakehouse.pipeline.enrichment import build_windows

        assert build_windows([]) == []

    def test_single_intervention_returns_one_window(self) -> None:
        from lakehouse.pipeline.enrichment import build_windows

        ivs = [self._iv(0, "Hola.")]
        windows = build_windows(ivs)
        assert len(windows) == 1
        assert len(windows[0]) == 1


class TestBuildWindowText:
    def test_includes_pregunta_and_participant(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_text

        iv = InterventionRecord(
            intervention_key="k000",
            conference_id="conf1",
            participant="PRESIDENTA",
            text="Avanzamos en paneles.",
            pregunta_activa="Como va la reforma?",
            chunk_index=0,
            url="https://example.com",
        )
        text = build_window_text([iv])
        assert "P: Como va la reforma?" in text
        assert "PRESIDENTA: Avanzamos en paneles." in text

    def test_without_pregunta_omits_p_label(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_text

        iv = InterventionRecord(
            intervention_key="k000",
            conference_id="conf1",
            participant="SECRETARIO",
            text="Se implemento la estrategia.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )
        text = build_window_text([iv])
        assert text == "SECRETARIO: Se implemento la estrategia."
        assert "P:" not in text

    def test_multiple_interventions_separated_by_blank_line(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_text

        ivs = [
            InterventionRecord(
                intervention_key="k000", conference_id="c", participant="P1",
                text="Uno.", pregunta_activa="", chunk_index=0, url="",
            ),
            InterventionRecord(
                intervention_key="k001", conference_id="c", participant="P2",
                text="Dos.", pregunta_activa="Q?", chunk_index=1, url="",
            ),
        ]
        text = build_window_text(ivs)
        assert text.count("\n\n") == 1


class TestBuildWindowKey:
    def test_deterministic_for_same_text(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_key

        k1 = build_window_key("conf1", 0, "mismo texto")
        k2 = build_window_key("conf1", 0, "mismo texto")
        assert k1 == k2

    def test_differs_for_index(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_key

        k1 = build_window_key("conf1", 0, "texto")
        k2 = build_window_key("conf1", 1, "texto")
        assert k1 != k2

    def test_contains_conference_and_index(self) -> None:
        from lakehouse.pipeline.enrichment import build_window_key

        key = build_window_key("conf1", 2, "texto")
        assert key.startswith("conf1_w002_")
        assert len(key) == len("conf1_w002_") + 6
```

**Nota sobre imports:** el test file ya importa `build_embedding_text` en el bloque top-level (de features anteriores). `build_windows`, `build_window_text`, `build_window_key` se importan inline en cada test por ahora; si ruff PLC0415 los marca, muevelos al import top-level.

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestBuildWindows tests/test_pipeline/test_enrichment.py::TestBuildWindowText tests/test_pipeline/test_enrichment.py::TestBuildWindowKey -v
```

Expected: FAIL con `ImportError` (funciones no existen).

- [ ] **Step 3: Implementar las funciones**

En `backend/src/lakehouse/pipeline/enrichment.py`, agrega despues de `build_embedding_text` (linea ~38):

```python
def build_window_text(interventions: list[InterventionRecord]) -> str:
    blocks = []
    for iv in interventions:
        if iv.pregunta_activa:
            blocks.append(f"P: {iv.pregunta_activa}\n{iv.participant}: {iv.text}")
        else:
            blocks.append(f"{iv.participant}: {iv.text}")
    return "\n\n".join(blocks)


def build_window_key(conference_id: str, window_index: int, window_text: str) -> str:
    h = hashlib.sha256(window_text.encode()).hexdigest()[:6]
    return f"{conference_id}_w{window_index:03d}_{h}"


def build_windows(
    interventions: list[InterventionRecord],
    max_tokens: int = WINDOW_MAX_TOKENS,
    overlap_tokens: int = WINDOW_OVERLAP_TOKENS,
) -> list[list[InterventionRecord]]:
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

**Import:** `hashlib` — verifica si esta importado en enrichment.py. Si no, agrega `import hashlib` al inicio.

- [ ] **Step 4: Verificar que pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestBuildWindows tests/test_pipeline/test_enrichment.py::TestBuildWindowText tests/test_pipeline/test_enrichment.py::TestBuildWindowKey -v
```

Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "feat: funciones de ventana deslizante (build_windows, build_window_text, build_window_key)"
```

---

### Task 4: Adaptar `_embed_one` y `_store_gold` a `WindowRecord`

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

- [ ] **Step 1: Reescribir tests de `_embed_one` y `_store_gold`**

Reemplaza la clase `TestEmbedOne` existente por:

```python
class TestEmbedOne:
    def test_returns_embedding_on_success(self) -> None:
        from lakehouse.pipeline.enrichment import _embed_one
        from lakehouse.schemas.gold import WindowRecord

        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text="P: Como va la reforma?\nPRESIDENTA: Avanzamos en paneles.",
            url="https://example.com",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.return_value = [0.1] * 768
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding == [0.1] * 768
        mock_embed.assert_called_once_with(
            "P: Como va la reforma?\nPRESIDENTA: Avanzamos en paneles.",
            "http://localhost:11434",
            "nomic-embed-text",
        )

    def test_returns_none_on_connection_error(self) -> None:
        from lakehouse.pipeline.enrichment import _embed_one
        from lakehouse.schemas.gold import WindowRecord

        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="P",
            text="texto",
            url="",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ConnectionError("Ollama embedding failed after 3 retries")
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding is None

    def test_returns_none_on_value_error(self) -> None:
        from lakehouse.pipeline.enrichment import _embed_one
        from lakehouse.schemas.gold import WindowRecord

        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="P",
            text="texto",
            url="",
            window_index=0,
        )
        with patch("lakehouse.pipeline.enrichment.embed_text") as mock_embed:
            mock_embed.side_effect = ValueError("Ollama returned empty embeddings")
            embedding = _embed_one(record, "http://localhost:11434", "nomic-embed-text")
        assert embedding is None
```

Reemplaza la clase `TestStoreGold` existente por:

```python
class TestStoreGold:
    def test_executes_insert_with_window_params(self) -> None:
        from lakehouse.pipeline.enrichment import _store_gold
        from lakehouse.schemas.gold import WindowRecord

        cur = MagicMock()
        record = WindowRecord(
            chunk_key="conf1_w000_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant="PRESIDENTA",
            text="P: Q?\nPRESIDENTA: R.",
            url="https://example.com",
            window_index=0,
        )
        _store_gold(cur, record, "2025-03-01", [0.1] * 768)
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO gold.rag_corpus" in sql
        assert params[0] == "conf1_w000_abc123"
        assert params[2] == "2025-03-01"
        assert params[4] == "P: Q?\nPRESIDENTA: R."   # chunk_text
        assert params[5] == "P: Q?\nPRESIDENTA: R."   # payload == text
        assert params[7] == ""                        # pregunta_activa vacia
        assert params[8] == [0.1] * 768
```

**Nota:** el test `test_single_intervention_stored_correctly` (en TestEnrichInterventions) que verificaba params[7]==pregunta_activa y params[8]==embedding tambien se actualiza en Task 5. No lo toques en este task aun.

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEmbedOne tests/test_pipeline/test_enrichment.py::TestStoreGold -v
```

Expected: FAIL (firmas nuevas no coinciden).

- [ ] **Step 3: Reescribir `_embed_one` y `_store_gold`**

En `backend/src/lakehouse/pipeline/enrichment.py`, reemplaza las funciones `_embed_one` y `_store_gold` (lineas 41-91) por:

```python
def _embed_one(
    record: WindowRecord,
    ollama_base_url: str,
    ollama_model: str,
) -> list[float] | None:
    try:
        return embed_text(record.text, ollama_base_url, ollama_model)
    except (ConnectionError, ValueError) as e:
        logger.warning(
            "embed_text falló",
            error=str(e),
            chunk_key=record.chunk_key,
        )
        return None


def _store_gold(
    cur: Any,
    record: WindowRecord,
    effective_date: str,
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
            record.chunk_key,
            record.conference_id,
            effective_date,
            record.participant,
            record.text,
            record.text,
            record.url,
            record.pregunta_activa,
            embedding,
        ),
    )
```

- [ ] **Step 4: Eliminar `build_embedding_payload` y `build_embedding_text`**

En `backend/src/lakehouse/pipeline/enrichment.py`, elimina las funciones `build_embedding_payload` (lineas ~21-30) y `build_embedding_text` (lineas ~34-38). Quedan como codigo muerto.

En `backend/tests/test_pipeline/test_enrichment.py`, elimina las clases `TestBuildEmbeddingPayload` y `TestBuildEmbeddingText`, y remueve `build_embedding_text` del import top-level.

- [ ] **Step 5: Verificar que pasan los tests de helpers**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestEmbedOne tests/test_pipeline/test_enrichment.py::TestStoreGold -v
```

Expected: 4 passed.

**Nota:** `TestEnrichInterventions` y `TestEnrichInterventionsParallel` aun fallaran (usan InterventionRecord y _embed_one con firma vieja). Se corrigen en Task 5. No los corrijas aqui.

- [ ] **Step 6: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "refactor: _embed_one y _store_gold operan sobre WindowRecord"
```

---

### Task 5: Adaptar `enrich_interventions` a `list[WindowRecord]`

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py`
- Test: `backend/tests/test_pipeline/test_enrichment.py`

**Objetivo:** `enrich_interventions` recibe `list[WindowRecord]`, cada ventana = 1 chunk. Se reescriben `TestEnrichInterventions` y `TestEnrichInterventionsParallel` para usar `WindowRecord`.

- [ ] **Step 1: Reescribir tests de `TestEnrichInterventions`**

Agrega un fixture helper de WindowRecord al inicio de `backend/tests/test_pipeline/test_enrichment.py` (despues de los imports, dentro de la clase `TestEnrichInterventions`):

```python
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
```

Reemplaza los tests que usan `InterventionRecord` con `sample_intervention` por versiones con `self._window(i)`:

- `test_uses_record_conference_date_when_param_none`: crea un `WindowRecord` con `conference_date="2025-03-01"`, llama `enrich_interventions(interventions=[record], conference_date=None, ...)`, verifica params[2]=="2025-03-01".
- `test_param_overrides_record_conference_date`: record con date "2025-03-01", param "2024-10-01", verifica params[2]=="2024-10-01".
- `test_record_without_date_is_failed`: WindowRecord sin fecha valida → embedded=0, failed=1. (Crea un WindowRecord con conference_date="" — el `effective_date = conference_date or record.conference_date` da "" que es falsy → failed.)
- `test_single_intervention_stored_correctly`: reemplaza el test completo por:

```python
    @patch("lakehouse.pipeline.enrichment.embed_text")
    @patch("lakehouse.pipeline.enrichment.psycopg.connect")
    def test_single_intervention_stored_correctly(
        self,
        mock_connect: MagicMock,
        mock_embed: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_embed.return_value = [0.5] * 768

        record = self._window(0, text="P: Q?\nPRESIDENTA: R.")

        result = enrich_interventions(
            windows=[record],
            conference_date="2024-10-01",
            pg_conn_str="postgresql://user:pass@localhost:5433/mydb",
            ollama_base_url="http://localhost:11434",
            ollama_model="nomic-embed-text",
        )

        assert result["total"] == 1
        assert result["embedded"] == 1
        assert result["failed"] == 0

        execute_args = mock_cursor.execute.call_args_list
        insert_call = None
        for call in execute_args:
            sql = call[0][0]
            if "INSERT INTO gold.rag_corpus" in sql:
                insert_call = call
                break

        assert insert_call is not None
        params = insert_call[0][1]
        assert params[0] == record.chunk_key
        assert params[1] == record.conference_id
        assert params[2] == "2024-10-01"
        assert params[3] == record.participant
        assert params[4] == record.text
        assert params[5] == record.text   # payload == text para ventanas
        assert params[6] == record.url
        assert params[7] == ""            # pregunta_activa vacia
        assert params[8] == [0.5] * 768

        mock_embed.assert_called_once_with(
            "P: Q?\nPRESIDENTA: R.", "http://localhost:11434", "nomic-embed-text"
        )
```

**Nota:** este test ya no usa `build_embedding_text` ni `sample_intervention`. El `pregunta_activa` del record es "" (por eso params[7]=="" y el embed es `record.text` directo).
- `test_partial_embedding_failure_logs_and_continues`: usa 3 WindowRecords, side_effect [embedding, ConnectionError, embedding] → embedded=2, failed=1.
- `test_empty_interventions_list`: sin cambios (lista vacia).
- `test_on_conflict_updates_metadata` y `test_on_conflict_do_nothing`: usan `self._window(0)`.
- `test_unique_violation_logs_and_counts_embedded`: usa `self._window(0)`.

**El fixture `sample_intervention` deja de usarse en `TestEnrichInterventions`. Si ya no se usa en ninguna parte del archivo, puedes eliminarlo del modulo (o dejarlo si otros tests lo usan — `TestBuildEmbeddingPayload` se elimina en Task 4, verifica que no haya usos restantes).**

- [ ] **Step 2: Reescribir `TestEnrichInterventionsParallel`**

Reemplaza los records `InterventionRecord(...)` por `WindowRecord`:

```python
    def _window(self, i: int, text: str) -> WindowRecord:
        return WindowRecord(
            chunk_key=f"conf1_w{i:03d}_abc123",
            conference_id="conf1",
            conference_date="2025-03-01",
            participant=f"P {i}",
            text=text,
            url="",
            window_index=i,
        )
```

Usa `[self._window(i, f"Texto {i}") for i in range(5)]` etc. Las aserciones de conteo quedan iguales. El test de concurrencia (`test_workers_runs_embeddings_in_parallel_threads`) usa el mismo patrón de barrier; solo cambia la construccion de records.

- [ ] **Step 3: Adaptar `enrich_interventions`**

En `backend/src/lakehouse/pipeline/enrichment.py`, cambia:

1. La firma de `enrich_interventions` (linea ~207): el tipo del primer parametro pasa de `list[InterventionRecord]` a `list[WindowRecord]`:

```python
def enrich_interventions(
    windows: list[WindowRecord],
    conference_date: str | None,
    pg_conn_str: str,
    ollama_base_url: str,
    ollama_model: str,
    workers: int = 1,
) -> dict:
    total = len(windows)
```

2. En el path paralelo, el loop usa `record` (WindowRecord) y la firma de `_embed_one`/`_store_gold` nuevas:

```python
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures: dict[Future, tuple[WindowRecord, str]] = {}
                for record in windows:
                    effective_date = conference_date or record.conference_date
                    if not effective_date:
                        logger.error(
                            "Intervención sin fecha de conferencia, omitida",
                            chunk_key=record.chunk_key,
                        )
                        failed += 1
                        reporter.tick()
                        continue
                    future = pool.submit(
                        _embed_one,
                        record,
                        ollama_base_url,
                        ollama_model,
                    )
                    futures[future] = (record, effective_date)

                for future in as_completed(futures):
                    record, effective_date = futures[future]
                    embedding = future.result()
                    if embedding is None:
                        logger.error(
                            "Error al generar embedding",
                            chunk_key=record.chunk_key,
                        )
                        failed += 1
                    else:
                        logger.info(
                            "Embedding generado para chunk",
                            chunk_key=record.chunk_key,
                            participant=record.participant,
                            dim=len(embedding),
                        )
                        try:
                            _store_gold(cur, record, effective_date, embedding)
                        except psycopg.errors.UniqueViolation:
                            logger.warning(
                                "Chunk duplicado en Gold, omitido",
                                chunk_key=record.chunk_key,
                            )
                        embedded += 1
                    reporter.tick()
        else:
            for record in windows:
                effective_date = conference_date or record.conference_date
                if not effective_date:
                    logger.error(
                        "Intervención sin fecha de conferencia, omitida",
                        chunk_key=record.chunk_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                embedding = _embed_one(record, ollama_base_url, ollama_model)
                if embedding is None:
                    logger.error(
                        "Error al generar embedding",
                        chunk_key=record.chunk_key,
                    )
                    failed += 1
                    reporter.tick()
                    continue
                logger.info(
                    "Embedding generado para chunk",
                    chunk_key=record.chunk_key,
                    participant=record.participant,
                    dim=len(embedding),
                )
                try:
                    _store_gold(cur, record, effective_date, embedding)
                except psycopg.errors.UniqueViolation:
                    logger.warning(
                        "Chunk duplicado en Gold, omitido",
                        chunk_key=record.chunk_key,
                    )
                embedded += 1
                reporter.tick()
```

**Nota:** `effective_date` se calcula ANTES de submit y se guarda en el futures dict (patron de la feature previa). El `conference_date` sigue viniendo del parametro o de `record.conference_date`.

- [ ] **Step 4: Verificar que pasan todos los tests de enrichment**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py -v
```

Expected: todos pasan (TestBuildWindows, TestBuildWindowText, TestBuildWindowKey, TestEmbedOne, TestStoreGold, TestEnrichInterventions, TestEnrichInterventionsParallel).

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "refactor: enrich_interventions procesa ventanas (WindowRecord)"
```

---

### Task 6: `build_windows_from_conference` y agrupacion en `enrich_service`

**Files:**
- Modify: `backend/src/lakehouse/services/enrich_service.py`
- Test: `backend/tests/test_services/test_enrich_service.py`

- [ ] **Step 1: Agregar tests**

Agrega al final de `backend/tests/test_services/test_enrich_service.py`:

```python
class TestBuildWindowsFromConference:
    def test_filters_short_sorts_and_builds_windows(self) -> None:
        from lakehouse.services.enrich_service import build_windows_from_conference

        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}", conference_id="c1", participant="P",
                text="Sí, seguridad." if i == 1 else "Texto largo " * 20,
                pregunta_activa="", chunk_index=i, url="https://u",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert len(windows) == 1
        assert windows[0].conference_id == "c1"
        assert windows[0].chunk_key.startswith("c1_w000_")
        assert "Sí, seguridad." not in windows[0].text  # filtrado

    def test_all_short_returns_empty(self) -> None:
        from lakehouse.services.enrich_service import build_windows_from_conference

        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}", conference_id="c1", participant="P",
                text="Sí.", pregunta_activa="", chunk_index=i, url="",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert windows == []

    def test_empty_input_returns_empty(self) -> None:
        from lakehouse.services.enrich_service import build_windows_from_conference

        assert build_windows_from_conference([], conference_date="2025-03-01") == []

    def test_sorts_by_chunk_index(self) -> None:
        from lakehouse.services.enrich_service import build_windows_from_conference

        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}", conference_id="c1", participant="P",
                text="Texto " + str(3 - i), pregunta_activa="", chunk_index=3 - i, url="",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert windows[0].text.startswith("P: \nP: Texto 1")
```

**Nota:** el `text` de la ventana inicia con `"P: \n"` porque `pregunta_activa=""` es falsy → se omite el bloque P:. El primer bloque es `"P: Texto 3"`. Ajusta la aserción segun el output real de `build_window_text`. Si es confuso, verifica el output con un print temporal.

- [ ] **Step 2: Verificar que fallan**

```bash
cd backend && uv run pytest tests/test_services/test_enrich_service.py::TestBuildWindowsFromConference -v
```

Expected: FAIL con `ImportError`.

- [ ] **Step 3: Implementar `build_windows_from_conference`**

En `backend/src/lakehouse/services/enrich_service.py`, agrega al inicio (despues de los imports):

```python
from lakehouse.pipeline.enrichment import (
    MIN_CHUNK_LENGTH,
    build_window_key,
    build_window_text,
    build_windows,
)
from lakehouse.schemas.gold import WindowRecord


def build_windows_from_conference(
    interventions: list[InterventionRecord],
    conference_date: str,
) -> list[WindowRecord]:
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

- [ ] **Step 4: Adaptar `EnrichService.run`**

En `backend/src/lakehouse/services/enrich_service.py`, `run()` actualmente:

1. Lee todas las intervenciones con `SELECT i.intervention_key, i.conference_id, i.participant, i.text, i.pregunta_activa, i.chunk_index, i.url, c.date AS conference_date FROM silver.interventions i LEFT JOIN silver.conferences c ...`
2. Construye `interventions` (lista de `InterventionRecord`)
3. Llama `enrich_interventions(interventions=interventions, ...)`

Cambia a: agrupar por conferencia, construir ventanas, y pasar `windows` a `enrich_interventions`:

```python
        rows = self._conn.execute(
            """
            SELECT i.conference_id, i.participant, i.text,
                   i.pregunta_activa, i.chunk_index, i.url, c.date AS conference_date
            FROM silver.interventions i
            LEFT JOIN silver.conferences c ON c.conference_id = i.conference_id
            ORDER BY i.conference_id, i.chunk_index
            """
        ).fetchall()
        self._conn.close()

        interventions = [
            InterventionRecord(
                conference_id=r[0],
                participant=r[1],
                text=r[2],
                pregunta_activa=r[3],
                chunk_index=r[4],
                url=r[5],
                conference_date=r[6],
                intervention_key=f"{r[0]}_{r[4]:03d}",  # key sintetico no usado por ventanas
            )
            for r in rows
        ]

        if not interventions:
            self._logger.warning("No hay intervenciones en Silver para enriquecer")
            return {"embedded": 0, "failed": 0, "total": 0}
        ...
        # despues del bloque clean y dry_run:
        windows: list[WindowRecord] = []
        for conf_id in {i.conference_id for i in interventions}:
            group = [i for i in interventions if i.conference_id == conf_id]
            date = group[0].conference_date
            if not date:
                self._logger.warning(
                    "Conferencia sin fecha, omitida",
                    conference_id=conf_id,
                )
                continue
            windows.extend(build_windows_from_conference(group, conference_date=date))

        if not windows:
            self._logger.warning("No se construyeron ventanas desde Silver")
            return {"embedded": 0, "failed": 0, "total": 0}
        ...
        return enrich_interventions(
            windows=windows,
            conference_date=None,  # cada ventana lleva su fecha
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
            workers=workers,
        )
```

**Nota sobre `dry_run`:** si `dry_run=True`, retorna `{"embedded": 0, "failed": 0, "total": len(windows)}` en vez de `len(interventions)`.

**Nota sobre `InterventionRecord`:** el campo `intervention_key` es obligatorio en el schema. Se usa un key sintetico `f"{conf_id}_{chunk_index:03d}"` porque el pipeline de ventanas ya no lo necesita (el chunk_key real viene de `build_window_key`). Si `InterventionRecord` requiere que `intervention_key` sea unico, verifica que `(conf_id, chunk_index)` sea unico — es la PK natural de la tabla silver.interventions.

- [ ] **Step 5: Actualizar tests existentes de `TestEnrichService`**

Los tests existentes de `TestEnrichService` mockean `enrich_interventions` y verifican `kwargs`. El test `test_run_propaga_workers_a_enrich_interventions` verifica `kwargs["workers"] == 4` — sigue valido. Pero el mock ahora recibe `windows=windows` en vez de `interventions=interventions`. Verifica que `test_run_no_dry_run_calls_enrich` (que usa `conn.execute.return_value.fetchall.return_value` con 1 fila) siga pasando: la fila es `("k1", "c1", "P", "t", "", 0, "https://example.com", "2025-03-01")` (8 elementos). Con el nuevo SELECT (7 columnas), la fila del mock tiene 8 elementos → el desempaquetado `r[0]...r[6]` ignora el 8vo. Ajusta el mock a 7 columnas o deja el 8vo (se ignora). Prefiere ajustar el mock a 7 columnas:

```python
conn.execute.return_value.fetchall.return_value = [
    ("c1", "P", "t", "", 0, "https://example.com", "2025-03-01"),
]
```

- [ ] **Step 6: Verificar tests**

```bash
cd backend && uv run pytest tests/test_services/test_enrich_service.py -v
```

Expected: todos pasan.

- [ ] **Step 7: Commit**

```bash
git add backend/src/lakehouse/services/enrich_service.py backend/tests/test_services/test_enrich_service.py
git commit -m "feat: enrich_service agrupa por conferencia y construye ventanas"
```

---

### Task 7: Filtro de cortos en la busqueda

**Files:**
- Modify: `backend/src/lakehouse/services/rag_search.py`
- Test: `backend/tests/test_services/test_rag_search.py`

- [ ] **Step 1: Agregar test del filtro**

En `backend/tests/test_services/test_rag_search.py`, en `TestSearchGoldCorpus`, agrega un test:

```python
    @patch("lakehouse.services.rag_search.logger")
    @patch("lakehouse.services.rag_search.psycopg.connect")
    @patch("lakehouse.services.rag_search._embed_query")
    def test_query_filters_short_chunks(
        self,
        mock_embed: MagicMock,
        mock_connect: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_embed.return_value = [0.1] * 768
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        search_gold_corpus("reforma", top_k=5, settings=Settings())

        sql, params = mock_cursor.execute.call_args.args
        assert "LENGTH(chunk_text) >= 50" in sql
```

- [ ] **Step 2: Verificar que falla**

```bash
cd backend && uv run pytest tests/test_services/test_rag_search.py::TestSearchGoldCorpus::test_query_filters_short_chunks -v
```

Expected: FAIL (la query no tiene el filtro).

- [ ] **Step 3: Implementar**

En `backend/src/lakehouse/services/rag_search.py`, en `search_gold_corpus`, agrega la clausula WHERE a la query:

```python
            cur.execute(
                """
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                   1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE LENGTH(chunk_text) >= 50
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding_str, embedding_str, top_k),
            )
```

**Nota:** usa la constante `MIN_CHUNK_LENGTH` si esta importable, o el literal `50`. Para mantener DRY, importa de `enrichment`: `from lakehouse.pipeline.enrichment import MIN_CHUNK_LENGTH` y usa `{MIN_CHUNK_LENGTH}` con f-string. Si causa import circular (enrichment importa de rag_search? no — enrichment no importa rag_search), es seguro. Si prefieres el literal por simplicidad, usa `50`.

- [ ] **Step 4: Verificar que pasa**

```bash
cd backend && uv run pytest tests/test_services/test_rag_search.py -v
```

Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/rag_search.py backend/tests/test_services/test_rag_search.py
git commit -m "feat: filtra chunks cortos en busqueda vectorial"
```

---

### Task 8: Verificacion completa

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

**Atencion:** el refactor elimino `build_embedding_payload` y `build_embedding_text`. Verifica que no haya imports rotos en otros archivos (`rg "build_embedding_payload|build_embedding_text" src/ tests/` debe devolver 0 resultados fuera de los commits eliminados). Si `test_evaluate_rag.py` u otro archivo importa estos simbolos, actualizalos.

- [ ] **Step 2: Verificar que no quedan referencias rotas**

```bash
cd backend && rg "build_embedding_payload|build_embedding_text|sample_intervention" src/ tests/ | grep -v "2026-07-31"
```

Expected: 0 resultados (o solo referencias validas).

- [ ] **Step 3: Commit de verificacion**

```bash
git add -A
git commit -m "chore: verificacion post feature ventana deslizante"
```
