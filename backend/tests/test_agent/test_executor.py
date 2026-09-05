from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from lakehouse.config import Settings
from lakehouse.schemas.agent import (
    AgentTurnResult,
    BuscarDeclaracionesOutput,
    Evidencia,
    ToolExecutionTrace,
)
from lakehouse.services.agent.executor import run_agent_turn

VALID_PLAN = (
    '{"tool_name": "buscar_declaraciones", '
    '"arguments": {"consulta": "reforma energetica"}, "motivo": "tema"}'
)
FOLLOWUP_NONE = '{"tool_name": null}'
FOLLOWUP_TOOL = (
    '{"tool_name": "consultar_cluster", '
    '"arguments": {"cluster_id": 1, "limite": 4}, "motivo": "detalle"}'
)

STRONG = BuscarDeclaracionesOutput(
    evidencias=[
        Evidencia(
            evidence_id="k1",
            texto="declaracion relevante",
            fecha=date(2025, 1, 1),
            participante="PRESIDENTA",
            conferencia="c1",
            url="https://gob.mx/1",
            similitud=0.9,
        )
    ]
)


def _fake_settings() -> Settings:
    return Settings(llamacpp_model="gemma-4-12b")


def test_run_agent_turn_single_tool() -> None:
    with (
        patch(
            "lakehouse.services.agent.planner.chat_json",
            side_effect=[VALID_PLAN, FOLLOWUP_NONE],
        ),
        patch(
            "lakehouse.services.agent.executor.buscar_declaraciones", return_value=STRONG
        ),
        patch(
            "lakehouse.services.agent.synthesizer.chat_text",
            return_value="Respuesta con cita",
        ),
    ):
        result = run_agent_turn(_fake_settings(), "reforma energetica", [])

    assert isinstance(result, AgentTurnResult)
    assert result.answer == "Respuesta con cita"
    assert result.refusal is False
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "buscar_declaraciones"
    assert result.tool_executions[0].status == "ok"


def test_run_agent_turn_allows_two_tools() -> None:
    with (
        patch(
            "lakehouse.services.agent.planner.chat_json",
            side_effect=[VALID_PLAN, FOLLOWUP_TOOL],
        ),
        patch(
            "lakehouse.services.agent.executor.buscar_declaraciones", return_value=STRONG
        ),
        patch(
            "lakehouse.services.agent.executor.consultar_cluster", return_value=STRONG
        ) as mock_cluster,
        patch(
            "lakehouse.services.agent.synthesizer.chat_text",
            return_value="Respuesta con dos tools",
        ),
    ):
        result = run_agent_turn(_fake_settings(), "reforma energetica", [])

    assert len(result.tool_executions) == 2
    assert result.tool_executions[1].tool_name == "consultar_cluster"
    mock_cluster.assert_called_once()


def test_run_agent_turn_never_exceeds_two_tools() -> None:
    with (
        patch(
            "lakehouse.services.agent.planner.chat_json",
            side_effect=[VALID_PLAN, FOLLOWUP_TOOL, FOLLOWUP_TOOL],
        ),
        patch(
            "lakehouse.services.agent.executor.buscar_declaraciones", return_value=STRONG
        ),
        patch(
            "lakehouse.services.agent.executor.consultar_cluster", return_value=STRONG
        ),
        patch(
            "lakehouse.services.agent.synthesizer.chat_text",
            return_value="Respuesta",
        ),
    ):
        result = run_agent_turn(_fake_settings(), "reforma energetica", [])

    assert len(result.tool_executions) == 2


def test_run_agent_turn_raises_on_first_tool_error() -> None:
    with (
        patch(
            "lakehouse.services.agent.planner.chat_json",
            side_effect=[VALID_PLAN, FOLLOWUP_NONE],
        ),
        patch(
            "lakehouse.services.agent.executor.buscar_declaraciones",
            side_effect=RuntimeError("base de datos caida"),
        ),
        pytest.raises(RuntimeError),
    ):
        run_agent_turn(_fake_settings(), "reforma energetica", [])


def test_run_agent_turn_persists_fallback_trace() -> None:
    with (
        patch(
            "lakehouse.services.agent.planner.chat_json",
            side_effect=["invalido", "invalido", FOLLOWUP_NONE],
        ),
        patch(
            "lakehouse.services.agent.executor.buscar_declaraciones", return_value=STRONG
        ),
        patch(
            "lakehouse.services.agent.synthesizer.chat_text",
            return_value="Respuesta fallback",
        ),
    ):
        result = run_agent_turn(_fake_settings(), "reforma energetica", [])

    assert len(result.tool_executions) == 1
    trace = result.tool_executions[0]
    assert isinstance(trace, ToolExecutionTrace)
    assert trace.status == "fallback"
    assert trace.tool_name == "buscar_declaraciones"
