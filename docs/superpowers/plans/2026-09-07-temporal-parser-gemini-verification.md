# Verificación del parser temporal contra Gemini (producción/GCP) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un comando CLI `verify-temporal-gemini` y un test de integración que verifiquen que el `TemporalParser` (filtro temporal del RAG) extrae fechas correctas usando Gemini en producción, contra Neon.

**Architecture:** Nuevo servicio `services/temporal_verification.py` con una tabla de casos de prueba (absoluta, ayer, lunes pasado, última semana, sin intento) que ejecuta `TemporalParser` + búsqueda híbrida reutilizando `chat_json`/`embed_search_query`/`search_with_date_filter` (que ya despachan a Gemini/Neon en producción), compara fechas contra esperadas calculadas en `America/Mexico_City`, y se expone como comando Typer. Un test de integración mockea solo la frontera externa de Gemini (`google.genai.Client`).

**Tech Stack:** Python 3.13 (uv), Typer, Pydantic, `google.genai`, psycopg/pgvector.

---

## File Structure

- **Create:** `backend/src/lakehouse/services/temporal_verification.py` — casos de prueba, cálculo de fechas esperadas y orquestación parser+búsqueda.
- **Modify:** `backend/src/lakehouse/cli.py` — nuevo comando top-level `verify-temporal-gemini` (fail-closed).
- **Create:** `backend/tests/test_services/test_temporal_verification.py` — unit tests de helpers + orquestación (mocks de search/embed/parser).
- **Create:** `backend/tests/test_services/test_temporal_parser_gemini.py` — test de integración parser→Gemini (mock solo `google.genai.Client`).
- **Modify:** `backend/tests/test_cli.py` — tests del comando (fail-closed + éxito).
- **Modify:** `AGENTS.md` — documentar el comando en la tabla de comandos.

---

## Task 1: Servicio `temporal_verification.py`

**Files:**
- Create: `backend/src/lakehouse/services/temporal_verification.py`
- Test: `backend/tests/test_services/test_temporal_verification.py`

- [ ] **Step 1: Escribir el test que falla (helpers de fechas relativas)**

