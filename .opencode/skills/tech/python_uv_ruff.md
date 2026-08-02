# Tech Skill: Python 3.13 + uv + Ruff

## Proposito

Definir las reglas estrictas de escritura de codigo Python en este proyecto, gestion de dependencias con `uv`, y calidad de codigo con `ruff`.

## Reglas

### Gestion de Entorno y Dependencias

**Exclusivo `uv`. Prohibido pyenv, pip, poetry, conda.**

```bash
# Inicializar entorno (solo una vez)
uv venv --python 3.13

# Agregar dependencia
uv add fastapi

# Agregar dependencia de desarrollo
uv add --dev pytest pytest-cov

# Sincronizar lockfile con pyproject.toml
uv sync

# Ejecutar script dentro del entorno
uv run python -m lakehouse.pipeline
```

### Estructura de pyproject.toml

```toml
[project]
name = "lakehouse"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "duckdb>=1.1.0",
    "psycopg[binary]>=3.2.0",
    "pgvector>=0.3.0",
    "pydantic>=2.10.0",
    "typer>=0.15.0",
    "httpx>=0.28.0",
    "beautifulsoup4>=4.12.0",
    "openai>=1.55.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-cov>=6.0.0",
    "pytest-asyncio>=0.25.0",
    "ty>=0.1.0",
    "ruff>=0.8.0",
]

[tool.uv]
dev-dependencies = ["pytest>=8.3.0", "pytest-cov>=6.0.0", "ruff>=0.8.0"]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM", "RET", "ARG", "PTH", "RUF"]
ignore = ["ARG001", "ARG002", "RET504"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true

[tool.ruff.lint.isort]
known-first-party = ["lakehouse"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=90"
```

### Typechecking

Usar `ty` (typecheck estricto) desde `uv`:

```bash
uv run ty check
```

### Reglas de Estilo

- Type hints obligatorios en TODAS las firmas de funciones publicas.
- Usar `from __future__ import annotations` en TODO archivo Python.
- Docstrings en formato Google-style para modulos, clases y funciones publicas.
- Nombres de modulos: snake_case. Clases: PascalCase. Funciones/variables: snake_case.

### Snippet de Ejemplo

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict


class IngestionManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    source_url: str
    started_at: datetime
    html_count: int = 0
    status: str = "pending"


async def fetch_page(url: str, *, timeout: float = 30.0) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
```

## Herramientas

- `uv`: Gestion de dependencias y entornos virtuales.
- `ruff`: Linter + formatter (reemplaza flake8, isort, black).
- `ty`: Typechecker estricto (alternativa ligera a mypy/pyright).

## Checklist de Verificacion

- [ ] `uv run ruff check` pasa sin errores.
- [ ] `uv run ruff format --check` no reporta cambios pendientes.
- [ ] `uv run ty check` no reporta errores de tipo.
- [ ] `uv sync` resuelve sin conflictos.
- [ ] No hay imports de `pip`, `poetry`, `conda` en ningun archivo.
- [ ] pyproject.toml declara `requires-python = ">=3.13"`.
- [ ] Todo archivo .py inicia con `from __future__ import annotations`.
