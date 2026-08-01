# Filtro Temporal Hibrido para RAG (Self-Querying)

## Problema

El pipeline RAG actual ejecuta busqueda semantica pura por similitud de cosenos sobre toda la tabla
`gold.rag_corpus`, sin considerar la dimension temporal. Si un usuario pregunta "que dijo Sheinbaum
ayer sobre el T-MEC", el sistema recupera los chunks semanticamente mas cercanos de cualquier fecha,
potencialmente devolviendo informacion irrelevante o del periodo equivocado. No existe ningun
mecanismo para filtrar por `conference_date` antes del ranking por similitud.

Ademas, las palabras temporales ("ayer", "lunes pasado", "lo mas reciente") contaminan el embedding
de la query, reduciendo la precision del ranking semantico.

## Solucion

Agregar una etapa de pre-procesamiento al endpoint `POST /chat/` que:

1. **Extrae metadatos temporales** via llamacpp (Gemma 4) con prompt estricto + validacion Pydantic
   + reintentos, devolviendo un `TimeFilterOut` estructurado.
2. **Limpia la query** eliminando palabras temporales del texto antes de generar el embedding.
3. **Ejecuta consulta hibrida** en PostgreSQL: si `requiere_filtro_tiempo=true`, aplica
   `BETWEEN` sobre `conference_date` ANTES del ranking `<=>` por similitud; si no, mantiene la
   busqueda semantica pura actual.
4. **Maneja el vacio temporal**: si no hay resultados en el rango, el LLM generador responde que
   no tiene informacion, en lugar de devolver resultados semanticamente similares de otras fechas.

## Diseno

### 1. Arquitectura General

```
POST /chat/ {query, top_k}
       │
       ▼
┌─────────────────┐
│ TemporalParser  │  datetime.now() inyectado en system prompt
│ .extraer(query) │
└────────┬────────┘
         │ TimeFilterOut
         ▼
┌─────────────────┐
│ Ollama embed    │  texto_busqueda_semantica (sin ruido temporal)
└────────┬────────┘
         │ vector[768]
         ▼
 requiere_filtro?
   /        \
 TRUE       FALSE
  │           │
  ▼           ▼
┌──────────┐ ┌──────────────────┐
│ BETWEEN  │ │ busqueda pura    │
│ + <=>    │ │ <=> (actual)     │
└────┬─────┘ └────────┬─────────┘
     └────────┬───────┘
              ▼
     ┌──────────────────┐
     │ ContextBuilder    │ + nota de fallback si aplica
     └────────┬─────────┘
              ▼
     ┌──────────────────┐
     │ llamacpp gen     │
     └──────────────────┘
```

### 2. Schema Pydantic: `TimeFilterOut`

Archivo nuevo: `backend/src/lakehouse/schemas/temporal.py`

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

### 3. TemporalParser

Archivo nuevo: `backend/src/lakehouse/services/temporal_parser.py`

#### 3.1 System Prompt (con datetime.now() inyectado dinamicamente)

```
Eres un parser de consultas temporales. Tu UNICA tarea es extraer informacion
de tiempo de la pregunta del usuario y devolver un objeto JSON.

REGLAS:
- La fecha/hora actual del servidor es: {datetime.now().isoformat()}
- Usa esa referencia para calcular fechas relativas (ayer, la semana pasada, etc.)
- fecha_inicio debe ser "YYYY-MM-DD 00:00:00"
- fecha_fin debe ser "YYYY-MM-DD 23:59:59"
- texto_busqueda_semantica debe contener SOLO la parte semantica de la query,
  eliminando TODAS las palabras temporales (fechas, "ayer", "lunes", "reciente",
  "semana pasada", "el miercoles", etc.)
- Si la query NO tiene intencion temporal, devuelve requiere_filtro_tiempo=false
  y fecha_inicio/fecha_fin en null. El texto_busqueda_semantica sera la query completa.
- Devuelve UNICAMENTE el JSON, sin texto adicional, sin markdown, sin explicaciones.

Ejemplos:
Query: "Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?"
→ Si hoy es miercoles 2026-08-05:
{"requiere_filtro_tiempo":true, "fecha_inicio":"2026-08-03 00:00:00",
 "fecha_fin":"2026-08-03 23:59:59",
 "texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC en la conferencia"}

Query: "Cual es la postura sobre energia nuclear?"
→ {"requiere_filtro_tiempo":false, "fecha_inicio":null, "fecha_fin":null,
   "texto_busqueda_semantica":"Cual es la postura sobre energia nuclear"}
```

