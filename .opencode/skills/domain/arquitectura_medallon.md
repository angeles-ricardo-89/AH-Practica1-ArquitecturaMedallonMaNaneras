# Domain Skill: Arquitectura Medallon (Bronze → Silver → Gold)

## Proposito

Definir las reglas estrictas del flujo de datos a traves de las tres capas del Lakehouse, desde
la ingesta de HTML crudo hasta el corpus semantico listo para RAG.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Python + uv + Ruff | `../tech/python_uv_ruff.md` | Scripts de pipeline (ingestion, parsing, enrichment) |
| DuckDB + pgvector | `../tech/duckdb_pgvector.md` | Almacenamiento en DuckLake + busqueda vectorial en pgvector |
| FastAPI + Pydantic + Typer | `../tech/fastapi_pydantic_typer.md` | Schemas Pydantic para validacion de registros; CLI Typer para orquestacion |

## Reglas por Capa

### Bronze — Ingesta Inmune al Ruido

**Proposito:** Almacenar el HTML original descargado garantizando reproducibilidad.

**Reglas:**
- Append-only. Nunca se modifica un registro Bronze existente.
- Agrupado por `ingestion_run_id` (timestamp ISO 8601 de la ejecucion).
- `content_hash` calculado sobre un segmento limpio del DOM (`<main>` o selector configurado), ignorando headers, footers y sidebars dinamicos.
- Cada ejecucion de ingesta genera un nuevo `ingestion_run_id`.

**Esquema Logico:**
```
bronze.raw_html (
    ingestion_run_id TEXT,
    source_url TEXT,
    fetched_at TIMESTAMPTZ,
    raw_html TEXT,
    content_hash TEXT,  -- SHA256 del DOM relevante
    http_status INT
)
```

**Orquestacion:**
```bash
uv run python -m lakehouse pipeline ingest  # CLI via Typer
```

### Silver — Rapida y Determinista

**Proposito:** Convertir HTML a registros Pydantic estandarizados.

**Reglas:**
- **Cero uso de LLMs en esta capa.** Solo selectores HTML y regex deterministicos.
- Parsing basado en etiquetas `<strong>` para detectar secciones (PREGUNTA, RESPUESTA, etc.).
- Variable `pregunta_activa` mantenida durante el parseo para inyectar contexto en los chunks.
- Registros invalidos van a `dlq.silver_rejects` con motivo de rechazo.
- Claves naturales via hashes concatenados (ver `idempotencia_y_merge.md`).

**Esquema Logico:**
```
silver.interventions (
    chunk_key TEXT PRIMARY KEY,       -- SHA256 determinista
    parent_key TEXT,                   -- FK a bronze.raw_html.content_hash
    conference_date DATE,
    participant TEXT,
    chunk_index INT,
    text TEXT,
    pregunta_activa TEXT,              -- Contexto de la pregunta que precede
    source_url TEXT,
    created_at TIMESTAMPTZ
)

silver.conferences (
    conference_date DATE PRIMARY KEY,
    source_url TEXT,
    participant_count INT,
    chunk_count INT,
    ingestion_run_id TEXT
)
```

**Schemas Pydantic:**
```python
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class InterventionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_key: str
    parent_key: str
    conference_date: date
    participant: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=10)
    pregunta_activa: str | None = None
    source_url: str
    parsed_at: datetime


class DLQRejectRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_text: str
    rejection_reason: str
    source_url: str
    rejected_at: datetime
```

### Gold — Semantica y Enriquecida

**Proposito:** Modelos analiticos, extraccion LLM asincrona y RAG Corpus.

**Reglas:**
- Extraccion de entidades (periodista, medio) via `gemma-4-12b` asincrono.
- Payload vectorial limpio sin IDs tecnicos (ver `payload_vectorial_limpio.md`).
- Embeddings generados via Ollama y almacenados en pgvector.
- Indices: B-Tree para fecha/participante, HNSW para vector coseno.

**Esquema Logico (pgvector):**
```
gold.rag_corpus (
    id SERIAL,                          -- Solo PK interna, no clave de negocio
    chunk_key TEXT UNIQUE NOT NULL,     -- FK a silver.interventions
    conference_date DATE NOT NULL,
    participant TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    source_url TEXT,
    pregunta_activa TEXT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT now()
)
```

**Enriquecimiento Asincrono con LLM:**
```python
from __future__ import annotations

from openai import AsyncOpenAI


async def extraer_entidades(
    text: str,
    client: AsyncOpenAI,
    model: str = "gemma-4-12b",
) -> dict[str, str]:
    prompt = (
        "Extrae del siguiente texto el nombre del periodista y el medio de comunicacion. "
        "Responde SOLO en formato JSON: {\"periodista\": \"...\", \"medio\": \"...\"}\n\n"
        f"Texto: {text[:2000]}"
    )
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
```

## Flujo Completo

```
[gob.mx] → Bronze (HTML crudo, content_hash)
              ↓
           Silver (Parsing determinista, Pydantic records)
              ↓
           Gold (LLM enrichment, embeddings, pgvector)
              ↓
           FastAPI (busqueda semantica) + Vue (chat RAG)
```

## Pipeline Ejecutable y Verificable en Docker

El PRD 3.0 (seccion 11.1) exige que el pipeline medallon corra dentro de un contenedor y se verifique con un solo comando.

- Docker Compose debe orquestar un servicio/perfil `pipeline` que ejecute Bronze -> Silver -> Gold -> clustering -> etiquetado con el MISMO codigo de pipeline.
- Ollama y llama.cpp pueden quedar como runtimes locales del host (GPU/pesos), pero como dependencias explicitas con health checks; no pasos manuales ocultos.
- Debe existir un comando unico de verificacion (ej. `make docker-verify`) que use una muestra Bronze congelada y compruebe que las capas producen salidas validas.
- Debe existir un comando documentado para ejecutar el pipeline completo contra el corpus real.
- La demostracion local del agente no realiza llamadas a Gemini ni a otros servicios externos.

**Verificacion:**
- [ ] `make docker-verify` produce evidencia verificable de Bronze, Silver y Gold (CA-D02, CA-D03).
- [ ] Una instalacion limpia levanta la aplicacion con instrucciones reproducibles (CA-D01).

## Tiempo de Reconstruccion (CA-08)

Una reconstruccion total desde Bronze a Gold (sin procesos LLM asincronos) para 3 meses de datos
debe completarse en <= 15 minutos.

## Checklist de Verificacion

- [ ] Bronze almacena HTML intacto con content_hash determinista.
- [ ] Bronze es append-only: re-ejecutar con mismos sources no modifica registros existentes.
- [ ] Silver parsea sin usar LLMs — solo regex y selectores HTML.
- [ ] Silver produce registros Pydantic validados.
- [ ] DLQ captura y documenta registros invalidos.
- [ ] Gold genera embeddings para cada chunk.
- [ ] Gold almacena embeddings en pgvector con indice HNSW.
- [ ] Reconstruccion total <= 15 minutos para 3 meses de datos.
