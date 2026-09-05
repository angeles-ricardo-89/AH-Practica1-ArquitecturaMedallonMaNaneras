# Tech Skill: DuckDB + pgvector

## Proposito

Definir los patrones de conexion y consulta para el catalogo DuckLake (DuckDB con catalogo Postgres)
y la busqueda vectorial via pgvector.

## Referencias

- Python + uv + Ruff: `../tech/python_uv_ruff.md`

## DuckDB — Conexion Catalogo-Lakehouse

### Conexion con Catalogo en Postgres

```python
from __future__ import annotations

import duckdb


def get_duckdb_connection(
    catalog_dsn: str,
    data_path: str = "/data/lakehouse/ducklake_files.duckdb",
) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute("INSTALL postgres; LOAD postgres;")
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute(
        "ATTACH '' AS catalog_db (TYPE postgres, SECRET s1);"
    )
    conn.execute(f"""
        CREATE SECRET s1 (
            TYPE postgres,
            CONNECTION_STRING '{catalog_dsn}',
            ALLOW_LOCAL_INFILE true
        );
    """)
    conn.execute(f"SET data_dir = '{data_path}';")
    return conn
```

### Idempotencia con MERGE INTO

```python
from __future__ import annotations

import hashlib

import duckdb


def generate_chunk_key(
    conference_date: str,
    participant: str,
    chunk_index: int,
    text: str,
) -> str:
    raw = f"{conference_date}|{participant}|{chunk_index}|{text[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def merge_silver_chunks(
    conn: duckdb.DuckDBPyConnection,
    chunks: list[dict],
) -> dict[str, int]:
    temp_table = "temp_silver_chunks"
    target_table = "silver.chunks"

    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_table} AS
        SELECT * FROM (VALUES {_build_values(chunks)})
        AS t(chunk_key, parent_key, chunk_index, text, participant, date)
    """)

    result = conn.execute(f"""
        MERGE INTO {target_table} AS target
        USING {temp_table} AS source
        ON target.chunk_key = source.chunk_key
        WHEN NOT MATCHED THEN INSERT BY NAME
    """)
    conn.commit()

    rows_affected = result.fetchall()
    return {
        "total_source": len(chunks),
        "new_rows": sum(1 for r in rows_affected if r[0] == "INSERT"),
        "duplicates": sum(1 for r in rows_affected if r[0] == "SKIP"),
    }
```

## pgvector — Conexion y Consultas

### Conexion a PostgreSQL con pgvector

```python
from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector


@dataclass
class VectorSearchResult:
    conference_date: str
    participant: str
    chunk_text: str
    source_url: str
    similarity: float
    pregunta_activa: str | None = None


def get_pg_connection(dsn: str) -> psycopg.Connection:
    conn = psycopg.connect(dsn)
    register_vector(conn)
    return conn
```

### Busqueda Semantica (HNSW)

```python
from __future__ import annotations

from typing import Any


def vector_search(
    conn: psycopg.Connection,
    embedding: list[float],
    *,
    top_k: int = 8,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    participante: str | None = None,
) -> list[dict[str, Any]]:
    query = """
    SELECT
        conference_date,
        participant,
        chunk_text,
        source_url,
        pregunta_activa,
        1.0 - (embedding <=> %s::vector) AS similarity
    FROM gold.rag_corpus
    WHERE 1=1
    """
    params: list[Any] = [embedding]

    if fecha_inicio:
        query += " AND conference_date >= %s"
        params.append(fecha_inicio)
    if fecha_fin:
        query += " AND conference_date <= %s"
        params.append(fecha_fin)
    if participante:
        query += " AND participant ILIKE %s"
        params.append(f"%{participante}%")

    query += " ORDER BY embedding <=> %s::vector LIMIT %s"
    params.extend([embedding, top_k])

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
```

### Creacion de Indices (Migracion SQL)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE gold.rag_corpus (
    id SERIAL PRIMARY KEY,
    chunk_key TEXT NOT NULL UNIQUE,
    conference_date DATE NOT NULL,
    participant TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    source_url TEXT,
    pregunta_activa TEXT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_rag_corpus_date ON gold.rag_corpus (conference_date);
CREATE INDEX idx_rag_corpus_participant ON gold.rag_corpus (participant);
CREATE INDEX idx_rag_corpus_embedding_hnsw
    ON gold.rag_corpus
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
```

### Generacion de Embeddings con Ollama

```python
from __future__ import annotations

import json

import httpx


async def generate_embedding(
    text: str,
    *,
    base_url: str = "http://localhost:11434",
    model: str = "embeddinggemma",
) -> list[float]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]
```

## Separacion de Espacios Vectoriales (local vs productivo)

Dueña de esta regla junto con el PRD 3.0 (seccion 11.3). Invariante dura: **nunca mezclar embeddings de modelos diferentes**, aunque compartan 768 dimensiones.

- Corpus local: EmbeddingGemma via Ollama. Corpus productivo: `gemini-embedding-001` (768 dims, normalizacion, tareas `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`).
- Cada indice registra metadatos obligatorios: proveedor+modelo, dimension, tipo de tarea, version del formato de texto embebido, fecha de construccion y hash del corpus.
- Produccion se construye por reindexacion TOTAL hacia Neon; el servicio falla al iniciar si la config de consulta no coincide con los metadatos del indice (fallar cerrado).
- Los filtros relacionales (fecha/participante) se aplican ANTES del ranking vectorial cuando estan presentes; nunca despues de descartar candidatos.

## Herramientas

- **DuckDB**: Motor analitico embebido con soporte para catalogo externo (Postgres).
- **pgvector**: Extension de PostgreSQL para busqueda vectorial.
- **Ollama**: Servidor local de modelos de embedding (embeddinggemma).
- **psycopg**: Driver PostgreSQL para Python.

## Checklist de Verificacion

- [ ] DuckDB puede hacer ATTACH al catalogo Postgres sin errores.
- [ ] MERGE INTO en Silver no duplica registros en ejecuciones repetidas.
- [ ] pgvector acepta embeddings de dimension correcta (768 para embeddinggemma).
- [ ] Indice HNSW acelera busquedas: query vectorial < 100ms para corpus < 10k registros.
- [ ] Ollama responde con embedding del tamano esperado (verificar `len(embedding)`).
- [ ] Busqueda hibrida (filtros + vector) devuelve resultados correctos.
