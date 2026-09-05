from __future__ import annotations

from typing import TYPE_CHECKING

from lakehouse.schemas.agent import (
    BuscarDeclaracionesOutput,
    ConsultarClusterOutput,
    ExplorarTemasOutput,
)
from lakehouse.services.agent.llm import chat_text
from lakehouse.services.agent.planner import format_history

if TYPE_CHECKING:
    from lakehouse.config import Settings

REFUSAL_TEXT = (
    "No encontré evidencia suficiente en el corpus para sostener esa conclusión."
)

SYNTH_SYSTEM_PROMPT = (
    "Eres un asistente de investigacion sobre las conferencias matutinas. "
    "Responde usando UNICAMENTE la evidencia recuperada del corpus. Cita fecha y "
    "participante cuando sea posible. Si la evidencia no basta, dilo y no inventes. "
    "Los clusters son agrupaciones algoritmicas, no hechos."
)


def _has_usable_evidence(results: list) -> bool:
    """Hay evidencia recuperada (declaraciones, cluster o temas). La similitud no es un
    discriminador confiable en este corpus (resultados relevantes rondan ~0.40), asi que la
    negativa dura se reserva para cuando no se recupero NADA; la suficiencia la juzga el
    sintetizador anclado a la evidencia."""
    if not results:
        return False
    for result in results:
        if isinstance(result, ExplorarTemasOutput) and result.clusters:
            return True
        if isinstance(result, ConsultarClusterOutput) and result.evidencias:
            return True
        if isinstance(result, BuscarDeclaracionesOutput) and result.evidencias:
            return True
    return False


def format_results(results: list) -> str:
    blocks: list[str] = []
    for result in results:
        if isinstance(result, BuscarDeclaracionesOutput):
            for ev in result.evidencias[:8]:
                blocks.append(
                    f"[{ev.fecha} | {ev.participante} | sim {ev.similitud:.2f}] "
                    f"{ev.texto} (fuente: {ev.url})"
                )
        elif isinstance(result, ConsultarClusterOutput):
            blocks.append(
                f"Cluster {result.cluster.cluster_id} ({result.cluster.tamano} chunks): "
                f"{result.cluster.etiqueta or 'sin etiqueta'}"
            )
            for ev in result.evidencias[:8]:
                blocks.append(
                    f"[{ev.fecha} | {ev.participante} | pertenencia "
                    f"{ev.pertenencia:.2f}] {ev.texto} (fuente: {ev.url})"
                )
        elif isinstance(result, ExplorarTemasOutput):
            for c in result.clusters[:5]:
                blocks.append(
                    f"Tema: {c.etiqueta or 'sin etiqueta'} ({c.tamano} chunks, "
                    f"{c.cohesion or 0:.2f} cohesion)"
                )
    return "\n".join(blocks)


def synthesize(
    settings: Settings,
    question: str,
    history: list[dict],
    results: list,
) -> tuple[str, bool]:
    if not _has_usable_evidence(results):
        return REFUSAL_TEXT, True

    evidence_text = format_results(results)
    history_text = ""
    if history:
        history_text = f"Contexto de la conversacion:\n{format_history(history)}\n\n"
    prompt = (
        f"{history_text}Evidencia recuperada:\n{evidence_text}\n\n"
        f"Pregunta: {question}\n\n"
        "Responde con base en la evidencia, con citas de fecha y participante."
    )
    answer = chat_text(
        settings,
        [
            {"role": "system", "content": SYNTH_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return answer, False
