# Especificación de diseño — Verificación del parser temporal contra Gemini (producción/GCP)

**Fecha:** 2026-09-07
**Fuente:** petición directa del operador (dueño de la demo)
**Estado:** Especificación en revisión (spec-review-loop)
**Alcance:** diseño, no implementación

---

## 1. Problema

El parser temporal (`services/temporal_parser.py`) resuelve consultas con intención de tiempo
(relativas y absolutas) y alimenta la búsqueda híbrida (filtro `BETWEEN` + pgvector). El flujo fue
corregido recientemente en local (timezone + `max_tokens` del modelo razonador), pero **no existe
ninguna forma de verificar que ese mismo flujo funciona con Gemini en producción**: en producción el
parser y la búsqueda despachan a Gemini (`gemini-3.5-flash-lite` para chat, `gemini-embedding-001`
para embeddings) y consultan Neon, y su comportamiento (formato de fechas, mapeo de roles, mime
JSON, referencia de "ahora") puede diferir del de llama.cpp/Ollama.

**Objetivo:** entregar un comando de verificación *durable* que ejecute las mismas consultas de
tiempo contra el stack productivo (Gemini + Neon) y reporte si las fechas parseadas coinciden con
las esperadas, más un test de integración que proteja el wiring parser→Gemini en CI.

---

## 2. Estado actual comprobado (verificado contra el código)

### 2.1 Despacho de proveedor

- `services/agent/llm.py::chat_json`/`chat_text` despachan a Gemini en producción
  (`_dispatch` → `GeminiChatAdapter.generate`) y a llama.cpp en local (`_post`).
- `GeminiChatAdapter` (`services/gemini_chat.py`) mapea el `system` prompt a `system_instruction`
  y los roles a `user`/`model`; soporta `response_mime_type="application/json"`.
- `services/rag_search.py::embed_search_query` despacha a `GeminiEmbeddingAdapter` en producción.

### 2.2 Parser temporal

- `TemporalParser.extraer(query)` usa `chat_json` (Gemini en producción) y valida con
  `TimeFilterOut` (formato `YYYY-MM-DD HH:MM:SS`, coherencia inicio<=fin).
- Tras el fix reciente, `_build_system_prompt(tz_name, now=None)` resuelve "ahora" con
  `ZoneInfo(settings.app_timezone)` (default `America/Mexico_City`), corregido desde el UTC del
  contenedor que desfasaba las fechas relativas un día.

### 2.3 Búsqueda híbrida

- `search_with_date_filter(query_vector, top_k, fecha_inicio, fecha_fin, settings)` aplica
  `conference_date BETWEEN %s::date AND %s::date` + `ORDER BY embedding <=> %s::vector` sobre
  `gold.rag_corpus`.
- En producción `get_database_url(settings)` exige `neon_database_url` (endpoint `-pooler` + TLS).

### 2.4 Configuración productiva

- `.env.production.example` define `GEMINI_API_KEY`, `NEON_DATABASE_URL`,
  `GEMINI_EMBEDDING_MODEL`, `GEMINI_CHAT_MODEL`, `GEMINI_EMBEDDING_DIMENSION`, `INDEX_FORMAT_VERSION`.
- Los secretos reales viven en Secret Manager y se inyectan como env vars en Cloud Run
  (`infra/terraform/main.tf`).

### 2.5 Patrón CLI existente

- `cli.py` expone comandos top-level como `evaluate_rag` (`@app.command()`) que delegan en un
  servicio y reportan resumen con `typer.echo` + `typer.Exit`.

---

## 3. Alcance y no alcance

### 3.1 Alcance (se construye en esta fase)

1. Servicio `services/temporal_verification.py` con casos de prueba tabulados y la lógica de
   verificación (parser + búsqueda contra Gemini/Neon + comparación de fechas esperadas).
2. Comando Typer top-level `verify-temporal-gemini` en `cli.py`, fail-closed sin secretos.
3. Test de integración `tests/test_services/test_temporal_parser_gemini.py` que mockea solo la
   frontera HTTP de Gemini (`google.genai.Client`).
