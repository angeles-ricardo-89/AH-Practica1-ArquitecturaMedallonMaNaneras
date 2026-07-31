# Evaluador de Practica: Arquitectura Medallon

Evalua automaticamente una implementacion de arquitectura medallon (Bronze -> Silver -> Gold)
para el diplomado de Inteligencia Artificial.

## Que evalua

- **Bronze (20 pts)**: Fuente publica, lotes, integridad, timestamps
- **Silver (25 pts)**: Contratos Pydantic, validacion, DLQ, conciliacion
- **Carga Idempotente (30 pts)**: Staging, claves naturales, MERGE, reprocesamiento, duplicados
- **Gold (25 pts)**: Preparacion textual, embeddings, indice vectorial, busqueda semantica

## Ejecucion

```bash
make evaluacion
```

O directamente:

```bash
cd backend && PYTHONPATH=src:../evaluacion/src uv run python -m evaluador.main
```

## Dependencias

- Python 3.13
- uv (gestor de paquetes)
- El mismo entorno virtual del backend (las dependencias se resuelven via `uv run`)

## Variables opcionales

Las siguientes variables de entorno del `.env` del proyecto afectan la evaluacion:

| Variable | Defecto | Efecto |
|----------|---------|--------|
| `SOURCE_ARCHIVE_URL` | https://www.gob.mx/presidencia/es/archivo/articulos | Fuente de datos para B1 |
| `DUCKLAKE_DATA_PATH` | (temporal en run dir) | Base de datos DuckDB aislada |

## Mecanismo de aislamiento

1. Cada ejecucion crea un directorio independiente `evaluacion/runs/<timestamp>/`
2. Se usa una base DuckDB temporal en ese directorio (`ducklake_files.duckdb`)
3. Las variables de entorno se sobrescriben para apuntar a la base temporal
4. El pipeline se ejecuta via subprocess con las variables de entorno modificadas
5. Los datos productivos no se ven afectados

## Estructura de evidencias

```
evaluacion/runs/<timestamp>/
├── reporte.html        # Reporte HTML navegable
├── resultado.json       # Resultados en JSON (legible por maquinas)
├── resumen.txt          # Resumen textual
├── logs/
│   └── evaluacion.log   # Log estructurado de la evaluacion
├── evidencias/          # Evidencias concretas (JSON, CSV, etc.)
│   ├── b1_source_response.json
│   ├── b2_lotes.json
│   ├── b3_hashes.json
│   ├── b4_timestamps.json
│   ├── s1_modelos_pydantic.json
│   ├── s2_registros_validos.json
│   ├── s3_dlq.json
│   ├── s4_rechazos.json
│   ├── s5_conciliacion.json
│   ├── i1_staging.json
│   ├── i2_claves_naturales.json
│   ├── i3_mecanismos_merge.json
│   ├── i4_reprocesamiento.json
│   ├── i5_duplicados.json
│   ├── g1_preparacion_textual.json
│   ├── g2_embeddings.json
│   ├── g3_indice_vectorial.json
│   ├── g4_busqueda_semantica.json
│   └── g5_busqueda_conceptual.json
└── comandos/
    └── ejecuciones.log  # Salida de comandos ejecutados
```

## Interpretacion de estados

| Estado | Significado | Puntos |
|--------|-------------|--------|
| CUMPLE | Evidencia ejecutable suficiente | 100% |
| PARCIAL | Parte del requisito demostrada | 50% |
| NO_CUMPLE | Evidencia de incumplimiento | 0% |
| INCONCLUSO | No se pudo evaluar por limitacion externa | 0% (provisional) |

## Limitaciones conocidas

- Los criterios Gold (G2, G5) requieren Ollama en localhost:11434 y PostgreSQL con pgvector via Docker
- La evaluacion de B2 necesita conectividad con gob.mx
- Si no hay conectividad externa, B1 queda INCONCLUSO y los lotes pueden fallar
- El pipeline usa max_articles=2 para acelerar la evaluacion

## Scoring

La suma maxima es 100 puntos. No se otorgan puntos extra por estilo o sofisticacion.
