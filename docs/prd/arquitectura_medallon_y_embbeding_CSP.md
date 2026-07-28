# PRD 2.0 — Lakehouse Local de Conferencias Matutinas de la Presidenta de México

## 1. Resumen Ejecutivo
Este producto es un data lakehouse local operado vía Docker Compose para ingerir, versionar, estructurar y consultar las versiones estenográficas de las conferencias matutinas presidenciales (gob.mx). 

El MVP demuestra una arquitectura medallón robusta —Bronze, Silver y Gold— con ingesta idempotente, parsing determinista, enriquecimiento asíncrono, y un dashboard web (Vue+FastAPI) con chat RAG. Se utilizan motores duales locales: Ollama para vectorización de textos y `llamacpp` (Gemma 4) para inferencia conversacional y evaluación automatizada (LLM-as-a-Judge).

---

## 2. Stack Tecnológico Actualizado
*   **Backend & Orquestación:** Python, FastAPI, CLI (Cron).
*   **Frontend:** Vue.js 3, Pinia, TailwindCSS, TypeScript, Vite.
*   **Lakehouse & Motor Analítico:** DuckLake, DuckDB.
*   **Catálogo & Vector Store:** PostgreSQL + pgvector.
*   **Motor de Embeddings (Puerto 11434):** Ollama (Evaluación: `nomic-embed-text`, `qwen3-embedding`, `embeddinggemma`, `nomic-embed-text-v2-moe`).
*   **Motor Generativo (Puerto 9200):** `llamacpp` ejecutando `gemma4` (API compatible con OpenAI).
*   **Infraestructura:** Docker Compose (Entorno Local).

---

## 3. Arquitectura Medallón (Reglas Clave)

### 3.1 Capa Bronze (Ingesta Inmune al Ruido)
*   **Propósito:** Almacenar el HTML original descargado garantizando reproducibilidad.
*   **Versionado:** Para evitar re-ingestas por cambios dinámicos del sitio web (timestamps, contadores), el `content_hash` **solo** se calculará sobre un segmento limpio del DOM (ej. `<main>` o `<div class="article-body">`), ignorando headers y footers.
*   **Idempotencia:** Append-only. Agrupado por `ingestion_run_id`.

### 3.2 Capa Silver (Rápida y Determinista)
*   **Propósito:** Convertir HTML a registros Pydantic estandarizados (`ConferenceRecord`, `InterventionRecord`).
*   **Parsing:** Estrictamente basado en selectores HTML y expresiones regulares sobre etiquetas `<strong>`. Cero uso de LLMs en esta capa para garantizar procesamiento en minutos.
*   **Cuarentena (DLQ):** Intervenciones sin formato legible van a una tabla de cuarentena.
*   **Heurística de Contexto (Estado):** El script mantendrá una variable `pregunta_activa` que se actualiza al detectar `<strong>PREGUNTA:</strong>`. Este texto se inyectará como metadato en los chunks posteriores de la respuesta para no perder el contexto en el RAG.
*   **Claves Naturales:** Cero IDs aleatorios (Snowflake). Uso estricto de hashes concatenados (ej. `chunk_key = parent_key + chunk_index + text_hash`) para permitir el `MERGE INTO` de DuckLake.

### 3.3 Capa Gold (Semántica y Enriquecida)
*   **Propósito:** Modelos analíticos, extracción LLM asíncrona y RAG Corpus.
*   **Extracción de Entidades:** Aquí es donde el LLM (`gemma4`) procesará de forma asíncrona quién es el periodista y de qué medio viene, actualizando los registros Silver.
*   **Payload Vectorial:** El texto inyectado a Ollama será puro y denso, sin basura técnica.
    
    **Formato exacto esperado:**
    > Contexto: Conferencia del [Fecha]
    > Participante: [Nombre]
    > Pregunta activa: [Texto de la pregunta]
    > Respuesta: [Texto del chunk limpio]

---

