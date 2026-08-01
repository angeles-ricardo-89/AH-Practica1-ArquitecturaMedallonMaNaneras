# Filtro Temporal Hibrido para RAG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar pre-procesamiento temporal al endpoint `/chat/` que extrae fechas de la query via llamacpp, genera embedding con texto semantico limpio, y ejecuta consulta hibrida (BETWEEN + pgvector cosine) en PostgreSQL.

**Architecture:** `TemporalParser` → llamacpp con prompt estricto + Pydantic validation + 3 niveles de reintentos → `TimeFilterOut`. Si `requiere_filtro_tiempo=true`, `search_with_date_filter()` aplica `BETWEEN` sobre `conference_date` antes del ranking `<=>`. Si `false` o fallback, busqueda semantica pura. `ContextBuilder` inyecta nota de fallback cuando aplica.

**Tech Stack:** Python 3.13, Pydantic, httpx (llamacpp), Ollama (embeddings), psycopg (PostgreSQL + pgvector), pytest + FastAPI TestClient

---

### Task 1: Schema Temporal (Pydantic)

**Files:**
- Create: `backend/src/lakehouse/schemas/temporal.py`
- Create: `backend/tests/test_schemas/test_temporal.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from datetime import datetime
from pydantic import ValidationError

from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult


class TestTimeFilterOut:
    def test_valid_with_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
        )
        assert tf.requiere_filtro_tiempo is True
        assert tf.fecha_inicio == "2025-07-15 00:00:00"
        assert tf.fecha_fin == "2025-07-15 23:59:59"
        assert tf.texto_busqueda_semantica == "Que dijo Sheinbaum sobre el T-MEC"

    def test_valid_without_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="postura sobre energia nuclear",
        )
        assert tf.requiere_filtro_tiempo is False
        assert tf.fecha_inicio is None
        assert tf.fecha_fin is None

    def test_rejects_requires_filter_without_dates(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                texto_busqueda_semantica="algo",
            )

    def test_rejects_malformed_date(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio="15/07/2025",
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )

    def test_rejects_requires_filter_with_none_start(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio=None,
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )


class TestTimeParserResult:
    def test_successful_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="test",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=False,
            raw_llm_response='{"requiere_filtro_tiempo":true,...}',
        )
        assert result.fallback_ocurrido is False
        assert result.filter_out == tf

    def test_fallback_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="query original",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=True,
            raw_llm_response="respuesta invalida del LLM",
        )
        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_schemas/test_temporal.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'lakehouse.schemas.temporal'`

- [ ] **Step 3: Write minimal implementation**

```python
from datetime import datetime
from pydantic import BaseModel, model_validator


class TimeFilterOut(BaseModel):
    requiere_filtro_tiempo: bool
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    texto_busqueda_semantica: str

    @model_validator(mode="after")
    def validar_coherencia(self):
        if self.requiere_filtro_tiempo:
            if not self.fecha_inicio or not self.fecha_fin:
                raise ValueError(
                    "fecha_inicio y fecha_fin requeridos cuando requiere_filtro_tiempo=true"
                )
            for f in [self.fecha_inicio, self.fecha_fin]:
                datetime.strptime(f, "%Y-%m-%d %H:%M:%S")
        return self


class TimeParserResult(BaseModel):
    filter_out: TimeFilterOut
    fallback_ocurrido: bool
    raw_llm_response: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_schemas/test_temporal.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/temporal.py backend/tests/test_schemas/test_temporal.py
git commit -m "agrega schemas TimeFilterOut y TimeParserResult para filtro temporal"
```

---

### Task 2: Config Settings

**Files:**
- Modify: `backend/src/lakehouse/config.py`

- [ ] **Step 1: Add temporal parser settings**

```python
temporal_parser_temperature: float = 0.1
temporal_parser_max_retries: int = 3
temporal_parser_max_tokens: int = 200
```

Insert after line 24 (`max_context_tokens: int = 8192`):

```python
    max_context_tokens: int = 8192
    max_ingest_pool: int = 6
    temporal_parser_temperature: float = 0.1
    temporal_parser_max_retries: int = 3
    temporal_parser_max_tokens: int = 200
```

- [ ] **Step 2: Verify settings load correctly**

