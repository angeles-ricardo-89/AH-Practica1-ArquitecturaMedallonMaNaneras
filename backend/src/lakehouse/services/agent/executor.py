from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from lakehouse.schemas.agent import (
    AgentTurnResult,
    BuscarDeclaracionesInput,
    BuscarDeclaracionesOutput,
    ConsultarClusterInput,
    ConsultarClusterOutput,
    ExplorarTemasInput,
    ExplorarTemasOutput,
    ToolExecutionTrace,
)
from lakehouse.schemas.chat import SourceChunk
from lakehouse.services.agent.planner import (
    ToolDecision,
    plan_first_tool,
    plan_followup,
)
from lakehouse.services.agent.synthesizer import format_results, synthesize
from lakehouse.services.agent.tools import (
    buscar_declaraciones,
    consultar_cluster,
    explorar_temas,
)
from lakehouse.services.token_estimator import estimate_tokens

if TYPE_CHECKING:
    from lakehouse.config import Settings

MAX_TOOLS = 2


def _run_tool(
    decision: ToolDecision, settings: Settings
) -> BuscarDeclaracionesOutput | ExplorarTemasOutput | ConsultarClusterOutput:
    name = decision.tool_name
    if name == "buscar_declaraciones":
        return buscar_declaraciones(
            settings, cast("BuscarDeclaracionesInput", decision.parsed_input)
        )
    if name == "explorar_temas":
        return explorar_temas(
            settings, cast("ExplorarTemasInput", decision.parsed_input)
        )
    if name == "consultar_cluster":
        return consultar_cluster(
            settings, cast("ConsultarClusterInput", decision.parsed_input)
        )
    raise ValueError(f"Unknown tool: {name}")


def _result_count(result: object) -> int:
    if isinstance(result, BuscarDeclaracionesOutput):
        return len(result.evidencias)
    if isinstance(result, ConsultarClusterOutput):
        return len(result.evidencias)
    if isinstance(result, ExplorarTemasOutput):
        return len(result.clusters)
    return 0


def _to_source_chunks(results: list[object]) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    seen_keys: set[str] = set()
    for result in results:
        if isinstance(result, BuscarDeclaracionesOutput):
            for ev in result.evidencias:
                if ev.evidence_id in seen_keys:
                    continue
                seen_keys.add(ev.evidence_id)
                chunks.append(
                    SourceChunk(
                        conference_date=str(ev.fecha),
                        conference_id=ev.conferencia,
                        participant=ev.participante,
                        chunk_text=ev.texto,
                        similarity=ev.similitud,
                        conference_url=ev.url,
                        pregunta_activa=ev.pregunta_activa,
                        qualitative_label="Media",
                        embedding_3d=ev.embedding_3d,
                        cluster_id=ev.cluster_id,
                    )
                )
        elif isinstance(result, ConsultarClusterOutput):
            for ev in result.evidencias:
                if ev.evidence_id in seen_keys:
                    continue
                seen_keys.add(ev.evidence_id)
                chunks.append(
                    SourceChunk(
                        conference_date=str(ev.fecha),
                        conference_id="",
                        participant=ev.participante,
                        chunk_text=ev.texto,
                        similarity=ev.pertenencia or 0.0,
                        conference_url=ev.url,
                        pregunta_activa=ev.pregunta_activa,
                        qualitative_label="Media",
                        embedding_3d=ev.embedding_3d,
                        cluster_id=result.cluster.cluster_id,
                    )
                )
    return chunks


def _execute(
    settings: Settings, decision: ToolDecision
) -> tuple[ToolExecutionTrace, object | None]:
    start = time.perf_counter()
    result: object | None = None
    error = ""
    status = "ok" if not decision.fallback else "fallback"
    try:
        result = _run_tool(decision, settings)
    except Exception as exc:  # noqa: BLE001 - el error queda en la traza
        status = "error"
        error = str(exc)[:200]
    duration_ms = int((time.perf_counter() - start) * 1000)
    trace = ToolExecutionTrace(
        tool_name=decision.tool_name,
        arguments=decision.trace_arguments,
        result_count=_result_count(result) if result is not None else 0,
        duration_ms=duration_ms,
        status=status,
        error=error,
    )
    return trace, result


def run_agent_turn(
    settings: Settings,
    question: str,
    history: list[dict] | None = None,
    max_tools: int = MAX_TOOLS,
) -> AgentTurnResult:
    history = history or []
    traces: list[ToolExecutionTrace] = []
    results: list[object] = []
    turn_start = time.perf_counter()

    decision = plan_first_tool(settings, question, history)
    trace, result = _execute(settings, decision)
    traces.append(trace)
    if trace.status == "error":
        raise RuntimeError(f"Herramienta '{decision.tool_name}' fallo: {trace.error}")
    if result is not None:
        results.append(result)

    if len(traces) < max_tools and results:
        summary = format_results(results)
        followup = plan_followup(settings, question, history, summary)
        if followup is not None:
            trace2, result2 = _execute(settings, followup)
            traces.append(trace2)
            if trace2.status != "error" and result2 is not None:
                results.append(result2)

    answer, refusal = synthesize(settings, question, history, results)
    latency_ms = int((time.perf_counter() - turn_start) * 1000)
    sources = _to_source_chunks(results)

    prompt_text = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
    ) + f"\nuser: {question}\n"
    if results:
        prompt_text += format_results(results)
    total_tokens = estimate_tokens(prompt_text) + estimate_tokens(answer)

    return AgentTurnResult(
        question=question,
        answer=answer,
        refusal=refusal,
        model_used=settings.llamacpp_model,
        tool_executions=traces,
        sources=sources,
        token_usage={"total": total_tokens},
        latency_ms=latency_ms,
    )