## 4. Estrategia de Búsqueda RAG (FastAPI + pgvector)
El backend utilizará una **Estrategia Híbrida Dinámica**:
1.  Tablas Gold indexadas con `B-Tree` (para fecha/participante) y `HNSW` (para el vector).
2.  Si el usuario aplica filtros estrictos en la UI, FastAPI ejecutará un filtrado relacional primero y distancia matemática secuencial sobre el subconjunto.
3.  Si la consulta es libre, se apoyará 100% en la velocidad del índice HNSW.

---

## 5. UI y Experiencia de Usuario (Vue + Pinia)
*   **Dashboard de Observabilidad:** La UI mostrará semáforos del estado del cronjob y un visor de los últimos logs (`/data/logs/pipeline/cron.log`) traídos mediante un endpoint HTTP.
*   **Control de Memoria RAG:** El chat no mostrará consumo de RAM. Pinia gestionará y graficará una barra de **Límite de Tokens (Ventana de Contexto)** utilizando un estimador local. Si llega al 90%, se alertará al usuario que el contexto más antiguo será descartado.
*   **Trazabilidad:** Cada respuesta del chat incluirá tarjetas clickeables con la evidencia exacta recuperada.

---

## 6. Criterios de Aceptación

*   **CA-01 — Bronze:** El sistema debe guardar al menos dos lotes Bronze intactos con timestamp tras dos ejecuciones.
*   **CA-02 — Silver:** El sistema debe validar registros contra Pydantic y separar válidos e inválidos con motivo de rechazo.
*   **CA-03 — Idempotencia DuckLake:** Dado el mismo lote reprocesado dos veces, la segunda ejecución de `MERGE` debe arrojar `filas_nuevas = 0` y `duplicados = 0`.
*   **CA-04 — Gold vectorial:** El sistema debe generar embeddings del campo relevante (payload denso) y almacenarlos en pgvector.
*   **CA-05 — Búsqueda semántica:** Dada una consulta de prueba, el sistema debe devolver resultados semánticamente relacionados con fecha, participante, fragmento y URL.
*   **CA-06 — RAG útil validado (LLM-as-a-Judge):** Al ejecutar el comando `python -m lakehouse evaluate-rag`, el script procesará un "Golden Dataset" local de 50 preguntas predefinidas. El evaluador (`gemma4`) considerará el RAG exitoso si alcanza:
    *   Fidelidad (Cero alucinaciones): **≥ 90%**
    *   Relevancia de Respuesta: **≥ 80%**
*   **CA-07 — Clasificación estable:** La variación de etiquetas principales entre ejecuciones sobre el mismo lote debe ser menor o igual a 5%.
*   **CA-08 — Tiempo de Reconstrucción:** Una reconstrucción total desde Bronze a Gold (sin los procesos asíncronos pesados del LLM) para 3 meses de datos debe completarse en **≤ 15 minutos**.
*   **CA-09 — Observabilidad:** El dashboard Vue debe mostrar un semáforo de estado de ingesta y permitir leer los últimos logs sin acceso SSH.

---

## 7. Variables de Entorno y Configuración

```env
APP_ENV=local
SOURCE_ARCHIVE_URL=[https://www.gob.mx/presidencia/es/archivo/articulos](https://www.gob.mx/presidencia/es/archivo/articulos)

# Lakehouse & Postgres
POSTGRES_HOST=postgres
POSTGRES_DB=mananeras
DUCKLAKE_CATALOG=postgres
DUCKLAKE_DATA_PATH=/data/lakehouse/ducklake_files.duckdb

# Motores Duales
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=nomic-embed-text

LLAMACPP_BASE_URL=http://localhost:9200/v1
LLAMACPP_MODEL=gemma4

# RAG & UI
RAG_TOP_K=8
MAX_CONTEXT_TOKENS=8192
```

## 8. Definición de Terminado (DoD)
El Sprint 1 se considerará cerrado cuando:

1. Se pueda hacer un docker compose up -d exitoso.
2. Los datos fluyan hasta Gold de manera idempotente usando DuckLake sin generar duplicados.
3. FastAPI sirva los chunks de evidencia y el frontend en Vue mantenga una conversación trazable vigilando el límite de tokens.
4. El script de evaluación automatizada (evaluate-rag.py) demuestre un 90% de fidelidad usando el modelo juez.