```bash
cd backend && uv run python -c "from lakehouse.config import Settings; s = Settings(); assert s.temporal_parser_temperature == 0.1; assert s.temporal_parser_max_retries == 3; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Run existing tests to ensure no regression**

```bash
uv run pytest tests/test_schemas/test_config.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/lakehouse/config.py
git commit -m "agrega settings de temporal parser al config"
```

---

### Task 3: TemporalParser Service

**Files:**
- Create: `backend/src/lakehouse/services/temporal_parser.py`
- Create: `backend/tests/test_services/test_temporal_parser.py`

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import MagicMock, patch

import httpx
import pytest

from lakehouse.config import Settings
from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult
from lakehouse.services.temporal_parser import TemporalParser


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def parser(settings):
    return TemporalParser(settings)


class TestTemporalParserExtraer:
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_extrae_fecha_exacta(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"requiere_filtro_tiempo":true,"fecha_inicio":"2025-07-15 00:00:00","fecha_fin":"2025-07-15 23:59:59","texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC"}'
                }
            }]
        }
        mock_client.post.return_value = mock_response

        result = parser.extraer("Que dijo Sheinbaum sobre el T-MEC en la conferencia del 15 de julio 2025")

        assert isinstance(result, TimeParserResult)
        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"
        assert "15 de julio" not in result.filter_out.texto_busqueda_semantica

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_sin_intencion_temporal(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"postura sobre energia nuclear"}'
                }
            }]
        }
        mock_client.post.return_value = mock_response

        result = parser.extraer("postura sobre energia nuclear")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.fecha_inicio is None
        assert result.filter_out.fecha_fin is None

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_con_markdown_json_block(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '```json\n{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"que es la reforma"}\n```\nEspero que te sirva.'
                }
            }]
        }
        mock_client.post.return_value = mock_response

        result = parser.extraer("que es la reforma")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_invalido_usa_fallback(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200

        call_count = [0]

        def fake_json():
            call_count[0] += 1
            return {
                "choices": [{
                    "message": {"content": "no soy un JSON valido en ningun intento, solo texto"}
                }]
            }

        mock_response.json.side_effect = fake_json
        mock_client.post.return_value = mock_response

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_prompt_incluye_datetime_actual(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"test"}'
                }
            }]
        }
        mock_client.post.return_value = mock_response

        parser.extraer("test")

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        messages = payload["messages"]
        system_content = messages[0]["content"]
        assert "fecha/hora actual" in system_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_temporal_parser.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
from __future__ import annotations

import json
import re
import time
from datetime import datetime

import httpx

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult

logger = get_logger(__name__, layer="service")


def _build_system_prompt() -> str:
    now = datetime.now().isoformat()
    return (
        "Eres un parser de consultas temporales. Tu UNICA tarea es extraer informacion "
        "de tiempo de la pregunta del usuario y devolver un objeto JSON.\n\n"
        "REGLAS:\n"
        f"- La fecha/hora actual del servidor es: {now}\n"
        "- Usa esa referencia para calcular fechas relativas (ayer, la semana pasada, etc.)\n"
        '- fecha_inicio debe ser "YYYY-MM-DD 00:00:00"\n'
        '- fecha_fin debe ser "YYYY-MM-DD 23:59:59"\n'
        "- texto_busqueda_semantica debe contener SOLO la parte semantica de la query, "
        'eliminando TODAS las palabras temporales (fechas, "ayer", "lunes", "reciente", '
        '"semana pasada", "el miercoles", etc.)\n'
        "- Si la query NO tiene intencion temporal, devuelve requiere_filtro_tiempo=false "
        "y fecha_inicio/fecha_fin en null. El texto_busqueda_semantica sera la query completa.\n"
        "- Devuelve UNICAMENTE el JSON, sin texto adicional, sin markdown, sin explicaciones.\n\n"
        "Ejemplos:\n"
        'Query: "Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?"\n'
        "-> Si hoy es miercoles 2026-08-05:\n"
        '{"requiere_filtro_tiempo":true, "fecha_inicio":"2026-08-03 00:00:00", '
        '"fecha_fin":"2026-08-03 23:59:59", '
        '"texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC en la conferencia"}'
    )


def _try_parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[^{}]*\{[^{}]*\}[^{}]*\}", raw)
    if not match:
        match = re.search(r"\{.*\}", raw, re.DOTALL)

    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


class TemporalParser:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def extraer(self, query: str) -> TimeParserResult:
        system_prompt = _build_system_prompt()
        url = f"{self._settings.llamacpp_base_url}/chat/completions"
        temperature = self._settings.temporal_parser_temperature
        max_tokens = self._settings.temporal_parser_max_tokens
        max_retries = self._settings.temporal_parser_max_retries

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(
                        url,
                        json={
                            "model": self._settings.llamacpp_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": query},
                            ],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json()["choices"][0]["message"]["content"]

                parsed = _try_parse_json(raw)
                if parsed is not None:
                    try:
                        filter_out = TimeFilterOut.model_validate(parsed)
                        return TimeParserResult(
                            filter_out=filter_out,
                            fallback_ocurrido=False,
                            raw_llm_response=raw,
                        )
                    except Exception:
                        if attempt < max_retries - 1:
                            continue

            except Exception as e:
                logger.warning(
                    "TemporalParser attempt %d failed: %s", attempt + 1, e
                )
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (2**attempt))
                continue

        logger.warning(
            "TemporalParser: usando fallback tras %d intentos fallidos", max_retries
        )
        return TimeParserResult(
            filter_out=TimeFilterOut(
                requiere_filtro_tiempo=False,
                texto_busqueda_semantica=query,
            ),
            fallback_ocurrido=True,
            raw_llm_response="",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_temporal_parser.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/temporal_parser.py backend/tests/test_services/test_temporal_parser.py
git commit -m "agrega TemporalParser con 3 niveles de reintento y fallback"
```

---

### Task 4: search_with_date_filter en rag_search.py

**Files:**
- Modify: `backend/src/lakehouse/services/rag_search.py`
- Modify: `backend/tests/test_services/test_rag_search.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_services/test_rag_search.py`:

```python
class TestSearchWithDateFilter:
    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_returns_mapped_rows_within_date_range(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2025-07-15", "c1", "PARTICIPANTE", "texto", "https://u", "pregunta", 0.95),
        ]

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=5,
            fecha_inicio="2025-07-15",
            fecha_fin="2025-07-15",
        )

        assert len(results) == 1
        assert results[0]["conference_id"] == "c1"
        assert results[0]["similarity"] == 0.95

        sql, params = mock_cursor.execute.call_args.args
        assert "conference_date BETWEEN" in sql
        assert "embedding <=> %s::vector" in sql
        assert "LENGTH(chunk_text) >= 50" in sql

    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_returns_empty_when_no_rows_in_range(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=5,
            fecha_inicio="2099-01-01",
            fecha_fin="2099-12-31",
        )

        assert results == []

    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_ranking_within_range_with_top_k(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2025-07-15", "c1", "P", "t1", "u1", "q", 0.99),
            ("2025-07-15", "c2", "P", "t2", "u2", "q", 0.80),
            ("2025-07-15", "c3", "P", "t3", "u3", "q", 0.70),
        ]

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=3,
            fecha_inicio="2025-07-15",
            fecha_fin="2025-07-15",
        )

        assert len(results) == 3
        assert results[0]["similarity"] == 0.99
        assert results[2]["similarity"] == 0.70

        sql, params = mock_cursor.execute.call_args.args
        assert len(params) >= 4
        assert params[3] == 3
```

Also add the import at the top of the test file (after existing imports):

```python
from lakehouse.services.rag_search import (
    _call_ollama_embed,
    _embed_query,
    _get_pgvector_connection_string,
    search_gold_corpus,
    search_sources,
    search_with_date_filter,
)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_rag_search.py::TestSearchWithDateFilter -v
```
Expected: FAIL — `ImportError: cannot import name 'search_with_date_filter'`

- [ ] **Step 3: Write implementation**

Add after `search_gold_corpus()` (after line 133) in `backend/src/lakehouse/services/rag_search.py`:

```python
def search_with_date_filter(
    query_vector: list[float],
    top_k: int,
    fecha_inicio: str,
    fecha_fin: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE conference_date BETWEEN %s::date AND %s::date
                  AND LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(
                query_sql,
                (embedding_str, fecha_inicio, fecha_fin, embedding_str, top_k),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector con filtro de fechas")
        raise RuntimeError("Search unavailable: database query failed") from e

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
            }
        )

    logger.info(
        "Busqueda con filtro de fechas completada",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resultados=len(results),
    )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_rag_search.py::TestSearchWithDateFilter -v
```
Expected: PASS

