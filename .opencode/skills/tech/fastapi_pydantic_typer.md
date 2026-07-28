# Tech Skill: FastAPI + Pydantic V2 + Typer

## Proposito

Definir los patrones de diseno para la API REST (FastAPI), validacion de datos (Pydantic V2) y CLI (Typer) del Lakehouse Mañaneras.

## Referencias

- Python + uv + Ruff: `../tech/python_uv_ruff.md`

## FastAPI — Patrones de Inyeccion y Routers

### Estructura de Modulos

```
backend/src/lakehouse/
    api/
        __init__.py
        deps.py          # Dependencias inyectables
        routers/
            __init__.py
            health.py     # GET /health
            search.py     # POST /search (RAG)
            chat.py       # POST /chat
            observability.py  # GET /observability/logs
    main.py
```

### Inyeccion de Dependencias (deps.py)

```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from httpx import AsyncClient
from openai import AsyncOpenAI

from lakehouse.config import Settings


def get_settings() -> Settings:
    return Settings()


async def get_llamacpp_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[AsyncOpenAI, None]:
    client = AsyncOpenAI(
        base_url=settings.llamacpp_base_url,
        api_key="not-needed",
    )
    try:
        yield client
    finally:
        await client.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMDep = Annotated[AsyncOpenAI, Depends(get_llamacpp_client)]
```

### Router Pattern (routers/search.py)

```python
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lakehouse.api.deps import SettingsDep
from lakehouse.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "/",
    response_model=SearchResponse,
    summary="Busqueda semantica hibrida",
    description="Busca en el corpus Gold usando filtros relacionales + distancia vectorial",
)
async def search(
    payload: SearchRequest,
    settings: SettingsDep,
) -> SearchResponse:
    ...
```

### Configuracion de Settings con Pydantic V2

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_env: str = "local"
    postgres_host: str = "postgres"
    postgres_db: str = "mananeras"
    ducklake_catalog: str = "postgres"
    ducklake_data_path: str = "/data/lakehouse/ducklake_files.duckdb"
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    llamacpp_base_url: str = "http://localhost:9200/v1"
    llamacpp_model: str = "gemma4"
    rag_top_k: int = 8
    max_context_tokens: int = 8192

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://postgres:postgres@{self.postgres_host}:5432/{self.postgres_db}"
        )
```

### Schemas con Pydantic V2 (schemas/search.py)

```python
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=500)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    participante: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class SearchResultItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    conference_date: date
    participant: str
    chunk_text: str
    source_url: str
    similarity: float
    pregunta_activa: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    strategy: str  # "hnsw", "relational_then_vector", "hybrid"
```

## Typer — CLI

```python
from __future__ import annotations

import typer

from lakehouse.pipeline.ingestion import run_ingestion
from lakehouse.pipeline.evaluate_rag import run_evaluation

app = typer.Typer(no_args_is_help=True)


@app.command()
def ingest(dry_run: bool = typer.Option(False, help="Simular sin escribir")) -> None:
    """Ejecuta la ingesta Bronze."""
    run_ingestion(dry_run=dry_run)


@app.command()
def evaluate_rag() -> None:
    """Ejecuta la evaluacion RAG con gemma4 como juez."""
    run_evaluation()
```

## Checklist de Verificacion

- [ ] Settings carga correctamente desde `.env`.
- [ ] Todos los endpoints usan `response_model` con schema Pydantic V2.
- [ ] Schemas usan `extra="forbid"` para validacion estricta.
- [ ] Dependencias injectables usan `Annotated[Type, Depends(...)]`.
- [ ] Typer CLI expone `--help` y comandos documentados.
- [ ] `uv run fastapi dev src/lakehouse/main.py` levanta sin errores.
- [ ] `curl http://localhost:8000/health` devuelve `{"status": "ok"}`.