Crea `backend/tests/test_services/test_temporal_verification.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from lakehouse.config import Settings
from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult
from lakehouse.services import temporal_verification
from lakehouse.services.temporal_verification import (
    TemporalTestCase,
    _esperados_relativos,
    _evaluar_ok,
    build_casos,
)

_MX = ZoneInfo("America/Mexico_City")


class TestEsperadosRelativos:
    def test_ayer(self):
        now = datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX)
        inicio, fin = _esperados_relativos("America/Mexico_City", "ayer", now)
        assert inicio == "2026-09-07 00:00:00"
        assert fin == "2026-09-07 23:59:59"

    def test_lunes_pasado_desde_martes(self):
        now = datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX)  # martes
        inicio, fin = _esperados_relativos("America/Mexico_City", "lunes_pasado", now)
        assert inicio == "2026-09-07 00:00:00"
        assert fin == "2026-09-07 23:59:59"

    def test_lunes_pasado_desde_lunes(self):
        now = datetime(2026, 9, 7, 10, 0, 0, tzinfo=_MX)  # lunes
        inicio, fin = _esperados_relativos("America/Mexico_City", "lunes_pasado", now)
        assert inicio == "2026-08-31 00:00:00"
        assert fin == "2026-08-31 23:59:59"

    def test_ultima_semana(self):
        now = datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX)  # martes
        inicio, fin = _esperados_relativos("America/Mexico_City", "ultima_semana", now)
        assert inicio == "2026-09-07 00:00:00"
        assert fin == "2026-09-08 23:59:59"


class TestBuildCasos:
    def test_tiene_cinco_casos_con_tipos_correctos(self):
        casos = build_casos("America/Mexico_City", now=datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX))
        assert len(casos) == 5
        assert [c.tipo for c in casos] == [
            "absoluta",
            "relativa",
            "relativa",
            "relativa",
            "sin_intento",
        ]
        absoluta = casos[0]
        assert absoluta.esperado_inicio == "2025-07-15 00:00:00"
        assert absoluta.esperado_fin == "2025-07-15 23:59:59"
        assert casos[-1].esperado_inicio is None


class TestEvaluarOk:
    def test_sin_intento(self):
        caso = TemporalTestCase(query="x", tipo="sin_intento")
        assert _evaluar_ok(caso, False, None, None) is True
        assert _evaluar_ok(caso, True, None, None) is False

    def test_absoluta_coincidencia(self):
        caso = TemporalTestCase(
            query="x",
            tipo="absoluta",
            esperado_inicio="2025-07-15 00:00:00",
            esperado_fin="2025-07-15 23:59:59",
        )
        assert _evaluar_ok(caso, True, "2025-07-15 00:00:00", "2025-07-15 23:59:59") is True
        assert _evaluar_ok(caso, True, "2025-07-16 00:00:00", "2025-07-16 23:59:59") is False

    def test_relativa_sin_filtro_falla(self):
        caso = TemporalTestCase(query="x", tipo="relativa", esperado_inicio="2026-09-07 00:00:00")
        assert _evaluar_ok(caso, False, None, None) is False


class TestVerifyTemporalGemini:
    def test_orquestacion_solo_absoluta_coincide(self, monkeypatch):
        class _FakeParser:
            def __init__(self, settings):  # noqa: ANN001
                self.settings = settings

            def extraer(self, query: str) -> TimeParserResult:
                return TimeParserResult(
                    filter_out=TimeFilterOut(
                        requiere_filtro_tiempo=True,
                        fecha_inicio="2025-07-15 00:00:00",
                        fecha_fin="2025-07-15 23:59:59",
                        texto_busqueda_semantica="semantica",
                    ),
                    fallback_ocurrido=False,
                    raw_llm_response="{}",
                )

        monkeypatch.setattr(temporal_verification, "TemporalParser", _FakeParser)
        monkeypatch.setattr(temporal_verification, "embed_search_query", lambda s, t: [0.1])
        monkeypatch.setattr(
            temporal_verification,
            "search_with_date_filter",
            lambda v, k, i, f, s: [{"conference_date": "2025-07-15"}],
        )
        monkeypatch.setattr(
            temporal_verification, "search_gold_corpus_from_vector", lambda v, k, s: []
        )

        result = temporal_verification.verify_temporal_gemini(
            Settings(app_env="production", gemini_api_key="k", neon_database_url="x")
        )

        assert result.total == 5
        assert result.pasaron == 1
        assert result.casos[0].ok is True
        assert result.casos[0].source_count == 1
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `cd backend && uv run pytest tests/test_services/test_temporal_verification.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lakehouse.services.temporal_verification'`

- [ ] **Step 3: Implementar el servicio**