- [ ] **Step 5: Run ALL existing rag_search tests to ensure no regression**

```bash
uv run pytest tests/test_services/test_rag_search.py -v
```
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/src/lakehouse/services/rag_search.py backend/tests/test_services/test_rag_search.py
git commit -m "agrega search_with_date_filter con BETWEEN sobre conference_date"
```

---

### Task 5: ContextBuilder — nota_fallback y sources vacio

**Files:**
- Modify: `backend/src/lakehouse/services/context_builder.py`
- Modify: `backend/tests/test_api/test_chat.py` (TestContextBuilder class)

- [ ] **Step 1: Write failing tests**

Append to `TestContextBuilder` class in `backend/tests/test_api/test_chat.py`:

```python
    def test_nota_fallback_included_in_context(self):
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=True,
        )
        assert "No se pudo determinar" in context
        assert "filtro temporal" in context
        assert "PRESIDENTA" in context

    def test_no_fallback_nota_when_not_requested(self):
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=False,
        )
        assert "No se pudo determinar" not in context

    def test_empty_sources_handled_gracefully(self):
        builder = ContextBuilder(max_context_tokens=8192)
        context, _usage = builder.build(
            query="test query",
            system_prompt="sys",
            sources=[],
        )
        assert "test query" in context
        assert "sys" in context
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api/test_chat.py::TestContextBuilder -v
```
Expected: Some tests FAIL — `ContextBuilder.build() got an unexpected keyword argument 'nota_fallback'`

- [ ] **Step 3: Write implementation**

Modify `build()` method signature and body in `backend/src/lakehouse/services/context_builder.py`:

Replace the method signature (line 15):

```python
    def build(
        self,
        query: str,
        system_prompt: str,
        sources: list | None = None,
        history: list[dict[str, str]] | None = None,
        nota_fallback: bool = False,
    ) -> tuple[str, TokenUsage]:
```

Replace the context assembly block (lines 41-45):

```python
        context = f"{system_prompt}\n\n"
        if nota_fallback:
            context += (
                "NOTA: No se pudo determinar automaticamente el filtro temporal de la consulta. "
                "Los resultados pueden pertenecer a cualquier fecha.\n---\n\n"
            )
        if sources_text.strip():
            context += f"Fuentes:\n{sources_text}\n\n"
        context += self._truncate_history_to_tokens(history, max_history_tokens)
        context += f"Pregunta: {query}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_api/test_chat.py::TestContextBuilder -v
```
Expected: PASS

- [ ] **Step 5: Run ALL existing chat tests to ensure no regression**

```bash
uv run pytest tests/test_api/test_chat.py -v
```
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/src/lakehouse/services/context_builder.py backend/tests/test_api/test_chat.py
git commit -m "agrega nota_fallback y manejo de sources vacio en ContextBuilder"
```

---

### Task 6: Orquestacion en Chat Endpoint

**Files:**
- Modify: `backend/src/lakehouse/api/routers/chat.py`
- Modify: `backend/tests/test_api/test_chat.py` (TestChatEndpoint class)

- [ ] **Step 1: Write failing tests**

Append to `TestChatEndpoint` class in `backend/tests/test_api/test_chat.py`:

```python
    def test_chat_with_temporal_filter(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=True,
                    fecha_inicio="2025-07-15",
                    fecha_fin="2025-07-15",
                    texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
                ),
                fallback_ocurrido=False,
            )
            with patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
                mock_date_search.return_value = []
                resp = client.post("/chat/", json={"query": "Que dijo Sheinbaum ayer sobre el T-MEC"})
                assert resp.status_code == 200
                mock_date_search.assert_called_once()

    def test_chat_without_temporal_intent(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=False,
                    texto_busqueda_semantica="postura sobre energia nuclear",
                ),
                fallback_ocurrido=False,
            )
            resp = client.post("/chat/", json={"query": "postura sobre energia nuclear"})
            assert resp.status_code == 200

    def test_chat_parser_fallback_injects_nota(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=False,
                    texto_busqueda_semantica="query ambigua",
                ),
                fallback_ocurrido=True,
            )
            resp = client.post("/chat/", json={"query": "query ambigua con fecha confusa"})
            assert resp.status_code == 200

    def test_chat_with_empty_date_range_responds_no_info(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls, \
             patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=True,
                    fecha_inicio="2099-01-01",
                    fecha_fin="2099-12-31",
                    texto_busqueda_semantica="reforma energetica",
                ),
                fallback_ocurrido=False,
            )
            mock_date_search.return_value = []
            resp = client.post("/chat/", json={"query": "reforma energetica de 2099"})
            assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api/test_chat.py::TestChatEndpoint -v
```
Expected: Some tests FAIL — `ModuleNotFoundError` or assertion failures

- [ ] **Step 3: Write implementation**

Replace `backend/src/lakehouse/api/routers/chat.py` in full:

