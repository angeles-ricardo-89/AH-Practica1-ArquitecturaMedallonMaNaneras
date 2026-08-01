# Clean Embedding Payload Implementacion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar el texto usado para embedding (semantico limpio) del texto guardado en `payload` (metadata completa) en Gold.

**Architecture:** Nueva funcion `build_embedding_text` genera texto `P: pregunta\nR: respuesta` sin metadata. `build_embedding_payload` sigue igual para la columna `payload`. `enrich_interventions` llama a ambas.

**Tech Stack:** Python 3.13, Pydantic, psycopg, Ollama (embeddinggemma)

---

### File Structure

| Archivo | Accion | Responsabilidad |
|---------|--------|-----------------|
| `backend/src/lakehouse/pipeline/enrichment.py` | Modify | + `build_embedding_text`, +1 linea en `enrich_interventions` |
| `backend/tests/test_pipeline/test_enrichment.py` | Modify | + `TestBuildEmbeddingText` con 3 tests |

---

### Task 1: Test `build_embedding_text` — con pregunta_activa

**Files:**
- Modify: `backend/tests/test_pipeline/test_enrichment.py` (append al final)

- [ ] **Step 1: Agregar la clase de tests**

Agrega al final de `backend/tests/test_pipeline/test_enrichment.py`:

```python
class TestBuildEmbeddingText:
    def test_build_embedding_text_with_pregunta(self) -> None:
        from lakehouse.pipeline.enrichment import build_embedding_text

        intervention = InterventionRecord(
            intervention_key="k1",
            conference_id="c1",
            participant="PRESIDENTA",
            text="Avanzamos en paneles solares en Sonora.",
            pregunta_activa="Como va la reforma energetica?",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert result == "P: Como va la reforma energetica?\nR: Avanzamos en paneles solares en Sonora."
        assert "Conferencia" not in result
        assert "Participante" not in result
        assert "Contexto" not in result
        assert intervention.participant not in result

    def test_build_embedding_text_without_pregunta(self) -> None:
        from lakehouse.pipeline.enrichment import build_embedding_text

        intervention = InterventionRecord(
            intervention_key="k2",
            conference_id="c2",
            participant="SECRETARIO",
            text="Se implemento la estrategia nacional de seguridad.",
            pregunta_activa="",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert result == "R: Se implemento la estrategia nacional de seguridad."
        assert "P:" not in result
        assert "Conferencia" not in result

    def test_build_embedding_text_no_ids_no_hashes(self) -> None:
        from lakehouse.pipeline.enrichment import build_embedding_text

        intervention = InterventionRecord(
            intervention_key="k3_abc123",
            conference_id="conf_xyz",
            participant="PRESIDENTA",
            text="Contenido de prueba.",
            pregunta_activa="Pregunta?",
            chunk_index=0,
            url="https://example.com",
        )
        result = build_embedding_text(intervention)
        assert intervention.intervention_key not in result
        assert intervention.conference_id not in result
        assert str(intervention.chunk_index) not in result
```

- [ ] **Step 2: Verificar que el test falla**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestBuildEmbeddingText -v
```

Expected: FAIL. `ImportError: cannot import name 'build_embedding_text'` o `AttributeError`.

- [ ] **Step 3: Implementar `build_embedding_text`**

En `backend/src/lakehouse/pipeline/enrichment.py`, agrega despues de `build_embedding_payload` (line ~31):

```python
def build_embedding_text(intervention: InterventionRecord) -> str:
    pregunta = intervention.pregunta_activa
    if pregunta:
        return f"P: {pregunta}\nR: {intervention.text}"
    return f"R: {intervention.text}"
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py::TestBuildEmbeddingText -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py backend/tests/test_pipeline/test_enrichment.py
git commit -m "feat: build_embedding_text genera texto semantico limpio sin metadata"
```

---

### Task 2: Cambiar enrich_interventions para usar build_embedding_text

**Files:**
- Modify: `backend/src/lakehouse/pipeline/enrichment.py:176-178`

- [ ] **Step 1: Cambiar la linea en enrich_interventions**

En `backend/src/lakehouse/pipeline/enrichment.py` linea 176-178, cambia:

```python
            payload = build_embedding_payload(intervention, effective_date)
            try:
                embedding = embed_text(payload, ollama_base_url, ollama_model)
```

Por:

```python
            payload = build_embedding_payload(intervention, effective_date)
            embedding_text = build_embedding_text(intervention)
            try:
                embedding = embed_text(embedding_text, ollama_base_url, ollama_model)
```

- [ ] **Step 2: Correr tests completos del modulo enrichment**

```bash
cd backend && uv run pytest tests/test_pipeline/test_enrichment.py -v
```

Expected: todos los tests de `TestEnrichInterventions` y `TestBuildEmbeddingText` pasan. Los tests de `enrich_interventions` mockean `embed_text` y no inspeccionan su argumento, por lo que no deberian romperse.

- [ ] **Step 3: Commit**

```bash
git add backend/src/lakehouse/pipeline/enrichment.py
git commit -m "feat: enrich usa build_embedding_text para embedding limpio"
```

---

### Task 3: Verificacion completa

- [ ] **Step 1: Ruff + ty + test suite completa**

```bash
cd backend && uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/
cd backend && uv tool run ty check src/
cd backend && uv run pytest -q --cov=src --cov-report=term-missing
```

Expected:
- ruff: All checks passed
- ty: All checks passed
- pytest: 260 passed, >=90% coverage

- [ ] **Step 2: Commit de verificacion**

```bash
git add -A
git commit -m "chore: verificacion post feature payload de embedding limpio"
```
