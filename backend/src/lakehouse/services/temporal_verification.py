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
