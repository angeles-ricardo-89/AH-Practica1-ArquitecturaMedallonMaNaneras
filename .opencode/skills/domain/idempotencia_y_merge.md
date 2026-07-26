# Domain Skill: Idempotencia y Merge

## Proposito

Garantizar que todas las operaciones de escritura en el Lakehouse sean idempotentes mediante
claves naturales deterministas basadas en hashes concatenados. Prohibido el uso de IDs aleatorios
(UUID4, Snowflake, SERIAL para claves de negocio).

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| DuckDB + pgvector | `../tech/duckdb_pgvector.md` | `MERGE INTO` para upserts idempotentes; `chunk_key` como clave natural en pgvector |

## Reglas de Claves Naturales

### Formato Estricto

Toda clave natural se genera concatenando los campos que definen la unicidad del registro,
separados por `|`, y aplicando SHA-256 sobre el resultado.

```
chunk_key = SHA256(f"{conference_date}|{participant}|{chunk_index}|{text[:200]}")
```

### Componentes de Clave por Capa

**Bronze (HTML crudo):**
```
content_hash = SHA256(texto_extraido_del_DOM_relevante)
```
El dominio relevante del DOM se define como `<main>` o el selector que contenga el cuerpo del articulo,
excluyendo headers, footers y sidebars con timestamps dinamicos.

**Silver (Chunks parseados):**
```
chunk_key = SHA256(f"{conference_date}|{participant}|{chunk_index}|{text_limpio[:200]}")
```

**Gold (RAG Corpus):**
```
corpus_key = chunk_key  # misma clave que Silver, el chunk no cambia
```

### Algoritmo MERGE INTO

```python
# Pseudocodigo del patreon idempotente
# 1. Crear tabla temporal con nuevos registros
# 2. MERGE INTO target USING temp ON clave natural
# 3. WHEN NOT MATCHED INSERT
# 4. (Opcional) WHEN MATCHED UPDATE solo metadatos (ej. updated_at)
# 5. Verificar: filas_nuevas > 0 o duplicados = 0

def merge_idempotente(
    conn: duckdb.DuckDBPyConnection,
    target_table: str,
    new_records: list[dict],
    natural_key: str,
) -> MergeResult:
    # Implementacion concreta en ../tech/duckdb_pgvector.md
    ...
```

## Reglas de Verificacion

### Rechazo Automatico (DLQ)

Los registros que no cumplan el formato esperado van a la tabla de cuarentena `dlq.silver_rejects`:
- Chunks con texto vacio despues de limpieza.
- Chunks sin participant detectado.
- Chunks sin pregunta_activa cuando deberian tenerla.

### Test de Idempotencia (Criterio de Aceptacion CA-03)

Dado el mismo lote reprocesado dos veces:
1. Primera ejecucion: `filas_nuevas = N`, `duplicados = 0`
2. Segunda ejecucion: `filas_nuevas = 0`, `duplicados = N`

Si esto no se cumple, el Gate Q bloquea el avance.

## Snippet de Verificacion

```python
from __future__ import annotations


def test_merge_idempotencia() -> None:
    resultado_1 = ejecutar_merge(lote_prueba)
    assert resultado_1.nuevas > 0
    assert resultado_1.duplicados == 0

    resultado_2 = ejecutar_merge(lote_prueba)  # mismo lote
    assert resultado_2.nuevas == 0
    assert resultado_2.duplicados == resultado_1.nuevas
```

## Checklist de Verificacion

- [ ] Ningun registro usa UUID4, Snowflake, SERIAL como clave de negocio.
- [ ] content_hash en Bronze se calcula SOLO sobre el DOM relevante (no HTML completo).
- [ ] chunk_key en Silver es determinista: mismo texto produce misma clave siempre.
- [ ] MERGE INTO re-ejecutado con mismo lote produce filas_nuevas=0.
- [ ] DLQ captura registros invalidos con motivo de rechazo.
- [ ] `MERGE` maneja commits explicitos (no autocommit).
