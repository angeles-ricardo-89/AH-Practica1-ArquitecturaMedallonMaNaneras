# Domain Skill: Payload Vectorial Limpio

## Proposito

Definir el formato exacto del texto que se inyecta a Ollama para generar embeddings.
El payload debe ser denso, puramente descriptivo y libre de IDs tecnicos, URLs internas,
hashes, o cualquier metadata que no aporte valor semantico al vector.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| DuckDB + pgvector | `../tech/duckdb_pgvector.md` | `generate_embedding()` recibe el payload limpio generado aqui |

## Reglas del Formato

### Estructura Exacta

Todo texto que se envia a Ollama para embedding debe seguir este formato:

```
Contexto: Conferencia del [FECHA]
Participante: [NOMBRE]
Pregunta activa: [TEXTO DE LA PREGUNTA]
Respuesta: [TEXTO DEL CHUNK LIMPIO]
```

### Componentes

| Campo | Fuente | Obligatorio | Ejemplo |
|-------|--------|-------------|---------|
| `FECHA` | `silver.interventions.conference_date` | SI | "2025-01-15" |
| `NOMBRE` | `silver.interventions.participant` | SI | "Carlos Lopez • El Universal" |
| `TEXTO DE LA PREGUNTA` | `silver.interventions.pregunta_activa` | SI (si existe) | "Cual es la postura sobre..." |
| `TEXTO DEL CHUNK LIMPIO` | `silver.interventions.text` | SI | Texto completo del chunk |

### Lo que NUNCA debe incluirse

- `chunk_key`, `parent_key`, u otros hashes tecnicos
- `ingestion_run_id`
- URLs (source_url, gob.mx)
- Timestamps de procesamiento (parsed_at, created_at)
- Indices numericos (chunk_index)
- IDs de base de datos (SERIAL, rowid)

### Generacion del Payload

```python
from __future__ import annotations

from datetime import date


def build_embedding_payload(
    conference_date: date,
    participant: str,
    pregunta_activa: str | None,
    chunk_text: str,
) -> str:
    payload_parts = [
        f"Contexto: Conferencia del {conference_date}",
        f"Participante: {participant}",
    ]
    if pregunta_activa:
        payload_parts.append(f"Pregunta activa: {pregunta_activa}")
    payload_parts.append(f"Respuesta: {chunk_text}")
    return "\n".join(payload_parts)
```

### Ejemplo Concreto

**Entrada (registro Silver):**
```
chunk_key: "e3b0c44298fc1c149afbf4c8996fb924..."
conference_date: 2025-01-15
participant: "Carlos Lopez"
pregunta_activa: "PREGUNTA: Cual es la postura sobre la reforma energetica?"
text: "La Presidenta respondio que la reforma energetica busca fortalecer a PEMEX y CFE como empresas publicas estrategicas. No se trata de eliminar la inversion privada sino de garantizar la soberania energetica nacional."
```

**Salida (payload para Ollama):**
```
Contexto: Conferencia del 2025-01-15
Participante: Carlos Lopez
Pregunta activa: PREGUNTA: Cual es la postura sobre la reforma energetica?
Respuesta: La Presidenta respondio que la reforma energetica busca fortalecer a PEMEX y CFE como empresas publicas estrategicas. No se trata de eliminar la inversion privada sino de garantizar la soberania energetica nacional.
```

## Impacto en la Calidad del Embedding

Un payload limpio es critico porque:

1. **Relevancia de busqueda:** Incluir hashes o IDs en el texto contamina la distancia coseno,
   haciendo que resultados irrelevantes aparezcan por similitud de caracteres aleatorios.

2. **Consistencia semantica:** El campo `Pregunta activa` permite que la busqueda semantica
   recupere respuestas incluso cuando la query del usuario esta formulada como pregunta
   (porque el embedding captura la relacion pregunta-respuesta).

3. **Alucinaciones reducidas:** Un payload contextualizado (con fecha, participante y pregunta)
   da al LLM mas informacion para generar respuestas fieles. Ver CA-06.

## Checklist de Verificacion

- [ ] `build_embedding_payload()` genera texto sin hashes, IDs, URLs.
- [ ] Payload incluye Contexto, Participante, Pregunta activa (si existe), Respuesta.
- [ ] No se incluye chunk_key en el payload.
- [ ] No se incluye source_url en el payload.
- [ ] No se incluyen timestamps de procesamiento.
- [ ] El payload es determinista: mismos inputs producen mismo string siempre.
- [ ] La busqueda semantica con payload limpio produce resultados mas relevantes que con payload crudo.