```python
import httpx
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.chat import ChatRequest, ChatResponse
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.rag_search import _embed_query, search_gold_corpus, search_sources, search_with_date_filter
from lakehouse.services.temporal_parser import TemporalParser
from lakehouse.services.token_estimator import estimate_tokens

logger = get_logger(__name__, layer="api")
router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "Eres un asistente especializado en las conferencias matutinas "
    "(Maaneras) del Gobierno de Mexico. Responde preguntas basandote "
    "en las fuentes proporcionadas. Si no encuentras informacion en las "
    "fuentes, indica que no tienes informacion al respecto."
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Chat with RAG",
    description="Send a query and get an answer with sources from the RAG corpus",
)
def chat(request: ChatRequest) -> ChatResponse:
    settings = Settings()
    logger.info(
        "Chat request recibido",
        query=request.query[:100],
        top_k=request.top_k,
    )

    temporal_parser = TemporalParser(settings)
    parser_result = temporal_parser.extraer(request.query)
    texto_semantico = parser_result.filter_out.texto_busqueda_semantica

    logger.info(
        "Parseo temporal completado",
        requiere_filtro=parser_result.filter_out.requiere_filtro_tiempo,
        fallback=parser_result.fallback_ocurrido,
    )

    try:
        query_embedding = _embed_query(
            texto_semantico, settings.ollama_base_url, settings.ollama_embed_model
        )
    except Exception as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("LLM backend unavailable") from e

    if parser_result.filter_out.requiere_filtro_tiempo:
        sources = search_with_date_filter(
            query_vector=query_embedding,
            top_k=request.top_k,
            fecha_inicio=parser_result.filter_out.fecha_inicio,
            fecha_fin=parser_result.filter_out.fecha_fin,
            settings=settings,
        )
        logger.info("Fuentes recuperadas con filtro temporal", source_count=len(sources))
    else:
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        from lakehouse.services.rag_search import _get_pgvector_connection_string
        import psycopg
        from lakehouse.pipeline.enrichment import MIN_CHUNK_LENGTH
        from typing import cast, LiteralString

        conn_str = _get_pgvector_connection_string(settings)
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(query_sql, (embedding_str, embedding_str, request.top_k))
            rows = cur.fetchall()

        results = []
        for row in rows:
            results.append({
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
            })

        from lakehouse.schemas.chat import SourceChunk
        sources = [
            SourceChunk(
                conference_date=r["conference_date"],
                conference_id=r["conference_id"],
                participant=r["participant"],
                chunk_text=r["chunk_text"],
                similarity=r["similarity"],
                conference_url=r["url"],
                pregunta_activa=r["pregunta_activa"],
            )
            for r in results
        ]
        logger.info("Fuentes recuperadas para chat", source_count=len(sources))

    builder = ContextBuilder(max_context_tokens=settings.max_context_tokens)
    context, token_usage = builder.build(
        query=request.query,
        system_prompt=SYSTEM_PROMPT,
        sources=sources,
        nota_fallback=parser_result.fallback_ocurrido,
    )
    logger.info("Contexto construido para LLM", tokens_estimados=token_usage)

    try:
        with httpx.Client(timeout=60.0) as client:
            payload = {
                "model": settings.llamacpp_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "max_tokens": 4096,
            }
            resp = client.post(
                f"{settings.llamacpp_base_url}/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            prompt_tokens = data.get("usage", {}).get("prompt_tokens", estimate_tokens(context))
            completion_tokens = data.get("usage", {}).get(
                "completion_tokens", estimate_tokens(answer)
            )
            logger.info(
                "Chat response generado",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
    except Exception as e:
        logger.exception("Backend LLM no disponible")
        raise RuntimeError("LLM backend unavailable") from e

    return ChatResponse(
        answer=answer,
        sources=sources,
        token_usage={
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
    )
```

Wait — this is duplicating `search_gold_corpus` logic. Let me refactor this to avoid duplication. I'll modify `rag_search.py` to export a helper that takes the already-computed embedding vector.

Actually, the simplest approach is: add a new function `search_gold_corpus_from_vector()` in `rag_search.py` that accepts a pre-computed vector, and use that from the chat endpoint.

Let me revise the implementation. I'll update rag_search.py with a helper, then use it in chat.py.

**Updated Step 3 — Add search_gold_corpus_from_vector() to rag_search.py first:**

```python
def search_gold_corpus_from_vector(
    query_vector: list[float],
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(query_sql, (embedding_str, embedding_str, top_k))
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector")
        raise RuntimeError("Search unavailable: database query failed") from e

    results = []
    for row in rows:
        results.append({
            "conference_date": str(row[0]),
            "conference_id": row[1],
            "participant": row[2],
            "chunk_text": row[3],
            "url": row[4],
            "pregunta_activa": row[5] or "",
            "similarity": float(row[6]),
        })

    logger.info("Busqueda completada por vector", resultados=len(results))
    return results
```

And refactor `search_gold_corpus()` to use the new helper:

```python
def search_gold_corpus(
    query: str,
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    try:
        query_embedding = _embed_query(query, settings.ollama_base_url, settings.ollama_embed_model)
    except (ConnectionError, ValueError) as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("Search unavailable: embedding generation failed") from e

    return search_gold_corpus_from_vector(query_embedding, top_k, settings)
```

Then the chat endpoint becomes much cleaner:

```python
def chat(request: ChatRequest) -> ChatResponse:
    settings = Settings()
    ...
    temporal_parser = TemporalParser(settings)
    parser_result = temporal_parser.extraer(request.query)

    try:
        query_embedding = _embed_query(
            parser_result.filter_out.texto_busqueda_semantica,
            settings.ollama_base_url,
            settings.ollama_embed_model,
        )
    except Exception as e:
        logger.exception("No se pudo generar embedding")
        raise RuntimeError("LLM backend unavailable") from e

    if parser_result.filter_out.requiere_filtro_tiempo:
        results = search_with_date_filter(
            query_vector=query_embedding,
            top_k=request.top_k,
            fecha_inicio=parser_result.filter_out.fecha_inicio,
            fecha_fin=parser_result.filter_out.fecha_fin,
            settings=settings,
        )
    else:
        results = search_gold_corpus_from_vector(query_embedding, request.top_k, settings)

    sources = [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
        )
        for r in results
    ]
    ...
```

This is much cleaner. Let me update the plan accordingly. The issue is that the plan I was writing is too long and complex. Let me revise tasks 4 and 6 with the cleaner approach.

Actually wait, let me reconsider. The plan should keep `search_gold_corpus_from_vector` as part of Task 4 (which is about rag_search.py changes), and then Task 6 uses it from chat.py. Let me rewrite the plan properly.

This is getting complex. Let me write a cleaner plan document.<｜end▁of▁thinking｜>Now let me write the complete plan.

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="write">
<｜｜DSML｜｜parameter name="content" string="true"># Filtro Temporal Hibrido para RAG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar pre-procesamiento temporal al endpoint `/chat/` que extrae fechas de la query via llamacpp, genera embedding con texto semantico limpio, y ejecuta consulta hibrida (BETWEEN + pgvector cosine) en PostgreSQL.

**Architecture:** `TemporalParser` → llamacpp con prompt estricto + Pydantic validation + 3 niveles de reintentos → `TimeFilterOut`. Si `requiere_filtro_tiempo=true`, `search_with_date_filter()` aplica `BETWEEN` sobre `conference_date` antes del ranking `<=>`. Si `false` o fallback, `search_gold_corpus_from_vector()` mantiene la busqueda semantica pura actual. `ContextBuilder` inyecta nota de fallback + maneja sources vacios.

