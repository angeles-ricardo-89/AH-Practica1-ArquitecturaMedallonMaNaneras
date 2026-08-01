from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta

import httpx
import pydantic

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.temporal import TimeFilterOut, TimeParserResult

logger = get_logger(__name__, layer="service")

_DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _build_system_prompt() -> str:
    now = datetime.now(UTC).astimezone()
    now_iso = now.isoformat()
    weekday = _DIAS_SEMANA[now.weekday()]

    dias_desde_lunes = now.weekday()
    if dias_desde_lunes == 0:
        dias_desde_lunes = 7
    lunes_pasado = (now - timedelta(days=dias_desde_lunes)).strftime("%Y-%m-%d")

    return (
        "Eres un parser de consultas temporales. Tu UNICA tarea es extraer informacion "
        "de tiempo de la pregunta del usuario y devolver un objeto JSON.\n\n"
        "REGLAS:\n"
        f"- La fecha/hora actual del servidor es: {now_iso}\n"
        "- Usa esa referencia para calcular fechas relativas (ayer, la semana pasada, etc.)\n"
        '- fecha_inicio debe ser "YYYY-MM-DD 00:00:00"\n'
        '- fecha_fin debe ser "YYYY-MM-DD 23:59:59"\n'
        "- texto_busqueda_semantica debe contener SOLO la parte semantica de la query, "
        'eliminando TODAS las palabras temporales (fechas, "ayer", "lunes", "reciente", '
        '"semana pasada", "el miercoles", etc.)\n'
        "- Si la query NO tiene intencion temporal, devuelve requiere_filtro_tiempo=false "
        "y fecha_inicio/fecha_fin en null. El texto_busqueda_semantica sera la query completa.\n"
        "- Devuelve UNICAMENTE el JSON, sin texto adicional, sin markdown, sin explicaciones.\n\n"
        "Ejemplos:\n"
        'Query: "Que dijo Sheinbaum sobre el T-MEC en la conferencia del lunes pasado?"\n'
        f"-> Si hoy es {weekday} {now.strftime('%Y-%m-%d')}:\n"
        f'{{"requiere_filtro_tiempo":true, "fecha_inicio":"{lunes_pasado} 00:00:00", '
        f'"fecha_fin":"{lunes_pasado} 23:59:59", '
        '"texto_busqueda_semantica":"Que dijo Sheinbaum sobre el T-MEC en la conferencia"}\n\n'
        'Query: "Cual es la postura sobre energia nuclear?"\n'
        '-> {"requiere_filtro_tiempo":false, "fecha_inicio":null, "fecha_fin":null, '
        '"texto_busqueda_semantica":"Cual es la postura sobre energia nuclear"}'
    )


def _try_parse_json(raw: str) -> dict | None:
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)

    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


class TemporalParser:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def extraer(self, query: str) -> TimeParserResult:
        system_prompt = _build_system_prompt()
        url = f"{self._settings.llamacpp_base_url}/chat/completions"
        temperature = self._settings.temporal_parser_temperature
        max_tokens = self._settings.temporal_parser_max_tokens
        max_retries = self._settings.temporal_parser_max_retries

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(
                        url,
                        json={
                            "model": self._settings.llamacpp_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": query},
                            ],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    resp.raise_for_status()
                    raw = resp.json()["choices"][0]["message"]["content"]

                parsed = _try_parse_json(raw)
                if parsed is not None:
                    try:
                        filter_out = TimeFilterOut.model_validate(parsed)
                        return TimeParserResult(
                            filter_out=filter_out,
                            fallback_ocurrido=False,
                            raw_llm_response=raw,
                        )
                    except pydantic.ValidationError:
                        logger.warning(
                            "TemporalParser attempt %d: JSON parseable pero no valido", attempt + 1
                        )
                        if attempt < max_retries - 1:
                            continue

            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                logger.exception("TemporalParser attempt %d failed", attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (2**attempt))
                continue

        logger.warning("TemporalParser: usando fallback tras %d intentos fallidos", max_retries)
        return TimeParserResult(
            filter_out=TimeFilterOut(
                requiere_filtro_tiempo=False,
                texto_busqueda_semantica=query,
            ),
            fallback_ocurrido=True,
            raw_llm_response="",
        )