Crea `backend/src/lakehouse/services/temporal_verification.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.services.rag_search import (
    embed_search_query,
    search_gold_corpus_from_vector,
    search_with_date_filter,
)
from lakehouse.services.temporal_parser import TemporalParser

logger = get_logger(__name__, layer="service")

_Relativa = Literal["ayer", "lunes_pasado", "ultima_semana"]


class TemporalTestCase(BaseModel):
    query: str
    tipo: Literal["absoluta", "relativa", "sin_intento"]
    semilla_relativa: _Relativa | None = None
    esperado_inicio: str | None = None
    esperado_fin: str | None = None


class TemporalCaseResult(BaseModel):
    query: str
    tipo: str
    ok: bool
    requiere_filtro: bool
    obtenido_inicio: str | None
    obtenido_fin: str | None
    esperado_inicio: str | None
    esperado_fin: str | None
    fallback_ocurrido: bool
    source_count: int
    fuentes: list[str]


class VerifyResult(BaseModel):
    total: int
    pasaron: int
    casos: list[TemporalCaseResult]


_CASOS_BASE: list[dict] = [
    {
        "query": "Que dijo Sheinbaum el 15 de julio de 2025?",
        "tipo": "absoluta",
        "esperado_inicio": "2025-07-15 00:00:00",
        "esperado_fin": "2025-07-15 23:59:59",
    },
    {"query": "Que paso ayer?", "tipo": "relativa", "semilla_relativa": "ayer"},
    {
        "query": "Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?",
        "tipo": "relativa",
        "semilla_relativa": "lunes_pasado",
    },
    {
        "query": "Que paso la ultima semana?",
        "tipo": "relativa",
        "semilla_relativa": "ultima_semana",
    },
    {"query": "Cual es la postura sobre energia nuclear?", "tipo": "sin_intento"},
]


def _esperados_relativos(
    tz_name: str, semilla: str, now: datetime | None = None
) -> tuple[str, str]:
    if now is None:
        now = datetime.now(ZoneInfo(tz_name))
    if semilla == "ayer":
        dia = now - timedelta(days=1)
        return f"{dia:%Y-%m-%d} 00:00:00", f"{dia:%Y-%m-%d} 23:59:59"
    dias_desde_lunes = now.weekday()
    if dias_desde_lunes == 0:
        dias_desde_lunes = 7
    inicio = now - timedelta(days=dias_desde_lunes)
    if semilla == "ultima_semana":
        return f"{inicio:%Y-%m-%d} 00:00:00", f"{now:%Y-%m-%d} 23:59:59"
    return f"{inicio:%Y-%m-%d} 00:00:00", f"{inicio:%Y-%m-%d} 23:59:59"


def build_casos(tz_name: str, now: datetime | None = None) -> list[TemporalTestCase]:
    casos: list[TemporalTestCase] = []
    for base in _CASOS_BASE:
        if base["tipo"] == "relativa":
            inicio, fin = _esperados_relativos(tz_name, base["semilla_relativa"], now)
            casos.append(TemporalTestCase(esperado_inicio=inicio, esperado_fin=fin, **base))
        else:
            casos.append(TemporalTestCase(**base))
    return casos


def _evaluar_ok(
    caso: TemporalTestCase,
    requiere_filtro: bool,
    obtenido_inicio: str | None,
    obtenido_fin: str | None,
) -> bool:
    if caso.tipo == "sin_intento":
        return requiere_filtro is False
    if not requiere_filtro:
        return False
    return obtenido_inicio == caso.esperado_inicio and obtenido_fin == caso.esperado_fin


def _verificar_caso(
    parser: TemporalParser,
    caso: TemporalTestCase,
    top_k: int,
    settings: Settings,
) -> TemporalCaseResult:
    parser_result = parser.extraer(caso.query)
    filtro = parser_result.filter_out

    source_count = 0
    fuentes: list[str] = []
    try:
        vec = embed_search_query(settings, filtro.texto_busqueda_semantica)
        if filtro.requiere_filtro_tiempo:
            assert filtro.fecha_inicio is not None
            assert filtro.fecha_fin is not None
            results = search_with_date_filter(
                vec, top_k, filtro.fecha_inicio, filtro.fecha_fin, settings
            )
        else:
            results = search_gold_corpus_from_vector(vec, top_k, settings)
        source_count = len(results)
        fuentes = [str(r["conference_date"]) for r in results]
    except Exception:
        logger.exception("Verificacion temporal: busqueda fallo", query=caso.query)

    ok = _evaluar_ok(
        caso, filtro.requiere_filtro_tiempo, filtro.fecha_inicio, filtro.fecha_fin
    )

    return TemporalCaseResult(
        query=caso.query,
        tipo=caso.tipo,
        ok=ok,
        requiere_filtro=filtro.requiere_filtro_tiempo,
        obtenido_inicio=filtro.fecha_inicio,
        obtenido_fin=filtro.fecha_fin,
        esperado_inicio=caso.esperado_inicio,
        esperado_fin=caso.esperado_fin,
        fallback_ocurrido=parser_result.fallback_ocurrido,
        source_count=source_count,
        fuentes=fuentes,
    )


def verify_temporal_gemini(settings: Settings, top_k: int = 8) -> VerifyResult:
    parser = TemporalParser(settings)
    casos = build_casos(settings.app_timezone)
    resultados = [_verificar_caso(parser, caso, top_k, settings) for caso in casos]
    pasaron = sum(1 for r in resultados if r.ok)
    return VerifyResult(total=len(resultados), pasaron=pasaron, casos=resultados)
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `cd backend && uv run pytest tests/test_services/test_temporal_verification.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/services/temporal_verification.py backend/tests/test_services/test_temporal_verification.py
git commit -m "agrega servicio de verificacion temporal contra Gemini"
```

---

## Task 2: Comando CLI `verify-temporal-gemini`

**Files:**
- Modify: `backend/src/lakehouse/cli.py`
- Test: `backend/tests/test_cli.py`

- [ ] **Step 1: Escribir los tests que fallan**

Añade al final de `backend/tests/test_cli.py` (importa `VerifyResult` arriba):

```python
from lakehouse.services.temporal_verification import VerifyResult
```

Y una nueva clase:

```python
class TestVerifyTemporalGemini:
    @patch("lakehouse.cli.Settings")
    def test_sin_gemini_key_falla_cerrado(self, mock_settings):
        mock_settings.return_value = Settings(
            app_env="production", gemini_api_key="", neon_database_url="x"
        )
        result = runner.invoke(app, ["verify-temporal-gemini"])
        assert result.exit_code != 0
        assert "GEMINI_API_KEY" in result.output

    @patch("lakehouse.cli.Settings")
    def test_sin_neon_url_falla_cerrado(self, mock_settings):
        mock_settings.return_value = Settings(
            app_env="production", gemini_api_key="k", neon_database_url=""
        )
        result = runner.invoke(app, ["verify-temporal-gemini"])
        assert result.exit_code != 0
        assert "NEON_DATABASE_URL" in result.output

    @patch("lakehouse.cli.Settings")
    def test_sin_produccion_falla_cerrado(self, mock_settings):
        mock_settings.return_value = Settings(
            app_env="local", gemini_api_key="k", neon_database_url="x"
        )
        result = runner.invoke(app, ["verify-temporal-gemini"])
        assert result.exit_code != 0
        assert "production" in result.output

    @patch("lakehouse.cli.verify_temporal_gemini_fn")
    @patch("lakehouse.cli.Settings")
    def test_exito_imprime_resumen(self, mock_settings, mock_verify):
        mock_settings.return_value = Settings(
            app_env="production", gemini_api_key="k", neon_database_url="x"
        )
        mock_verify.return_value = VerifyResult(total=5, pasaron=5, casos=[])
        result = runner.invoke(app, ["verify-temporal-gemini"])
        assert result.exit_code == 0
        assert "5/5" in result.output
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `cd backend && uv run pytest tests/test_cli.py::TestVerifyTemporalGemini -q`
Expected: FAIL — comando no existe (`No such command`)

