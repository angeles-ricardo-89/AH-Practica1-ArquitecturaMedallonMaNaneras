from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from lakehouse.schemas.agent import (
    BuscarDeclaracionesInput,
    ToolPlan,
)
from lakehouse.services.agent.llm import chat_json
from lakehouse.services.agent.tools import TOOL_INPUT_MODELS, TOOL_NAMES

if TYPE_CHECKING:
    from lakehouse.config import Settings

PLAN_SYSTEM_PROMPT = (
    "Eres un agente de investigacion sobre las conferencias matutinas. Tienes "
    "exactamente tres herramientas de SOLO LECTURA y no puedes usar otras:\n"
    "1. buscar_declaraciones: argumentos {\"consulta\": str, \"fecha_inicio\": "
    "\"YYYY-MM-DD\"|null, \"fecha_fin\": \"YYYY-MM-DD\"|null, \"participante\": str|null, "
    "\"top_k\": int 1..8}. Localiza que se dijo sobre una persona o tema.\n"
    "2. explorar_temas: argumentos {\"texto\": str|null, \"limite\": int 1..5}. "
    "Descubre temas del corpus.\n"
    "3. consultar_cluster: argumentos {\"cluster_id\": int >= 0, \"limite\": int 1..8}. "
    "Explica un tema con declaraciones representativas.\n"
    "Responde SOLO con JSON estricto y valido: "
    "{\"tool_name\": \"<una de las tres>\", \"arguments\": {...}, \"motivo\": \"breve\"}. "
    "No inventes fechas, participantes ni identificadores."
)

REPAIR_INSTRUCTION = (
    "Tu respuesta anterior no fue JSON valido con una herramienta permitida. "
    "Reintenta respondiendo SOLO con JSON estricto y valido."
)


@dataclass
class ToolDecision:
    tool_name: str
    parsed_input: BaseModel
    fallback: bool = False
    trace_arguments: dict = field(default_factory=dict)


def format_history(history: list[dict]) -> str:
    lines = []
    for msg in history[-6:]:
        lines.append(f"{msg.get('role', 'unknown')}: {msg.get('content', '')}")
    return "\n".join(lines)


def parse_plan(raw: str) -> ToolPlan | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return ToolPlan(**data)
    except (json.JSONDecodeError, ValidationError):
        return None


def validate_plan(plan: ToolPlan) -> tuple[str, BaseModel] | None:
    if plan.tool_name is None or plan.tool_name not in TOOL_NAMES:
        return None
    input_cls = TOOL_INPUT_MODELS[plan.tool_name]
    try:
        parsed = input_cls(**plan.arguments)
    except ValidationError:
        return None
    return plan.tool_name, parsed


def _to_decision(tool_name: str, parsed: BaseModel, fallback: bool = False) -> ToolDecision:
    return ToolDecision(
        tool_name=tool_name,
        parsed_input=parsed,
        fallback=fallback,
        trace_arguments=parsed.model_dump(mode="json"),
    )


def _messages(question: str, history: list[dict], extra: str = "") -> list[dict]:
    content = f"Pregunta: {question}"
    if history:
        content = f"Contexto de la investigacion (solo esta conversacion):\n{format_history(history)}\n\n{content}"
    if extra:
        content = f"{content}\n\n{extra}"
    return [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def plan_first_tool(
    settings: Settings, question: str, history: list[dict]
) -> ToolDecision:
    messages = _messages(question, history)
    raw = chat_json(settings, messages)
    plan = parse_plan(raw)
    valid = validate_plan(plan) if plan else None
    if valid is not None:
        return _to_decision(valid[0], valid[1])

    repair_messages = [
        *messages,
        {"role": "assistant", "content": raw or ""},
        {"role": "user", "content": REPAIR_INSTRUCTION},
    ]
    raw_retry = chat_json(settings, repair_messages)
    plan_retry = parse_plan(raw_retry)
    valid_retry = validate_plan(plan_retry) if plan_retry else None
    if valid_retry is not None:
        return _to_decision(valid_retry[0], valid_retry[1], fallback=False)

    return _to_decision(
        "buscar_declaraciones",
        BuscarDeclaracionesInput(consulta=question[:2000], top_k=8),
        fallback=True,
    )


def plan_followup(
    settings: Settings,
    question: str,
    history: list[dict],
    last_result_summary: str,
) -> ToolDecision | None:
    extra = (
        "Resultado de la primera herramienta:\n"
        f"{last_result_summary}\n\n"
        "Si hace falta UNA segunda herramienta para completar la investigacion, "
        "responde con su JSON. Si ya es suficiente para responder, responde "
        'exactamente {"tool_name": null}.'
    )
    messages = _messages(question, history, extra)
    raw = chat_json(settings, messages)
    plan = parse_plan(raw)
    if plan is None or plan.tool_name is None:
        return None
    valid = validate_plan(plan)
    if valid is None:
        return None
    return _to_decision(valid[0], valid[1])
