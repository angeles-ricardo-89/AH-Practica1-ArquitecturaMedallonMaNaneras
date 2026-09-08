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
        now = datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX)
        inicio, fin = _esperados_relativos("America/Mexico_City", "lunes_pasado", now)
        assert inicio == "2026-09-07 00:00:00"
        assert fin == "2026-09-07 23:59:59"

    def test_lunes_pasado_desde_lunes(self):
        now = datetime(2026, 9, 7, 10, 0, 0, tzinfo=_MX)
        inicio, fin = _esperados_relativos("America/Mexico_City", "lunes_pasado", now)
        assert inicio == "2026-08-31 00:00:00"
        assert fin == "2026-08-31 23:59:59"

    def test_ultima_semana(self):
        now = datetime(2026, 9, 8, 2, 10, 0, tzinfo=_MX)
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
        assert (
            _evaluar_ok(caso, requiere_filtro=False, obtenido_inicio=None, obtenido_fin=None)
            is True
        )
        assert (
            _evaluar_ok(caso, requiere_filtro=True, obtenido_inicio=None, obtenido_fin=None)
            is False
        )

    def test_absoluta_coincidencia(self):
        caso = TemporalTestCase(
            query="x",
            tipo="absoluta",
            esperado_inicio="2025-07-15 00:00:00",
            esperado_fin="2025-07-15 23:59:59",
        )
        assert (
            _evaluar_ok(
                caso,
                requiere_filtro=True,
                obtenido_inicio="2025-07-15 00:00:00",
                obtenido_fin="2025-07-15 23:59:59",
            )
            is True
        )
        assert (
            _evaluar_ok(
                caso,
                requiere_filtro=True,
                obtenido_inicio="2025-07-16 00:00:00",
                obtenido_fin="2025-07-16 23:59:59",
            )
            is False
        )

    def test_relativa_sin_filtro_falla(self):
        caso = TemporalTestCase(query="x", tipo="relativa", esperado_inicio="2026-09-07 00:00:00")
        assert (
            _evaluar_ok(caso, requiere_filtro=False, obtenido_inicio=None, obtenido_fin=None)
            is False
        )


class TestVerifyTemporalGemini:
    def test_orquestacion_solo_absoluta_coincide(self, monkeypatch):
        class _FakeParser:
            def __init__(self, settings: Settings) -> None:
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
        monkeypatch.setattr(temporal_verification, "embed_search_query", lambda _s, _t: [0.1])
        monkeypatch.setattr(
            temporal_verification,
            "search_with_date_filter",
            lambda _v, _k, _i, _f, _s: [{"conference_date": "2025-07-15"}],
        )
        monkeypatch.setattr(
            temporal_verification, "search_gold_corpus_from_vector", lambda _v, _k, _s: []
        )

        result = temporal_verification.verify_temporal_gemini(
            Settings(app_env="production", gemini_api_key="k", neon_database_url="x")
        )

        assert result.total == 5
        assert result.pasaron == 1
        assert result.casos[0].ok is True
        assert result.casos[0].source_count == 1