- [ ] **Step 3: Implementar el comando**

En `backend/src/lakehouse/cli.py`, añade el import:

```python
from lakehouse.services.temporal_verification import verify_temporal_gemini as verify_temporal_gemini_fn
```

Y el comando (junto a `evaluate_rag`):

```python
@app.command()
def verify_temporal_gemini() -> None:
    """Verifica el parser temporal contra Gemini y Neon productivos.

    Ejecuta las mismas consultas de tiempo (absolutas y relativas) y compara las
    fechas parseadas contra las esperadas en America/Mexico_City. Requiere secretos
    productivos (GEMINI_API_KEY y NEON_DATABASE_URL) inyectados por Secret Manager.
    """
    settings = Settings()
    if not settings.is_production:
        raise typer.BadParameter("APP_ENV debe ser 'production' para verificar con Gemini/Neon")
    if not settings.gemini_api_key:
        raise typer.BadParameter("GEMINI_API_KEY es obligatorio (Secret Manager/env)")
    if not settings.neon_database_url:
        raise typer.BadParameter("NEON_DATABASE_URL es obligatorio (Secret Manager/env)")

    result = verify_temporal_gemini_fn(settings)
    for caso in result.casos:
        estado = "PASS" if caso.ok else "FAIL"
        typer.echo(f"[{estado}] {caso.query}")
        typer.echo(f"    esperado: {caso.esperado_inicio} .. {caso.esperado_fin}")
        typer.echo(
            f"    obtenido: {caso.obtenido_inicio} .. {caso.obtenido_fin} "
            f"(filtro={caso.requiere_filtro}, fuentes={caso.source_count})"
        )
    typer.echo(f"\nResultado: {result.pasaron}/{result.total} casos pasaron")
    raise typer.Exit(code=0 if result.pasaron == result.total else 1)
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `cd backend && uv run pytest tests/test_cli.py::TestVerifyTemporalGemini -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add backend/src/lakehouse/cli.py backend/tests/test_cli.py
git commit -m "agrega comando verify-temporal-gemini fail-closed"
```

---

## Task 3: Test de integración parser→Gemini

**Files:**
- Create: `backend/tests/test_services/test_temporal_parser_gemini.py`

- [ ] **Step 1: Escribir el test de integración (mock solo `google.genai.Client`)**

Crea `backend/tests/test_services/test_temporal_parser_gemini.py`:

```python
from __future__ import annotations

from typing import ClassVar

import pytest
from google import genai

from lakehouse.config import Settings
from lakehouse.services.temporal_parser import TemporalParser


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self) -> None:
        self.generate_calls: list[tuple] = []
        self.gen_text = ""

    def generate_content(self, *, model, contents, config=None) -> _FakeResponse:
        self.generate_calls.append((model, contents, config))
        return _FakeResponse(self.gen_text)


