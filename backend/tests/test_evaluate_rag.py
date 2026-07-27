from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lakehouse.pipeline.evaluate_rag import (
    _parse_score,
    evaluate_rag,
)

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "data" / "golden_dataset.json"


@pytest.fixture
def golden_data() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text())


@pytest.fixture
def mock_chat_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "La reforma energética fortalece a Pemex."}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }
    return resp


@pytest.fixture
def mock_judge_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "95"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5},
    }
    return resp


class TestGoldenDataset:
    def test_golden_dataset_exists(self) -> None:
        assert GOLDEN_PATH.exists(), "golden_dataset.json must exist"

    def test_golden_dataset_has_50_questions(self, golden_data: list[dict]) -> None:
        assert len(golden_data) == 50

    def test_golden_dataset_required_fields(self, golden_data: list[dict]) -> None:
        for item in golden_data:
            assert "id" in item
            assert "question" in item
            assert "reference_answer" in item
            assert "expected_topics" in item
            assert "category" in item
            assert isinstance(item["id"], int)
            assert isinstance(item["question"], str) and len(item["question"]) > 0
            assert isinstance(item["reference_answer"], str) and len(item["reference_answer"]) > 0
            assert isinstance(item["expected_topics"], list) and len(item["expected_topics"]) > 0
            assert isinstance(item["category"], str) and len(item["category"]) > 0

    def test_golden_dataset_unique_ids(self, golden_data: list[dict]) -> None:
        ids = [item["id"] for item in golden_data]
        assert len(ids) == len(set(ids))

    def test_golden_dataset_questions_spanish(self, golden_data: list[dict]) -> None:
        for item in golden_data:
            assert any(char in item["question"] for char in "áéíóúñ¿¡"), (
                f"Question {item['id']} should contain Spanish characters"
            )

    def test_golden_dataset_categories(self, golden_data: list[dict]) -> None:
        categories = {item["category"] for item in golden_data}
        expected = {
            "reformas",
            "salud",
            "seguridad",
            "economía",
            "programas sociales",
            "anticorrupción",
            "relaciones exteriores",
            "infraestructura",
            "igualdad",
            "general",
            "medio ambiente",
        }
        assert categories == expected


class TestEvaluateRag:
    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    @patch("lakehouse.pipeline.evaluate_rag._call_llamacpp")
    def test_evaluate_rag_completes(
        self,
        mock_llamacpp: MagicMock,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.return_value = "La reforma energética fortalece a Pemex."
        mock_llamacpp.return_value = "95"

        result = evaluate_rag()

        assert result["status"] == "completed"
        assert result["total"] == 50
        assert result["scored"] == 50
        assert result["failed"] == 0
        assert result["avg_fidelity"] >= 90.0
        assert result["avg_relevance"] >= 80.0

    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    @patch("lakehouse.pipeline.evaluate_rag._call_llamacpp")
    def test_evaluate_rag_saves_results_file(
        self,
        mock_llamacpp: MagicMock,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.return_value = "Respuesta de prueba."
        mock_llamacpp.return_value = "90"

        result = evaluate_rag()

        output_path = Path(result["output_path"])
        assert output_path.exists()
        saved = json.loads(output_path.read_text())
        assert saved["status"] == "completed"
        assert len(saved["results"]) == 50

    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    @patch("lakehouse.pipeline.evaluate_rag._call_llamacpp")
    def test_evaluate_rag_uses_settings(
        self,
        mock_llamacpp: MagicMock,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.return_value = "Respuesta."
        mock_llamacpp.return_value = "85"

        result = evaluate_rag()

        assert result["total"] == 50

    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    def test_evaluate_rag_handles_chat_failure(
        self,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.side_effect = RuntimeError("Chat unavailable")

        result = evaluate_rag()

        assert result["status"] == "completed"
        assert result["total"] == 50
        assert result["failed"] == 50

    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    @patch("lakehouse.pipeline.evaluate_rag._call_llamacpp")
    def test_evaluate_rag_includes_all_ids(
        self,
        mock_llamacpp: MagicMock,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.return_value = "Respuesta."
        mock_llamacpp.return_value = "90"

        result = evaluate_rag()

        ids = {r["id"] for r in result["results"]}
        assert ids == set(range(1, 51))

    @patch("lakehouse.pipeline.evaluate_rag._call_chat")
    @patch("lakehouse.pipeline.evaluate_rag._call_llamacpp")
    def test_evaluate_rag_fidelity_and_relevance_scores(
        self,
        mock_llamacpp: MagicMock,
        mock_chat: MagicMock,
    ) -> None:
        mock_chat.return_value = "Respuesta."
        mock_llamacpp.return_value = "95"

        result = evaluate_rag()

        for r in result["results"]:
            if "error" not in r:
                assert r["fidelity"] == 95.0
                assert r["relevance"] == 95.0


class TestParseScore:
    def test_parse_numeric_string(self) -> None:
        assert _parse_score("95") == 95.0

    def test_parse_with_text_prefix(self) -> None:
        assert _parse_score("fidelidad: 85") == 85.0

    def test_parse_with_percent_sign(self) -> None:
        assert _parse_score("90%") == 90.0

    def test_parse_decimal(self) -> None:
        assert _parse_score("92.5") == 92.5

    def test_parse_out_of_range_clamps(self) -> None:
        score = _parse_score("150")
        assert score == 50.0

    def test_parse_empty_string_returns_default(self) -> None:
        assert _parse_score("") == 50.0

    def test_parse_nonsense_returns_default(self) -> None:
        assert _parse_score("no aplica") == 50.0

    def test_parse_lowercase_label(self) -> None:
        assert _parse_score("relevancia: 78") == 78.0

    def test_parse_mixed_text(self) -> None:
        assert _parse_score("Puntuación: 88/100") == 88.0

    def test_parse_with_newlines(self) -> None:
        assert _parse_score("\n  92  \n") == 92.0

    def test_parse_score_prefix(self) -> None:
        assert _parse_score("score: 87") == 87.0

    def test_parse_puntaje_prefix(self) -> None:
        assert _parse_score("puntaje: 76") == 76.0