#### 3.2 Logica de Reintentos (3 niveles de defensa)

```
Intento 1: prompt estricto, temperature=0.1, max_tokens=200
  → llamacpp POST /v1/chat/completions
  → strip() la respuesta, json.loads()
  → TimeFilterOut.model_validate(dict)
  → OK? retornar TimeParserResult(fallback_ocurrido=False)

Intento 2: limpiar respuesta (remover ```json, markdown, texto sobrante)
  → regex extraer primer { ... } con balanceo de llaves
  → json.loads() → TimeFilterOut.model_validate()
  → OK? retornar TimeParserResult(fallback_ocurrido=False)

Intento 3 (fallback final):
  → filter_out = TimeFilterOut(
        requiere_filtro_tiempo=False,
        texto_busqueda_semantica=query_original,
    )
  → retornar TimeParserResult(fallback_ocurrido=True)
```

#### 3.3 Configuracion

Agregar a `backend/src/lakehouse/config.py`:

```python
temporal_parser_temperature: float = 0.1
temporal_parser_max_retries: int = 3
temporal_parser_max_tokens: int = 200
```

### 4. Consulta Hibrida SQL

Archivo modificado: `backend/src/lakehouse/services/rag_search.py`

Nuevo metodo `search_with_date_filter()`:

```python
async def search_with_date_filter(
    query_vector: list[float],
    top_k: int,
    fecha_inicio: str,
    fecha_fin: str,
) -> list[dict[str, object]]:
    async with pg_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT conference_date, conference_id, participant,
                       chunk_text, url, pregunta_activa,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM gold.rag_corpus
                WHERE conference_date BETWEEN %s::date AND %s::date
                  AND LENGTH(chunk_text) >= 50
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vector, fecha_inicio, fecha_fin, query_vector, top_k),
            )
            rows = await cur.fetchall()
            return [_row_to_dict(row) for row in rows]
```

**Notas:**
- `conference_date` ya tiene indice B-Tree (`idx_rag_corpus_conference_date`), el `BETWEEN` usa
  index scan nativo de PostgreSQL.
- El `ORDER BY embedding <=>` opera solo sobre el subconjunto filtrado, reduciendo el costo
  computational respecto a ordenar toda la tabla.
- Si `BETWEEN` no encuentra filas, retorna `[]` — el chat endpoint manejara el conjunto vacio.

### 5. Orquestacion en Chat Endpoint

Archivo modificado: `backend/src/lakehouse/api/routers/chat.py`

```python
@router.post("/chat/")
async def chat(request: ChatRequest, ...):
    # 1. Parseo temporal
    parser_result = temporal_parser.extraer(request.query)

    # 2. Embedding con texto semantico limpio
    query_vector = await embed(parser_result.filter_out.texto_busqueda_semantica)

    # 3. Busqueda hibrida
    if parser_result.filter_out.requiere_filtro_tiempo:
        sources = await search_with_date_filter(
            query_vector, request.top_k,
            parser_result.filter_out.fecha_inicio,
            parser_result.filter_out.fecha_fin,
        )
    else:
        sources = await search_gold_corpus(query_vector, request.top_k)

    # 4. Contexto + generacion
    context = context_builder.build(
        sources=sources,
        query=request.query,
        nota_fallback=parser_result.fallback_ocurrido,
    )
    answer = await llamacpp_generate(context)
    return ChatResponse(answer=answer, sources=sources, ...)
