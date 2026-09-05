# Domain Skill: Memoria RAG y Limite de Tokens

> **Alcance:** esta skill gobierna SOLO la ventana de contexto (truncado FIFO de tokens) en el
> prompt del chat RAG. NO gobierna la persistencia de conversaciones, el aislamiento entre
> usuarios ni la retencion de 30 dias: eso es responsabilidad de `memoria_conversacional.md`.
> Nota: valor canonico `MAX_CONTEXT_TOKENS = 10000` (confirmado por el usuario). Debe exponerse por una API autenticada.

## Proposito

Definir las reglas de gestion de la ventana de contexto (MAX_CONTEXT_TOKENS) tanto en el backend
como en la UI del chat RAG, garantizando que el sistema no envie mas tokens de los que el modelo
puede procesar y que el usuario tenga visibilidad del consumo.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Vue 3 + Pinia + Tailwind | `../tech/vue3_pinia_tailwind.md` | TokenBar en la UI, store de chat en Pinia |
| FastAPI + Pydantic + Typer | `../tech/fastapi_pydantic_typer.md` | Endpoint /chat gestiona el contexto en backend |
| DuckDB + pgvector | `../tech/duckdb_pgvector.md` | Recuperacion de chunks relevantes (top_k) |

## Reglas

### Constante Global

```python
# backend/src/lakehouse/config.py
MAX_CONTEXT_TOKENS: int = 10000  # Configurable via .env
```

### Estimacion de Tokens (Backend)

El backend usa un estimador local simple para contar tokens sin depender de un tokenizador externo:

```python
from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimador conservador: ~4 caracteres por token para espanol."""
    return max(1, len(text) // 4)


def build_chat_context(
    user_query: str,
    retrieved_chunks: list[str],
    conversation_history: list[dict[str, str]],
    max_tokens: int = 10000,
) -> str:
    """Construye el prompt del sistema respetando MAX_CONTEXT_TOKENS."""
    system_prompt = (
        "Eres un asistente que responde preguntas sobre las conferencias "
        "matutinas de la Presidenta de Mexico. Usa UNICAMENTE la evidencia "
        "proporcionada. Si no encuentras respuesta en la evidencia, dilo "
        "explicitamente. Cita la fuente (fecha, participante)."
    )
    used = estimate_tokens(system_prompt)
    available = max_tokens - used - 500  # 500 tokens de margen para la respuesta

    chunks_text = ""
    for chunk in retrieved_chunks:
        chunk_tokens = estimate_tokens(chunk)
        if used + chunk_tokens > available:
            break
        chunks_text += f"\n---\n{chunk}"
        used += chunk_tokens

    history_text = ""
    for msg in conversation_history[-6:]:  # ultimos 6 mensajes max
        history_text += f"{msg['role']}: {msg['content']}\n"

    return (
        f"{system_prompt}\n\n"
        f"Evidencia:\n{chunks_text}\n\n"
        f"Historial:\n{history_text}\n\n"
        f"Pregunta: {user_query}"
    )
```

### Gestion en la UI (Vue + Pinia)

La UI muestra una barra de consumo de tokens. Reglas:

1. **Verde** (< 90%): Operacion normal.
2. **Amarillo** (>= 80%): Advertencia visual, sin bloqueo.
3. **Rojo** (>= 90%): Alerta al usuario. El backend automaticamente descarta
   los mensajes mas antiguos del historial (FIFO) para liberar tokens.

```typescript
// stores/chat.ts
const TOKEN_WARNING_THRESHOLD = 0.8;
const TOKEN_CRITICAL_THRESHOLD = 0.9;

watch(tokenUsagePercent, (value) => {
  if (value >= 90) {
    showWarning.value = true;
    warningMessage.value =
      "La ventana de contexto esta al 90%. Los mensajes mas antiguos seran descartados.";
  }
});
```

### Estrategia de Truncado

Cuando los chunks recuperados + historial exceden MAX_CONTEXT_TOKENS:

1. **Siempre preservar:** system prompt + user query actual (no se truncan).
2. **Truncar en orden:**
   a. Chunks menos relevantes (menor similarity, del final de la lista).
   b. Historial de conversacion mas antiguo (FIFO).
3. **Registrar en logs:** cuando ocurre un truncado, loggear cuantos tokens se descartaron.

### Evidencia y Trazabilidad

Cada respuesta del chat DEBE incluir tarjetas de evidencia clickeables con:
- Fecha de la conferencia
- Nombre del participante
- Fragmento textual usado
- URL fuente

Esto se logra devolviendo en la respuesta del endpoint `/chat` no solo el texto generado
sino tambien el array de `source_chunks` usados.

```python
class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    token_usage: TokenUsage


class SourceChunk(BaseModel):
    conference_date: date
    participant: str
    chunk_text: str
    source_url: str
    similarity: float


class TokenUsage(BaseModel):
    used: int
    max: int
    percent: float
    truncated: bool
```

## Checklist de Verificacion

- [ ] MAX_CONTEXT_TOKENS configurable via .env (default 10000).
- [ ] `estimate_tokens()` produce estimaciones consistentes.
- [ ] `build_chat_context()` nunca excede MAX_CONTEXT_TOKENS.
- [ ] TokenBar en UI cambia de verde → amarillo → rojo correctamente.
- [ ] Alerta visual cuando > 90%.
- [ ] Truncado FIFO del historial funciona (mensajes antiguos desaparecen).
- [ ] Respuesta del chat incluye array de `sources` con evidencia trazable.
- [ ] System prompt y user query nunca se truncan.