**Tech Stack:** Python 3.13, Pydantic, httpx (llamacpp), Ollama (embeddings via `_embed_query`), psycopg (PostgreSQL + pgvector), pytest + FastAPI TestClient

---

### Task 1: Schema Temporal (Pydantic)

**Files:**
- Create: `backend/src/lakehouse/schemas/temporal.py`
- Create: `backend/tests/test_schemas/test_temporal.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from pydantic import ValidationError

from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult


class TestTimeFilterOut:
    def test_valid_with_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
        )
        assert tf.requiere_filtro_tiempo is True
        assert tf.fecha_inicio == "2025-07-15 00:00:00"
        assert tf.fecha_fin == "2025-07-15 23:59:59"

    def test_valid_without_filter(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="postura sobre energia nuclear",
        )
        assert tf.requiere_filtro_tiempo is False
        assert tf.fecha_inicio is None
        assert tf.fecha_fin is None

    def test_rejects_requires_filter_without_dates(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                texto_busqueda_semantica="algo",
            )

    def test_rejects_malformed_date_format(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio="15/07/2025",
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )

    def test_rejects_requires_filter_with_none_date(self):
        with pytest.raises(ValidationError):
            TimeFilterOut(
                requiere_filtro_tiempo=True,
                fecha_inicio=None,
                fecha_fin="2025-07-15 23:59:59",
                texto_busqueda_semantica="algo",
            )


class TestTimeParserResult:
    def test_successful_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=True,
            fecha_inicio="2025-07-15 00:00:00",
            fecha_fin="2025-07-15 23:59:59",
            texto_busqueda_semantica="test",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=False,
            raw_llm_response='{"requiere_filtro_tiempo":true}',
        )
        assert result.fallback_ocurrido is False
        assert result.filter_out == tf

    def test_fallback_parse(self):
        tf = TimeFilterOut(
            requiere_filtro_tiempo=False,
            texto_busqueda_semantica="query original",
        )
        result = TimeParserResult(
            filter_out=tf,
            fallback_ocurrido=True,
            raw_llm_response="respuesta invalida del LLM",
        )
        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_schemas/test_temporal.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'lakehouse.schemas.temporal'`

- [ ] **Step 3: Write implementation**

`backend/src/lakehouse/schemas/temporal.py`:

```python
from datetime import datetime

from pydantic import BaseModel, model_validator


class TimeFilterOut(BaseModel):
    requiere_filtro_tiempo: bool
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    texto_busqueda_semantica: str

    @model_validator(mode="after")
    def validar_coherencia(self):
        if self.requiere_filtro_tiempo:
            if not self.fecha_inicio or not self.fecha_fin:
                raise ValueError(
                    "fecha_inicio y fecha_fin requeridos cuando requiere_filtro_tiempo=true"
                )
            for f in [self.fecha_inicio, self.fecha_fin]:
                datetime.strptime(f, "%Y-%m-%d %H:%M:%S")
        return self


class TimeParserResult(BaseModel):
    filter_out: TimeFilterOut
    fallback_ocurrido: bool
    raw_llm_response: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_schemas/test_temporal.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/schemas/temporal.py backend/tests/test_schemas/test_temporal.py
git commit -m "agrega schemas TimeFilterOut y TimeParserResult para filtro temporal"
```

---

### Task 2: Config Settings

**Files:**
- Modify: `backend/src/lakehouse/config.py`

- [ ] **Step 1: Add temporal parser settings**

After `max_ingest_pool: int = 6` (line 25), add:

```python
    temporal_parser_temperature: float = 0.1
    temporal_parser_max_retries: int = 3
    temporal_parser_max_tokens: int = 200
```

- [ ] **Step 2: Verify settings load correctly**

```bash
cd backend && uv run python -c "from lakehouse.config import Settings; s = Settings(); assert s.temporal_parser_temperature == 0.1; assert s.temporal_parser_max_retries == 3; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Run existing config tests**

```bash
uv run pytest tests/test_schemas/test_config.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/lakehouse/config.py
git commit -m "agrega settings de temporal parser al config"
```

---

### Task 3: TemporalParser Service

**Files:**
- Create: `backend/src/lakehouse/services/temporal_parser.py`
- Create: `backend/tests/test_services/test_temporal_parser.py`

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import MagicMock, patch

import pytest

from lakehouse.config import Settings
from lakehouse.schemas.temporal import TimeParserResult
from lakehouse.services.temporal_parser import TemporalParser


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def parser(settings):
    return TemporalParser(settings)


class TestTemporalParserExtraer:
    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_extrae_fecha_exacta(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": '{"requiere_filtro_tiempo":true,"fecha_inicio":"2025-07-15 00:00:00","fecha_fin":"2025-07-15 23:59:59","texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC"}'}}]
        }

        result = parser.extraer("Que dijo Sheinbaum sobre el T-MEC en la conferencia del 15 de julio 2025")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"
        assert "15 de julio" not in result.filter_out.texto_busqueda_semantica

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_sin_intencion_temporal(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"postura sobre energia nuclear"}'}}]
        }

        result = parser.extraer("postura sobre energia nuclear")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.fecha_inicio is None
        assert result.filter_out.fecha_fin is None

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_con_markdown_json_block(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": '```json\n{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"que es la reforma"}\n```\nEspero que te sirva.'}}]
        }

        result = parser.extraer("que es la reforma")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is False

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_llm_responde_invalido_usa_fallback(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": "no soy un JSON valido en ningun intento, solo texto"}}]
        }

        result = parser.extraer("texto con fecha hoy")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
        assert result.filter_out.texto_busqueda_semantica == "texto con fecha hoy"

    @patch("lakehouse.services.temporal_parser.httpx.Client")
    def test_prompt_incluye_datetime_actual(self, mock_client_class, parser):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": '{"requiere_filtro_tiempo":false,"fecha_inicio":null,"fecha_fin":null,"texto_busqueda_semantica":"test"}'}}]
        }

        parser.extraer("test")

        call_args = mock_client.post.call_args
        messages = call_args[1]["json"]["messages"]
        system_content = messages[0]["content"]
        assert "fecha/hora actual" in system_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_temporal_parser.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

`backend/src/lakehouse/services/temporal_parser.py`:

```python
from __future__ import annotations

import json
import re
import time
from datetime import datetime

import httpx

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult

logger = get_logger(__name__, layer="service")


