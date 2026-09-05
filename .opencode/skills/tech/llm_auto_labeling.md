# Skill: LLM Auto-Labeling
**Domain**: Semantic cluster labeling using local LLM (llamacpp/gemma-4-12b).
**Tech**: httpx, llamacpp OpenAI-compatible API, text templates.

## Overview
Use this skill when implementing auto-labeling of text clusters with a local LLM. The LLM generates short descriptive labels (max 4 words) for groups of semantically similar text chunks.

## Key Architecture Rule

Prompt template lives in a versioned file (`backend/src/lakehouse/prompts/cluster_label_v1.txt`). Never embed the prompt as a string constant in Python code.

## Implementation Patterns

### 1. Load prompt from file

```python
from pathlib import Path

def load_prompt_template(version: str = "v1") -> str:
    prompt_path = Path(__file__).parent.parent / "prompts" / f"cluster_label_{version}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
```

### 2. Select representative chunks for a cluster

```python
def select_representative_chunks(
    chunks: list[dict],
    cluster_id: int,
    k: int = 5,
) -> list[dict]:
    """Select top-k chunks by membership strength, tiebreak by chunk_key ASC."""
    cluster_chunks = [
        c for c in chunks
        if c["cluster_id"] == cluster_id and cluster_id >= 0
    ]
    cluster_chunks.sort(key=lambda c: (-c["cluster_pertenencia"], c["chunk_key"]))
    return cluster_chunks[:k]
```

### 3. Format prompt with sampled chunks

```python
def format_labeling_prompt(prompt_template: str, chunks: list[dict], max_chars: int = 1500) -> str:
    texts = []
    for chunk in chunks:
        text = chunk["chunk_text"][:max_chars]
        texts.append(f"- {text}")
    return prompt_template.replace("{textos_formateados}", "\n".join(texts))
```

### 4. Call llamacpp for label generation

```python
import httpx

def generate_label(
    prompt: str,
    base_url: str,
    model: str,
    max_retries: int = 2,
    temperature: float = 0,
    max_tokens: int = 20,
) -> str:
    """Call llamacpp and return the raw label response."""
    for attempt in range(max_retries):
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            raw = data["choices"][0]["message"]["content"].strip()
            if raw:
                return raw
            raise ValueError("empty_response")
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            continue
    raise RuntimeError("max_retries_exhausted")
```

### 5. Validate and normalize label

```python
import re

def validate_label(raw_label: str) -> tuple[str | None, str | None]:
    """Validate and normalize a raw label. Returns (normalized_label, error)."""
    if not raw_label or not raw_label.strip():
        return None, "empty"

    # Normalize
    label = raw_label.strip()
    label = re.sub(r"\s+", " ", label)          # Collapse whitespace
    label = label.strip('"').strip("'")          # Strip wrapping quotes
    label = label.rstrip(".")                    # Strip trailing period

    # Strip common prefixes
    for prefix in ["etiqueta:", "tema:", "categoria:", "respuesta:", "label:", "category:", "topic:"]:
        if label.lower().startswith(prefix):
            label = label[len(prefix):].strip()

    if not label:
        return None, "empty_after_normalize"

    # Check line count
    lines = [l for l in label.split("\n") if l.strip()]
    if len(lines) > 1:
        return None, "multiline"

    # Check word count (max 4)
    words = label.split()
    if len(words) > 4:
        return None, "too_many_words"

    return label, None
```

### 6. Full label generation loop with persistence

```python
def label_clusters(
    conn,
    run_id: str,
    cluster_ids: list[int],
    chunks: list[dict],
    base_url: str,
    model: str,
    prompt_version: str = "v1",
    max_retries: int = 2,
    max_chars: int = 1500,
    k: int = 5,
) -> tuple[int, int]:
    """Label all clusters. Returns (completed_count, failed_count)."""
    prompt_template = load_prompt_template(prompt_version)
    completed, failed = 0, 0

    for cid in cluster_ids:
        if cid < 0:
            continue
        samples = select_representative_chunks(chunks, cid, k=k)
        prompt = format_labeling_prompt(prompt_template, samples, max_chars=max_chars)

        label = None
        error = None
        for attempt in range(max_retries + 1):
            try:
                raw = generate_label(prompt, base_url, model, max_retries=1)
                label, error = validate_label(raw)
                if label:
                    break
            except Exception as e:
                error = str(e)

        cur = conn.cursor()
        if label:
            cur.execute("""
                INSERT INTO gold.cluster_labels
                    (clustering_run_id, cluster_id, cluster_label, label_status,
                     sample_size, sample_chunk_keys, model_name, prompt_version,
                     attempt_count)
                VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s, %s)
                ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                SET cluster_label = EXCLUDED.cluster_label,
                    label_status = 'completed',
                    sample_size = EXCLUDED.sample_size,
                    sample_chunk_keys = EXCLUDED.sample_chunk_keys,
                    attempt_count = EXCLUDED.attempt_count,
                    updated_at = NOW()
            """, (run_id, cid, label, len(samples), [c["chunk_key"] for c in samples],
                  model, prompt_version, attempt + 1))
            completed += 1
        else:
            cur.execute("""
                INSERT INTO gold.cluster_labels
                    (clustering_run_id, cluster_id, label_status, error_message,
                     sample_size, sample_chunk_keys, model_name, prompt_version,
                     attempt_count)
                VALUES (%s, %s, 'failed', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (clustering_run_id, cluster_id) DO UPDATE
                SET label_status = 'failed',
                    error_message = EXCLUDED.error_message,
                    attempt_count = EXCLUDED.attempt_count,
                    updated_at = NOW()
            """, (run_id, cid, error, len(samples), [c["chunk_key"] for c in samples],
                  model, prompt_version, attempt + 1))
            failed += 1

        conn.commit()

    return completed, failed
```

## Anti-Patterns

- **Don't embed prompt as string constant** — use versioned file.
- **Don't call LLM for noise clusters (cluster_id = -1)** — skip them.
- **Don't fail entire labeling on one cluster failure** — isolate errors per cluster.
- **Don't modify persisted chunk text** — truncation only applies to the copy sent to LLM.
- **Don't use high temperature** — must be `temperature=0` for deterministic labels.
- **Don't retry endlessly** — respect `max_retries` and mark as `failed`.
- **Don't translate or rephrase the LLM output** — only validate and normalize whitespace/punctuation.

## Prompt Template Format

File: `backend/src/lakehouse/prompts/cluster_label_v1.txt`

```
[INSTRUCCION DE SISTEMA / CONTEXTO]
Eres un sistema experto en analisis de datos y taxonomias. Tu unica tarea es asignar una categoria o etiqueta conceptual a un grupo de textos.

[REGLAS ESTRICTAS]
1. La etiqueta debe ser una frase o titulo muy corto, con un maximo de 4 palabras.
2. Debe describir el denominador comun o tema central de todos los ejemplos provistos.
3. Responde UNICAMENTE con la etiqueta del tema.
4. Prohibido incluir introducciones, explicaciones, saludos, notas aclaratorias o comillas en tu respuesta.

[EJEMPLOS DE TEXTO DEL GRUPO DE DATOS]
{textos_formateados}

[RESPUESTA]
```
