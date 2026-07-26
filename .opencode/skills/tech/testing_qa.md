# Tech Skill: Testing + QA

## Proposito

Definir la estrategia de testing, mocks y cobertura para el backend y frontend del Lakehouse Mañaneras.

## Referencias

- Python + uv + Ruff: `../tech/python_uv_ruff.md`
- FastAPI + Pydantic: `../tech/fastapi_pydantic_typer.md`

## Estrategia General

| Capa | Framework | Cobertura Minima | Enfoque |
|------|-----------|-----------------|---------|
| Schemas Pydantic | pytest | 100% | Validacion de campos, casos borde |
| Pipeline (Bronze/Silver) | pytest + mocks | 95% | Idempotencia, DLQ, parsing |
| FastAPI endpoints | pytest + httpx.AsyncClient | 90% | Status codes, response schemas |
| DuckDB/PG queries | pytest con fixtures | 90% | MERGE, inserts, busqueda vectorial |
| Vue Components | vitest + @vue/test-utils | 80% | Renderizado, eventos, stores |

## Backend — Pytest

### Estructura

```
backend/
    tests/
        __init__.py
        conftest.py
        test_schemas/
            test_search.py
            test_conference.py
        test_pipeline/
            test_ingestion.py
            test_parsing.py
            test_merge.py
        test_api/
            test_search.py
            test_chat.py
            test_health.py
        test_db/
            test_pgvector.py
            test_duckdb_merge.py
```

### Fixtures (conftest.py)

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from lakehouse.api.deps import get_settings
from lakehouse.config import Settings
from lakehouse.main import app

from unittest.mock import AsyncMock, patch


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_env="test",
        postgres_host="localhost",
        postgres_db="mananeras_test",
        ducklake_data_path="/tmp/lakehouse_test",
        llamacpp_base_url="http://localhost:9200/v1",
        llamacpp_model="gemma4",
        ollama_base_url="http://localhost:11434",
        ollama_embed_model="nomic-embed-text",
    )


@pytest_asyncio.fixture
async def async_client(
    test_settings: Settings,
) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_settings] = lambda: test_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
```

### Test de Schema (Pydantic)

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lakehouse.schemas.search import SearchRequest


def test_search_request_minima_valida() -> None:
    req = SearchRequest(query="entrevista periodistas")
    assert req.query == "entrevista periodistas"
    assert req.top_k == 8
    assert req.fecha_inicio is None


def test_search_request_query_vacia_rechazada() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_query_demasiado_larga() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="a" * 501)


def test_search_request_top_k_fuera_de_rango() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="test", top_k=0)
    with pytest.raises(ValidationError):
        SearchRequest(query="test", top_k=21)


def test_search_request_campos_extra_rechazados() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="test", campo_inexistente="no permitido")  # type: ignore[call-arg]
```

### Test de API (FastAPI)

```python
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_search_sin_filtros(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/search/",
        json={"query": "conferencia matutina", "top_k": 4},
    )
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    assert "strategy" in data
```

### Test de Pipeline con Mocks

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ingestion_idempotencia() -> None:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        ("SKIP",), ("SKIP",), ("SKIP",), ("SKIP",), ("SKIP",),
    ]

    with patch("lakehouse.pipeline.ingestion.get_duckdb_connection", return_value=mock_conn):
        from lakehouse.pipeline.ingestion import merge_bronze_html

        result = merge_bronze_html(mock_conn, [{"content_hash": "abc123"}])
        assert result["new_rows"] == 0
        assert result["duplicates"] == 1
```

## Frontend — Vitest

### Configuracion (vitest.config.ts)

```typescript
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    coverage: {
      provider: "v8",
      thresholds: { lines: 80, branches: 75 },
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
```

### Test de Componente Vue

```typescript
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import TokenBar from "@/components/chat/TokenBar.vue";

describe("TokenBar", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("muestra barra verde cuando uso < 90%", () => {
    const wrapper = mount(TokenBar, {
      props: { current: 4000, max: 8192 },
    });
    const bar = wrapper.find('[data-testid="token-fill"]');
    expect(bar.classes()).toContain("bg-emerald-500");
    expect(bar.attributes("style")).toContain("width: 48%");
  });

  it("muestra barra roja cuando uso > 90%", () => {
    const wrapper = mount(TokenBar, {
      props: { current: 7500, max: 8192 },
    });
    const bar = wrapper.find('[data-testid="token-fill"]');
    expect(bar.classes()).toContain("bg-red-500");
  });
});
```

## Evaluacion LLM-as-a-Judge

El comando `python -m lakehouse evaluate-rag` ejecuta el script de evaluacion:

```python
from __future__ import annotations

import json


def evaluate_rag_responses(
    golden_dataset: list[dict],
    *,
    fidelity_threshold: float = 0.90,
    relevance_threshold: float = 0.80,
) -> dict[str, float]:
    # Procesa 50 preguntas del Golden Dataset
    # Usa gemma4 como juez para evaluar fidelidad y relevancia
    scores = {"fidelity": 0.0, "relevance": 0.0, "total_questions": len(golden_dataset)}
    # ... logica de evaluacion
    return scores
```

## Checklist de Verificacion

- [ ] `uv run pytest -xvs` pasa sin errores en backend.
- [ ] `uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90` cumple.
- [ ] `pnpm test:unit` pasa sin errores en frontend.
- [ ] Schemas Pydantic validan casos borde (vacio, max length, invalido).
- [ ] Mocks correctamente aislan dependencias externas (Ollama, llamacpp, DuckDB).
- [ ] `evaluate-rag` alcanza >= 90% fidelidad y >= 80% relevancia.
- [ ] No hay `print()` ni `console.log` en tests — solo asserts.