def _build_system_prompt() -> str:
    now = datetime.now().isoformat()
    return (
        "Eres un parser de consultas temporales. Tu UNICA tarea es extraer informacion "
        "de tiempo de la pregunta del usuario y devolver un objeto JSON.\n\n"
        "REGLAS:\n"
        f"- La fecha/hora actual del servidor es: {now}\n"
        "- Usa esa referencia para calcular fechas relativas (ayer, la semana pasada, etc.)\n"
        '- fecha_inicio debe ser "YYYY-MM-DD 00:00:00"\n'
        '- fecha_fin debe ser "YYYY-MM-DD 23:59:59"\n'
        "- texto_busqueda_semantica debe contener SOLO la parte semantica de la query, "
        'eliminando TODAS las palabras temporales (fechas, "ayer", "lunes", "reciente", '
        '"semana pasada", "el miercoles", etc.)\n'
        "- Si la query NO tiene intencion temporal, devuelve requiere_filtro_tiempo=false "
        "y fecha_inicio/fecha_fin en null. El texto_busqueda_semantica sera la query completa.\n"
        "- Devuelve UNICAMENTE el JSON, sin texto adicional, sin markdown, sin explicaciones.\n\n"
        "Ejemplos:\n"
        'Query: "Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?"\n'
        "-> Si hoy es miercoles 2026-08-05:\n"
        '{"requiere_filtro_tiempo":true, "fecha_inicio":"2026-08-03 00:00:00", '
        '"fecha_fin":"2026-08-03 23:59:59", '
        '"texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC en la conferencia"}\n\n'
        'Query: "Cual es la postura sobre energia nuclear?"\n'
        '-> {"requiere_filtro_tiempo":false, "fecha_inicio":null, "fecha_fin":null, '
        '"texto_busqueda_semantica":"Cual es la postura sobre energia nuclear"}'
    )


def _try_parse_json(raw: str) -> dict | None:
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)

    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


