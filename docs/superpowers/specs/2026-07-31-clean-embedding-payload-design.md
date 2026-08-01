# Payload de Embedding Limpio

## Problema

El texto que se incrusta con Ollama contiene ruido estructural que diluye la precision de la similitud coseno:

```
Contexto: Conferencia del 2024-10-01
Participante: PRESIDENTA
Pregunta activa: Como va la reforma energetica?
Respuesta: Avanzamos en paneles solares...
```

Palabras como `Contexto:`, `Conferencia`, `Participante:`, fechas, y nombres de participantes ocupan dimensiones del vector 768-dim sin valor discriminativo. `Participante: PRESIDENTA` aparece en el 80% de los chunks; `Contexto: Conferencia del` en el 100%. Ambos son ruido que desplaza el vector lejos del contenido semantico relevante.

Dos chunks sobre "reforma energetica" con distinto participante y fecha tienen vectores mas lejanos de lo que deberian porque el nombre del participante y la fecha consumen dimensiones del embedding -- dimensiones que el modelo `embeddinggemma` asigna a TODO el texto por igual.

La brecha entre 99% relevancia y 34% fidelidad en el evaluador RAG confirma este diagnostico: la busqueda vectorial recupera chunks del tema correcto (alta relevancia), pero el LLM no recibe los chunks con suficiente precision semantica para reconstruir la respuesta de referencia (baja fidelidad).

## Solucion

Separar la generacion del texto de embedding del texto de payload almacenado en Gold:

- **`build_embedding_payload`**: sin cambios. Sigue generando el texto con metadata completa (`Contexto:`, `Participante:`, fecha) para la columna `payload` de `gold.rag_corpus` (trazabilidad).
- **`build_embedding_text`**: funcion nueva. Genera texto semantico limpio con solo pregunta activa y respuesta, usando etiquetas minimales `P:` y `R:`.

### Funcion nueva: `build_embedding_text`

```python
def build_embedding_text(intervention: InterventionRecord) -> str:
    pregunta = intervention.pregunta_activa
    if pregunta:
        return f"P: {pregunta}\nR: {intervention.text}"
    return f"R: {intervention.text}"
```

**Comportamiento:**

| `pregunta_activa` | Texto generado |
|---|---|
| `"Como va la reforma energetica?"` | `P: Como va la reforma energetica?\nR: Avanzamos en paneles solares...` |
| `""` (vacio) | `R: {intervention.text}` (solo la respuesta) |

**No incluye:** fecha, participante, `Contexto:`, `Conferencia del`, IDs tecnicos, hashes. Solo contenido semantico con dos etiquetas minimales que ayudan al modelo de embedding a distinguir pregunta de respuesta.

### Cambio en `enrich_interventions`

```python
# Antes (linea ~172-178)
payload = build_embedding_payload(intervention, effective_date)
embedding = embed_text(payload, ollama_base_url, ollama_model)

# Despues
payload = build_embedding_payload(intervention, effective_date)
embedding_text = build_embedding_text(intervention)
embedding = embed_text(embedding_text, ollama_base_url, ollama_model)
```

El INSERT a `gold.rag_corpus` no cambia. La columna `payload` recibe el texto con metadata (trazabilidad), la columna `embedding` recibe el vector generado desde el texto limpio.

### Columnas de Gold afectadas

| Columna | Antes | Despues |
|---------|-------|---------|
| `payload` | Texto con metadata | Igual (sin cambios) |
| `embedding` | Vector de texto con metadata | Vector de texto limpio |

## Impacto esperado

- **Relevancia**: se mantiene alta (el contenido semantico ya estaba en el texto original, solo se elimina ruido). Podria mejorar ligeramente.
- **Fidelidad**: mejora significativa. Al eliminar ruido del embedding, chunks semanticamente cercanos se agrupan mejor en el espacio vectorial. El LLM recibe fuentes mas precisas para la misma query.
- **Dimensionalidad**: los vectores siguen siendo 768-dim, pero las dimensiones ahora codifican solo contenido semantico, no metadata repetitiva.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `backend/src/lakehouse/pipeline/enrichment.py` | Nueva funcion `build_embedding_text`. Una linea cambiada en `enrich_interventions`. |
| `backend/tests/test_pipeline/test_enrichment.py` | Nueva clase `TestBuildEmbeddingText` con 3 tests. |

## Verificacion

1. `ruff check` + `ruff format` en archivos modificados
2. `ty check src/` sin errores
3. `pytest --cov=src --cov-fail-under=90` (257 tests, >=90% cobertura)
4. `make pipeline-enrich ARGS="--clean"` regenera Gold con embeddings limpios
5. `make evaluate-rag` mide fidelidad post-cambio (baseline: 34.18%)

## No incluido en este feature

- Cambios al modelo de embedding (`embeddinggemma` permanece)
- Cambios al formato del context builder (ya refactorizado en feature anterior)
- Limpieza del payload para el LLM (el text que ve el LLM ya es `chunk_text` + `pregunta_activa`, via context builder)
- Re-indexado automatico (se hara manualmente con `--clean`)