class _FakeClient:
    shared_models: ClassVar[_FakeModels | None] = None

    def __init__(self, api_key: str | None = None, **kwargs: object) -> None:
        self.api_key = api_key
        if _FakeClient.shared_models is None:
            _FakeClient.shared_models = _FakeModels()
        self.models = _FakeClient.shared_models


@pytest.fixture
def fake_genai(monkeypatch) -> _FakeModels:
    models = _FakeModels()
    _FakeClient.shared_models = models
    monkeypatch.setattr(genai, "Client", _FakeClient)
    return models


def _prod_settings() -> Settings:
    return Settings(
        app_env="production",
        gemini_api_key="test-key",
        gemini_chat_model="gemini-3.5-flash-lite",
        gemini_embedding_model="gemini-embedding-001",
        neon_database_url="postgresql://u:p@ep-test-pooler.us-east-2.aws.neon.tech/db?sslmode=require",
    )


class TestTemporalParserProduccionGemini:
    def test_extraer_usa_gemini_con_system_instruction_y_mime_json(self, fake_genai):
        fake_genai.gen_text = (
            '{"requiere_filtro_tiempo":true,"fecha_inicio":"2025-07-15 00:00:00",'
            '"fecha_fin":"2025-07-15 23:59:59",'
            '"texto_busqueda_semantica":"Que dijo Sheinbaum"}'
        )
        parser = TemporalParser(_prod_settings())

        result = parser.extraer("Que dijo Sheinbaum el 15 de julio de 2025?")

        assert result.fallback_ocurrido is False
        assert result.filter_out.requiere_filtro_tiempo is True
        assert result.filter_out.fecha_inicio == "2025-07-15 00:00:00"
        assert result.filter_out.fecha_fin == "2025-07-15 23:59:59"

        model, contents, config = fake_genai.generate_calls[0]
        assert model == "gemini-3.5-flash-lite"
        assert config.system_instruction is not None
        assert "fecha/hora actual" in config.system_instruction
        assert config.response_mime_type == "application/json"
        assert config.max_output_tokens == 8192
        assert contents[0].role == "user"

    def test_extraer_marca_fallback_ante_json_invalido_de_gemini(self, fake_genai):
        fake_genai.gen_text = "no soy un json"
        parser = TemporalParser(_prod_settings())

        result = parser.extraer("Que paso ayer?")

        assert result.fallback_ocurrido is True
        assert result.filter_out.requiere_filtro_tiempo is False
```

- [ ] **Step 2: Correr el test y verificar que pasa**

Run: `cd backend && uv run pytest tests/test_services/test_temporal_parser_gemini.py -q`
Expected: PASS (ambos) — el wiring parser→Gemini ya funciona; si no, revela un bug real del adapter.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_services/test_temporal_parser_gemini.py
git commit -m "agrega test de integracion parser temporal contra Gemini"
```

---

## Task 4: Documentación y Gate Q

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Documentar el comando en AGENTS.md**

En la tabla de comandos de `AGENTS.md`, bajo el bloque "Evaluacion RAG", añade:

```markdown
# Verificacion temporal contra Gemini (produccion): python -m lakehouse verify-temporal-gemini
# Requiere GEMINI_API_KEY y NEON_DATABASE_URL (Secret Manager). Corre las mismas consultas de tiempo.
```

- [ ] **Step 2: Lint + format**

Run: `cd backend && make lint-fix`
Expected: `ruff check --fix` + `ruff format` sin errores.

- [ ] **Step 3: Typecheck**

Run: `cd backend && make typecheck-backend`
Expected: `ty check` → "All checks passed!"

- [ ] **Step 4: Suite completa con gate de cobertura**

Run: `cd backend && make test-backend`
Expected: todos los tests pasan y cobertura >= 90%.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "documenta comando verify-temporal-gemini en AGENTS.md"
```

---

## Verificación manual (en Cloud Run, cuando haya credenciales)

Con secretos inyectados (o `.env.production`), correr:

```bash
cd backend && python -m lakehouse verify-temporal-gemini
```

Salida esperada: tabla `[PASS]/[FAIL]` por consulta con fechas esperadas vs obtenidas y conteo de
fuentes, y `Resultado: 5/5 casos pasaron` (exit 0). Si Gemini desvía una fecha, el caso marca
`FAIL` y el comando sale con código 1.
