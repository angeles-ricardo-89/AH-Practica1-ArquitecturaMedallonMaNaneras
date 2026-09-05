from __future__ import annotations

from unittest.mock import patch

from lakehouse.config import Settings
from lakehouse.schemas.agent import BuscarDeclaracionesInput, ToolPlan
from lakehouse.services.agent.planner import (
    parse_plan,
    plan_first_tool,
    plan_followup,
    validate_plan,
)

VALID_PLAN = (
    '{"tool_name": "buscar_declaraciones", '
    '"arguments": {"consulta": "reforma energetica"}, "motivo": "tema"}'
)
FOLLOWUP_NONE = '{"tool_name": null}'


def test_parse_plan_valid() -> None:
    plan = parse_plan(VALID_PLAN)
    assert plan is not None
    assert plan.tool_name == "buscar_declaraciones"
    assert plan.arguments["consulta"] == "reforma energetica"


def test_parse_plan_invalid_json() -> None:
    assert parse_plan("no es json") is None


def test_validate_plan_allowlist() -> None:
    valid = validate_plan(ToolPlan(tool_name="explorar_temas", arguments={"limite": 3}))
    assert valid is not None
    assert valid[0] == "explorar_temas"
    unknown = validate_plan(ToolPlan(tool_name="borrar_todo", arguments={}))
    assert unknown is None
    bad_args = validate_plan(
        ToolPlan(tool_name="buscar_declaraciones", arguments={"consulta": ""})
    )
    assert bad_args is None


def test_plan_first_tool_valid() -> None:
    with patch(
        "lakehouse.services.agent.planner.chat_json", return_value=VALID_PLAN
    ) as mock:
        decision = plan_first_tool(Settings(), "reforma", [])
    assert decision.tool_name == "buscar_declaraciones"
    assert isinstance(decision.parsed_input, BuscarDeclaracionesInput)
    assert decision.fallback is False
    mock.assert_called_once()


def test_plan_first_tool_repairs_after_invalid() -> None:
    with patch(
        "lakehouse.services.agent.planner.chat_json",
        side_effect=["texto invalido", VALID_PLAN],
    ) as mock:
        decision = plan_first_tool(Settings(), "reforma", [])
    assert decision.tool_name == "buscar_declaraciones"
    assert decision.fallback is False
    assert mock.call_count == 2


def test_plan_first_tool_fallback_after_double_invalid() -> None:
    with patch(
        "lakehouse.services.agent.planner.chat_json",
        side_effect=["invalido", "invalido"],
    ) as mock:
        decision = plan_first_tool(Settings(), "pregunta sin tool", [])
    assert decision.tool_name == "buscar_declaraciones"
    assert decision.fallback is True
    assert isinstance(decision.parsed_input, BuscarDeclaracionesInput)
    assert mock.call_count == 2


def test_plan_followup_none_when_no_more_tools() -> None:
    with patch(
        "lakehouse.services.agent.planner.chat_json", return_value=FOLLOWUP_NONE
    ) as mock:
        decision = plan_followup(Settings(), "reforma", [], "resumen")
    assert decision is None
    mock.assert_called_once()


def test_plan_followup_returns_tool() -> None:
    with patch(
        "lakehouse.services.agent.planner.chat_json", return_value=VALID_PLAN
    ):
        decision = plan_followup(Settings(), "reforma", [], "resumen")
    assert decision is not None
    assert decision.tool_name == "buscar_declaraciones"