```

### 6. ContextBuilder: Nota de Fallback

Archivo modificado: `backend/src/lakehouse/services/context_builder.py`

El metodo `build()` acepta un nuevo parametro opcional `nota_fallback: bool = False`. Si es `True`,
inyecta al inicio del contexto:

```
NOTA: No se pudo determinar automaticamente el filtro temporal de la consulta.
Los resultados pueden pertenecer a cualquier fecha.
---
[fuentes formateadas...]
```

### 7. Conjunto Vacio Temporal

Cuando `search_with_date_filter()` retorna `[]`:
- `ContextBuilder` recibe `sources=[]` → genera contexto: "No se encontraron resultados para el
  rango de fechas solicitado."
- llamacpp responde: "No tengo informacion sobre ese periodo." o variante.
- No se hace fallback a busqueda sin filtro — se respeta la intencion temporal del usuario.

## Archivos involucrados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/schemas/temporal.py` | Nuevo — `TimeFilterOut`, `TimeParserResult` |
| `backend/src/lakehouse/services/temporal_parser.py` | Nuevo — `TemporalParser` con llamada HTTP a llamacpp + Pydantic + retry |
| `backend/src/lakehouse/services/rag_search.py` | Modificado — nuevo metodo `search_with_date_filter()` con SQL BETWEEN + `<=>` |
| `backend/src/lakehouse/api/routers/chat.py` | Modificado — orquestacion: parser → embed → busqueda hibrida → context → gen |
| `backend/src/lakehouse/services/context_builder.py` | Modificado — parametro `nota_fallback`, manejo de sources vacio |
| `backend/src/lakehouse/config.py` | Modificado — `temporal_parser_temperature`, `temporal_parser_max_retries`, `temporal_parser_max_tokens` |

## Casos borde

- **Query con fecha exacta:** "conferencia del 15 de julio 2025" → `requiere_filtro=true`,
  `fecha_inicio="2025-07-15 00:00:00"`, `fecha_fin="2025-07-15 23:59:59"`, texto semantico sin
  "15 de julio 2025".
- **Query con fecha relativa (ayer):** "lo que dijo ayer sobre el T-MEC" → fecha inicio/fin = ayer
  respecto a `datetime.now()` del servidor, texto sin "ayer".
- **Query con fecha relativa (dia de semana):** "conferencia del lunes pasado" → fecha inicio/fin
  = lunes anterior calculado por el LLM, texto sin "lunes pasado".
- **Query sin intencion temporal:** "postura sobre energia nuclear" → `requiere_filtro=false`,
  `texto_busqueda_semantica` = query original, busqueda semantica pura.
- **LLM responde con markdown:** ` ```json {...} ``` ` + texto explicativo → el intento 2 limpia
  y extrae el JSON correctamente.
- **LLM responde JSON invalido 3 veces:** fallback → `requiere_filtro=false`, busqueda pura,
  `nota_fallback=True` en contexto.
- **BETWEEN no encuentra filas:** `search_with_date_filter()` retorna `[]`. El chat responde
  "No tengo informacion sobre ese periodo."
- **Filtro temporal + ranking:** 5+ resultados en rango, `top_k=3` → retorna los 3 mas similares
  dentro del rango, no de toda la tabla.
- **Query en horario sin servidor:** `datetime.now()` se obtiene en cada llamada a `extraer()`,
  siempre actualizado.
- **Reintentos agotan timeout:** `httpx.TimeoutException` en los 3 intentos → fallback
  (`fallback_ocurrido=True`), busqueda pura, nota en contexto.

## Verificacion

1. `ruff check --fix && ruff format` en archivos modificados
2. `uv run pyright src/` sin errores
3. `uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90` (coverage >= 90% en
   modulos nuevos y modificados)
4. Test manual: `curl -X POST http://localhost:8000/chat/ -d '{"query":"que dijo Sheinbaum ayer
   sobre el T-MEC"}'` → solo resultados de la fecha de ayer.
5. Test manual: `curl -X POST http://localhost:8000/chat/ -d '{"query":"que dijo Sheinbaum ayer
   sobre el T-MEC"}'` con tabla vacia en esa fecha → respuesta "No tengo informacion sobre ese
   periodo".

## No incluido en este feature

- Gramatica formal (GBNF/JSON Schema) en llamacpp — se usa prompt engineering estricto con
  validacion Pydantic + reintentos. Si el servidor llamacpp o futuras versiones de llama_cpp
  Python soportan `response_format` con `json_schema`, se podra agregar como mejora.
- Filtros temporales en `POST /search/` — se mantiene busqueda semantica pura. El filtro temporal
  solo aplica al endpoint `/chat/`.
- Filtros compuestos (temporal + participante + pregunta_activa) — alcance limitado a filtro
  temporal solamente.
- Cache de resultados de parseo temporal — cada query se parsea individualmente.
- Soporte para multiples rangos temporales en una misma query.