class TemporalParser:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def extraer(self, query: str) -> TimeParserResult:
        system_prompt = _build_system_prompt()
        url = f"{self._settings.llamacpp_base_url}/chat/completions"
        temperature = self._settings.temporal_parser_temperature
        max_tokens = self._settings.temporal_parser_max_tokens
        max_retries = self._settings.temporal_parser_max_retries

        for attempt in range(max_retries):
            raw = ""
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(
                        url,
                        json={
                            "model": self._settings.llamacpp_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": query},
                            ],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json()["choices"][0]["message"]["content"]

                parsed = _try_parse_json(raw)
                if parsed is not None:
                    try:
                        filter_out = TimeFilterOut.model_validate(parsed)
                        return TimeParserResult(
                            filter_out=filter_out,
                            fallback_ocurrido=False,
                            raw_llm_response=raw,
                        )
                    except Exception:
                        logger.warning(
                            "TemporalParser attempt %d: JSON parseable pero no valido", attempt + 1
                        )
                        if attempt < max_retries - 1:
                            continue

            except Exception as e:
                logger.warning("TemporalParser attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (2**attempt))
                continue

        logger.warning("TemporalParser: usando fallback tras %d intentos fallidos", max_retries)
        return TimeParserResult(
            filter_out=TimeFilterOut(
                requiere_filtro_tiempo=False,
                texto_busqueda_semantica=query,
            ),
            fallback_ocurrido=True,
            raw_llm_response="",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_services/test_temporal_parser.py -v
```
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/temporal_parser.py backend/tests/test_services/test_temporal_parser.py
git commit -m "agrega TemporalParser con 3 niveles de reintento y fallback"
```

---

### Task 4: Refactor rag_search.py + search_with_date_filter

**Files:**
- Modify: `backend/src/lakehouse/services/rag_search.py`
- Modify: `backend/tests/test_services/test_rag_search.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_services/test_rag_search.py`:

```python
class TestSearchGoldCorpusFromVector:
    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_returns_mapped_rows(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2024-10-01", "c1", "P", "texto", "https://u", "q", 0.95),
        ]

        from lakehouse.services.rag_search import search_gold_corpus_from_vector
        results = search_gold_corpus_from_vector([0.1] * 768, top_k=5)

        assert len(results) == 1
        assert results[0]["conference_id"] == "c1"
        assert results[0]["similarity"] == 0.95
        sql, _params = mock_cursor.execute.call_args.args
        assert "ORDER BY embedding <=> %s::vector" in sql
        assert "LENGTH(chunk_text) >= 50" in sql


class TestSearchWithDateFilter:
    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_returns_mapped_rows_within_date_range(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2025-07-15", "c1", "P", "texto", "https://u", "q", 0.95),
        ]

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=5,
            fecha_inicio="2025-07-15",
            fecha_fin="2025-07-15",
        )

        assert len(results) == 1
        assert results[0]["conference_id"] == "c1"
        sql, _params = mock_cursor.execute.call_args.args
        assert "conference_date BETWEEN" in sql
        assert "embedding <=> %s::vector" in sql

    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_returns_empty_when_no_rows_in_range(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=5,
            fecha_inicio="2099-01-01",
            fecha_fin="2099-12-31",
        )

        assert results == []

    @patch("lakehouse.services.rag_search.psycopg.connect")
    def test_ranking_within_range_with_top_k(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("2025-07-15", "c1", "P", "t1", "u1", "q", 0.99),
            ("2025-07-15", "c2", "P", "t2", "u2", "q", 0.80),
            ("2025-07-15", "c3", "P", "t3", "u3", "q", 0.70),
        ]

        from lakehouse.services.rag_search import search_with_date_filter
        results = search_with_date_filter(
            query_vector=[0.1] * 768,
            top_k=3,
            fecha_inicio="2025-07-15",
            fecha_fin="2025-07-15",
        )

        assert len(results) == 3
        assert results[0]["similarity"] == 0.99
        assert results[2]["similarity"] == 0.70
```

Update imports at top of test file — replace the `from lakehouse.services.rag_search import ...` block with:

```python
from lakehouse.services.rag_search import (
    _call_ollama_embed,
    _embed_query,
    _get_pgvector_connection_string,
    search_gold_corpus,
    search_gold_corpus_from_vector,
    search_sources,
    search_with_date_filter,
)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_services/test_rag_search.py::TestSearchGoldCorpusFromVector tests/test_services/test_rag_search.py::TestSearchWithDateFilter -v
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write implementation**

Add `search_gold_corpus_from_vector()` after the imports and before `search_gold_corpus()`. Then refactor `search_gold_corpus()` to use it, and add `search_with_date_filter()`.

In `backend/src/lakehouse/services/rag_search.py`, after line 75 (`_embed_query`), insert:

```python
def search_gold_corpus_from_vector(
    query_vector: list[float],
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(query_sql, (embedding_str, embedding_str, top_k))
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector")
        raise RuntimeError("Search unavailable: database query failed") from e

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
            }
        )

    logger.info("Busqueda completada por vector", resultados=len(results))
    return results
```

Replace `search_gold_corpus()` body (lines 81-133) with:

```python
def search_gold_corpus(
    query: str,
    top_k: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    try:
        query_embedding = _embed_query(query, settings.ollama_base_url, settings.ollama_embed_model)
    except (ConnectionError, ValueError) as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("Search unavailable: embedding generation failed") from e

    return search_gold_corpus_from_vector(query_embedding, top_k, settings)
```

After `search_gold_corpus()` (now around line 100), add `search_with_date_filter()`:

```python
def search_with_date_filter(
    query_vector: list[float],
    top_k: int,
    fecha_inicio: str,
    fecha_fin: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    if settings is None:
        settings = Settings()

    conn_str = _get_pgvector_connection_string(settings)
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            query_sql: LiteralString = cast(
                "LiteralString",
                f"""
                SELECT conference_date, conference_id, participant, chunk_text, url, pregunta_activa,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE conference_date BETWEEN %s::date AND %s::date
                  AND LENGTH(chunk_text) >= {MIN_CHUNK_LENGTH}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
            )
            cur.execute(
                query_sql,
                (embedding_str, fecha_inicio, fecha_fin, embedding_str, top_k),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Error al consultar pgvector con filtro de fechas")
        raise RuntimeError("Search unavailable: database query failed") from e

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "conference_date": str(row[0]),
                "conference_id": row[1],
                "participant": row[2],
                "chunk_text": row[3],
                "url": row[4],
                "pregunta_activa": row[5] or "",
                "similarity": float(row[6]),
            }
        )

    logger.info(
        "Busqueda con filtro de fechas completada",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resultados=len(results),
    )
    return results
```

- [ ] **Step 4: Run ALL rag_search tests**

```bash
uv run pytest tests/test_services/test_rag_search.py -v
```
Expected: ALL PASS (existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/rag_search.py backend/tests/test_services/test_rag_search.py
git commit -m "agrega search_gold_corpus_from_vector y search_with_date_filter"
```

---

### Task 5: ContextBuilder — nota_fallback y sources vacio

**Files:**
- Modify: `backend/src/lakehouse/services/context_builder.py`
- Modify: `backend/tests/test_api/test_chat.py` (TestContextBuilder section)

- [ ] **Step 1: Write failing tests**

Append to `TestContextBuilder` class in `backend/tests/test_api/test_chat.py`:

```python
    def test_nota_fallback_included_in_context(self):
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=True,
        )
        assert "No se pudo determinar" in context
        assert "filtro temporal" in context
        assert "PRESIDENTA" in context

    def test_no_fallback_nota_when_not_requested(self):
        builder = ContextBuilder(max_context_tokens=8192)
        sources = [
            SourceChunk(
                conference_date="2024-10-01",
                conference_id="abc123",
                participant="PRESIDENTA",
                chunk_text="Contenido de la fuente.",
                similarity=0.95,
                conference_url="https://example.com",
            ),
        ]
        context, _usage = builder.build(
            query="test",
            system_prompt="sys",
            sources=sources,
            nota_fallback=False,
        )
        assert "No se pudo determinar" not in context

    def test_empty_sources_handled_gracefully(self):
        builder = ContextBuilder(max_context_tokens=8192)
        context, _usage = builder.build(
            query="test query",
            system_prompt="sys",
            sources=[],
        )
        assert "test query" in context
        assert "sys" in context
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api/test_chat.py::TestContextBuilder::test_nota_fallback_included_in_context -v
```
Expected: FAIL — `build() got an unexpected keyword argument 'nota_fallback'`

- [ ] **Step 3: Write implementation**

In `backend/src/lakehouse/services/context_builder.py`:

Change `build()` signature (line 15) from:

```python
    def build(
        self,
        query: str,
        system_prompt: str,
        sources: list | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, TokenUsage]:
```

To:

```python
    def build(
        self,
        query: str,
        system_prompt: str,
        sources: list | None = None,
        history: list[dict[str, str]] | None = None,
        nota_fallback: bool = False,
    ) -> tuple[str, TokenUsage]:
```

Replace context assembly block (lines 41-45) from:

```python
        context = f"{system_prompt}\n\n"
        if sources_text.strip():
            context += f"Fuentes:\n{sources_text}\n\n"
        context += self._truncate_history_to_tokens(history, max_history_tokens)
        context += f"Pregunta: {query}"
```

To:

```python
        context = f"{system_prompt}\n\n"
        if nota_fallback:
            context += (
                "NOTA: No se pudo determinar automaticamente el filtro temporal de la consulta. "
                "Los resultados pueden pertenecer a cualquier fecha.\n---\n\n"
            )
        if sources_text.strip():
            context += f"Fuentes:\n{sources_text}\n\n"
        context += self._truncate_history_to_tokens(history, max_history_tokens)
        context += f"Pregunta: {query}"
```

- [ ] **Step 4: Run ContextBuilder tests**

```bash
uv run pytest tests/test_api/test_chat.py::TestContextBuilder -v
```
Expected: ALL PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/context_builder.py backend/tests/test_api/test_chat.py
git commit -m "agrega nota_fallback y manejo de sources vacio en ContextBuilder"
```

---

### Task 6: Orquestacion en Chat Endpoint

**Files:**
- Modify: `backend/src/lakehouse/api/routers/chat.py`
- Modify: `backend/tests/test_api/test_chat.py` (TestChatEndpoint section)

- [ ] **Step 1: Write failing tests**

Append to `TestChatEndpoint` class in `backend/tests/test_api/test_chat.py`:

```python
    def test_chat_with_temporal_filter(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls, \
             patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=True,
                    fecha_inicio="2025-07-15",
                    fecha_fin="2025-07-15",
                    texto_busqueda_semantica="Que dijo Sheinbaum sobre el T-MEC",
                ),
                fallback_ocurrido=False,
            )
            mock_date_search.return_value = []
            resp = client.post("/chat/", json={"query": "Que dijo Sheinbaum ayer sobre el T-MEC"})
            assert resp.status_code == 200
            mock_date_search.assert_called_once()

    def test_chat_without_temporal_intent(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls, \
             patch("lakehouse.api.routers.chat.search_gold_corpus_from_vector") as mock_search:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=False,
                    texto_busqueda_semantica="postura sobre energia nuclear",
                ),
                fallback_ocurrido=False,
            )
            mock_search.return_value = []
            resp = client.post("/chat/", json={"query": "postura sobre energia nuclear"})
            assert resp.status_code == 200

    def test_chat_parser_fallback_injects_nota(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls, \
             patch("lakehouse.api.routers.chat.search_gold_corpus_from_vector") as mock_search:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=False,
                    texto_busqueda_semantica="query ambigua",
                ),
                fallback_ocurrido=True,
            )
            mock_search.return_value = []
            resp = client.post("/chat/", json={"query": "query ambigua con fecha confusa"})
            assert resp.status_code == 200

    def test_chat_with_empty_date_range_responds_no_info(self, mock_llamacpp):
        with patch("lakehouse.api.routers.chat.TemporalParser") as mock_parser_cls, \
             patch("lakehouse.api.routers.chat.search_with_date_filter") as mock_date_search:
            mock_parser = MagicMock()
            mock_parser_cls.return_value = mock_parser
            mock_parser.extraer.return_value = MagicMock(
                filter_out=MagicMock(
                    requiere_filtro_tiempo=True,
                    fecha_inicio="2099-01-01",
                    fecha_fin="2099-12-31",
                    texto_busqueda_semantica="reforma energetica",
                ),
                fallback_ocurrido=False,
            )
            mock_date_search.return_value = []
            resp = client.post("/chat/", json={"query": "reforma energetica de 2099"})
            assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api/test_chat.py::TestChatEndpoint -v
```
Expected: Some tests FAIL — new tests won't find `TemporalParser` import in chat.py router

- [ ] **Step 3: Write implementation**

Replace `backend/src/lakehouse/api/routers/chat.py`:

```python
import httpx
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.chat import ChatRequest, ChatResponse, SourceChunk
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.rag_search import (
    _embed_query,
    search_gold_corpus_from_vector,
    search_with_date_filter,
)
from lakehouse.services.temporal_parser import TemporalParser
from lakehouse.services.token_estimator import estimate_tokens

logger = get_logger(__name__, layer="api")
router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "Eres un asistente especializado en las conferencias matutinas "
    "(Maaneras) del Gobierno de Mexico. Responde preguntas basandote "
    "en las fuentes proporcionadas. Si no encuentras informacion en las "
    "fuentes, indica que no tienes informacion al respecto."
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Chat with RAG",
    description="Send a query and get an answer with sources from the RAG corpus",
)
def chat(request: ChatRequest) -> ChatResponse:
    settings = Settings()
    logger.info(
        "Chat request recibido",
        query=request.query[:100],
        top_k=request.top_k,
    )

    temporal_parser = TemporalParser(settings)
    parser_result = temporal_parser.extraer(request.query)
    texto_semantico = parser_result.filter_out.texto_busqueda_semantica

    logger.info(
        "Parseo temporal completado",
        requiere_filtro=parser_result.filter_out.requiere_filtro_tiempo,
        fallback=parser_result.fallback_ocurrido,
    )

    try:
        query_embedding = _embed_query(
            texto_semantico, settings.ollama_base_url, settings.ollama_embed_model
        )
    except Exception as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("LLM backend unavailable") from e

    if parser_result.filter_out.requiere_filtro_tiempo:
        results = search_with_date_filter(
            query_vector=query_embedding,
            top_k=request.top_k,
            fecha_inicio=parser_result.filter_out.fecha_inicio,
            fecha_fin=parser_result.filter_out.fecha_fin,
            settings=settings,
        )
        logger.info("Fuentes recuperadas con filtro temporal", source_count=len(results))
    else:
        results = search_gold_corpus_from_vector(query_embedding, request.top_k, settings)
        logger.info("Fuentes recuperadas para chat", source_count=len(results))

    sources = [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
        )
        for r in results
    ]

    builder = ContextBuilder(max_context_tokens=settings.max_context_tokens)
    context, token_usage = builder.build(
        query=request.query,
        system_prompt=SYSTEM_PROMPT,
        sources=sources,
        nota_fallback=parser_result.fallback_ocurrido,
    )
    logger.info("Contexto construido para LLM", tokens_estimados=token_usage)

    try:
        with httpx.Client(timeout=60.0) as client:
            payload = {
                "model": settings.llamacpp_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "max_tokens": 4096,
            }
            resp = client.post(
                f"{settings.llamacpp_base_url}/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            prompt_tokens = data.get("usage", {}).get("prompt_tokens", estimate_tokens(context))
            completion_tokens = data.get("usage", {}).get(
                "completion_tokens", estimate_tokens(answer)
            )
            logger.info(
                "Chat response generado",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
    except Exception as e:
        logger.exception("Backend LLM no disponible")
        raise RuntimeError("LLM backend unavailable") from e

    return ChatResponse(
        answer=answer,
        sources=sources,
        token_usage={
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
    )
```

- [ ] **Step 4: Run ALL chat tests**

```bash
uv run pytest tests/test_api/test_chat.py -v
```
Expected: ALL PASS (existing + 4 new temporal tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/api/routers/chat.py backend/tests/test_api/test_chat.py
git commit -m "integra filtro temporal hibrido en endpoint /chat/"
```

---

### Task 7: QA — Lint, Typecheck, y Coverage Final

**Files:**
- None new

- [ ] **Step 1: Ruff check + format**

```bash
cd backend && uv run ruff check --fix && uv run ruff format
```
Expected: All clear, no errors

- [ ] **Step 2: Typecheck**

```bash
uv run pyright src/
```
Expected: 0 errors, 0 warnings

- [ ] **Step 3: Full test suite with coverage**

```bash
uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90
```
Expected: >= 90% coverage, ALL tests PASS

- [ ] **Step 4: Commit (amend if fixes needed)**

```bash
git add -A
git commit -m "QA: lint, typecheck, coverage >= 90% para filtro temporal hibrido"
```