4. Documentación del comando en `AGENTS.md` (tabla de comandos).

### 3.2 No alcance

- No se modifica el comportamiento del parser ni de la búsqueda (solo se verifica).
- No se automatiza la ejecución en Cloud Run (el operador la corre manualmente cuando lo requiera).
- No se verifica el turno agéntico completo (planner/synthesizer), solo el filtro temporal.
- No se alteran las credenciales ni la infraestructura Terraform.

---

## 4. Diseño

### 4.1 Casos de prueba (las mismas consultas verificadas en local)

Tabla fija de casos con tipo y esperados:

| # | Query | Tipo | Esperado |
|---|-------|------|----------|
| 1 | `Que dijo Sheinbaum el 15 de julio de 2025?` | absoluta | inicio=fin=`2025-07-15` |
| 2 | `Que paso ayer?` | relativa | inicio=fin=`hoy - 1 día` (México) |
| 3 | `Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?` | relativa | inicio=fin=`último lunes` (México) |
| 4 | `Que paso la ultima semana?` | relativa | inicio=`último lunes`, fin=`hoy` |
| 5 | `Cual es la postura sobre energia nuclear?` | sin_intento | `requiere_filtro_tiempo=false` |

Las fechas relativas esperadas se calculan en runtime con `ZoneInfo(settings.app_timezone)`,
replicando la semántica del prompt (mismo cálculo que `_build_system_prompt`).

### 4.2 Servicio `services/temporal_verification.py`

Estructuras pydantic:

- `TemporalTestCase`: `query: str`, `tipo: Literal["absoluta", "relativa", "sin_intento"]`,
  `esperado_inicio: str | None`, `esperado_fin: str | None`, `semilla_relativa: str | None`
  (indicador `ayer`/`lunes_pasado`/`ultima_semana` para calcular el esperado).
- `TemporalCaseResult`: `query`, `tipo`, `requiere_filtro`, `obtenido_inicio`, `obtenido_fin`,
  `esperado_inicio`, `esperado_fin`, `ok`, `fallback_ocurrido`, `source_count`, `fuentes`
  (lista de `conference_date`).
- `VerifyResult`: `total`, `pasaron`, `casos: list[TemporalCaseResult]`.

Función `verify_temporal_gemini(settings: Settings) -> VerifyResult`:

1. Para cada caso:
   - `parser_result = TemporalParser(settings).extraer(query)`.
   - Si `requiere_filtro_tiempo`: `vec = embed_search_query(settings, texto_semantico)`;
     `results = search_with_date_filter(vec, top_k, inicio, fin, settings)`.
   - Si no: `vec = embed_search_query(settings, texto_semantico)`;
     `results = search_gold_corpus_from_vector(vec, top_k, settings)`.
   - Compara `fecha_inicio`/`fecha_fin` contra los esperados (para `sin_intento`, `ok` si
     `requiere_filtro_tiempo is False`).
2. Acumula resultados y devuelve el resumen.

Función auxiliar `_esperados_relativos(tz_name, semilla) -> tuple[str, str]` que, dado "ahora" en
México, devuelve `(inicio, fin)` formateados `YYYY-MM-DD HH:MM:SS`.

### 4.3 Comando `verify-temporal-gemini` (`cli.py`)

```python
@app.command()
def verify_temporal_gemini() -> None:
    settings = Settings()
    if not settings.gemini_api_key:
        raise typer.BadParameter("GEMINI_API_KEY es obligatorio (Secret Manager/env)")
    if not settings.neon_database_url:
        raise typer.BadParameter("NEON_DATABASE_URL es obligatorio (Secret Manager/env)")
    result = verify_temporal_gemini_fn(settings)
    # imprime tabla por caso + resumen
    raise typer.Exit(code=0 if result.pasaron == result.total else 1)
```

- Imprime por caso: `query`, esperado vs obtenido, `PASS`/`FAIL`, `fuentes=N`, top fechas.
- Resumen final: `X/Y pasaron`.
- Exit code 1 si algún caso falla (útil como gate manual).

