# Tech Skill: Configuracion de Runtime GCP (Cloud Run + Neon + Gemini)

## Proposito

Gobernar la configuracion de ejecucion productiva: parametros de Cloud Run, conexion Neon (TLS +
pooling), modelos Gemini (generativo y embeddings) y la validacion del indice al arrancar. Separada
de `terraform_gcp.md` (IaC).

## Cuando usar

- Ajustar el entorno productivo (`APP_ENV=prod`), conexiones Neon, modelos Gemini o la validacion de indice.
- Implementar el adaptador Gemini o la reindexacion productiva.

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 11.2, 11.3, 20, 21).

## Archivos que gobierna

- `backend/src/lakehouse/config.py` (settings prod: gemini, neon, jwt)
- `backend/src/lakehouse/services/gemini_embedding.py`, `gemini_chat.py` (adaptadores, nuevos)
- `backend/src/lakehouse/db/pgvector_conn.py` (TLS/pooling Neon)
- `.env.template` / `.env.production.example`

## Invariantes

- Neon: conexion agrupada + TLS obligatorio. No exponer `DATABASE_URL` en logs.
- Generativo productivo: `gemini-3.5-flash-lite`. Embeddings: `gemini-embedding-001`, 768 dims, normalizacion, tareas `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`.
- Corpus local = EmbeddingGemma; corpus productivo = Gemini. JAMAS mezclar espacios vectoriales (ver `duckdb_pgvector.md`).
- Metadatos obligatorios de indice: proveedor+modelo, dimension, tipo de tarea, version de formato, fecha, hash del corpus.
- El servicio FALLA al iniciar si la config de consulta no coincide con los metadatos del indice (fallar cerrado).
- Cloud Run: 1 vCPU, concurrencia 10, `max-instances=1`, facturacion por solicitud; aviso visible de nivel gratuito Gemini (los datos pueden usarse para mejorar productos de Google; no introducir investigaciones confidenciales).

## Flujo de trabajo

1. Reindexacion TOTAL hacia Neon con Gemini embeddings (indice independiente y versionado).
2. Al arrancar, validar modelo/dimension/tarea contra metadatos; fallar cerrado si no coincide.
3. Servir web + API bajo el MISMO origen (build unico) para simplificar cookies y CORS.

## Verificaciones de aceptacion

- [ ] Produccion rechaza iniciar si modelo/dimension/tarea no coincide con el indice Neon (CA-R05).
- [ ] Embeddings locales y productivos fisicamente separados (CA-R06).
- [ ] Neon exige TLS y usa conexion agrupada (CA-D07).
- [ ] Servicio escala a cero con maximo de instancias configurado (CA-D08).