### 4.4 Test de integración `tests/test_services/test_temporal_parser_gemini.py`

Mockea solo `google.genai.Client` (frontera externa), patrón de `test_gemini_adapters.py`:

- `TemporalParser.extraer` con `app_env="production"` + `gemini_api_key` set → usa Gemini:
  - el system prompt llega como `config.system_instruction`;
  - `config.response_mime_type == "application/json"`;
  - `config.temperature` y `max_output_tokens` propagados desde settings.
- Parseo correcto de una fecha absoluta devuelta por Gemini.
- `_esperados_relativos("America/Mexico_City", "ayer"|"lunes_pasado"|"ultima_semana")` calcula las
  fechas correctas para un "ahora" conocido (se inyecta el reloj si hace falta).

---

## 5. Manejo de errores y casos borde

| Caso | Comportamiento |
|---|---|
| Sin `GEMINI_API_KEY` | `typer.BadParameter`, exit code != 0 |
| Sin `NEON_DATABASE_URL` | `typer.BadParameter`, exit code != 0 |
| Gemini devuelve JSON inválido/truncado | `TemporalParser` reintenta y cae a fallback; el caso marca `fallback_ocurrido=True` y `ok=False` |
| Gemini interpreta mal "ahora" (timezone) | la comparación contra el esperado en México detecta el desfase → `ok=False` |
| Neon sin datos en el rango | `source_count=0`; el caso evalúa solo el parseo de fechas (no el número de fuentes) |
| Búsqueda falla (DB) | `search_with_date_filter` lanza `RuntimeError`; el comando captura y marca el caso como fallido sin abortar la verificación completa |

El criterio de `ok` se basa **solo en las fechas parseadas** (inicio/fin), no en el número de
fuentes, porque la cobertura de datos puede variar (p. ej. fines de semana sin conferencias).

---

## 6. Testing (Gate Q / Gate I)

Mocks **solo** en la frontera HTTP de Gemini (servicio externo), nunca de servicios internos.

### 6.1 Unitarios `tests/test_services/test_temporal_verification.py`

- `_esperados_relativos` produce las fechas correctas para `ayer`, `lunes_pasado` y `ultima_semana`
  en `America/Mexico_City` con un "ahora" conocido (inyectando el reloj).
- La tabla de casos tiene exactamente los 5 casos con tipos correctos.

### 6.2 Integración `tests/test_services/test_temporal_parser_gemini.py`

- Parser→Gemini wiring (system instruction, mime JSON, params) como en §4.4.
- `verify_temporal_gemini` con Gemini y Neon mockeados en su frontera devuelve `pasaron == total`
  cuando los esperados coinciden, y `ok=False` cuando Gemini devuelve una fecha errónea.

### 6.3 Config

- `app_timezone` y `temporal_parser_max_tokens` ya cubiertos por `test_config.py` (fix previo).

---

## 7. Seguridad

- **Secreto:** `GEMINI_API_KEY` y `NEON_DATABASE_URL` se leen de env (Secret Manager en Cloud Run);
  jamás se loggean ni se imprimen (el comando solo reporta host del endpoint y conteos).
- **Sin cambios de red/ingreso:** el comando es una verificación outbound HTTPS; no añade endpoints,
  permisos IAM ni tráfico de entrada.
- **Escáner de secretos:** no se introducen literales de credenciales; `scripts/scan_secrets.py`
  debe seguir pasando.

---

## 8. Criterios de aceptación

1. `python -m lakehouse verify-temporal-gemini` falla cerrado (mensaje claro) sin
   `GEMINI_API_KEY`/`NEON_DATABASE_URL`, y con credenciales ejecuta los 5 casos y reporta
   esperado vs obtenido + resumen.
2. El test de integración verifica el wiring parser→Gemini (system instruction + mime JSON) y corre
   en la suite normal sin red real.
3. Las fechas relativas esperadas se calculan en `America/Mexico_City` (no UTC).
4. `make test-backend`, `ruff`, `ty` verdes; cobertura >= 90%.
5. `AGENTS.md` documenta el nuevo comando.
