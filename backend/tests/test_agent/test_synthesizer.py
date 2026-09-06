from __future__ import annotations

from datetime import date
from unittest.mock import patch

from lakehouse.config import Settings
from lakehouse.schemas.agent import (
    BuscarDeclaracionesOutput,
    ClusterDetalle,
    ClusterResumen,
    ConsultarClusterOutput,
    Evidencia,
    EvidenciaCluster,
    ExplorarTemasOutput,
)
from lakehouse.services.agent.synthesizer import (
    REFUSAL_TEXT,
    format_results,
    synthesize,
)


def _evidencia(sim: float) -> Evidencia:
    return Evidencia(
        evidence_id=f"k{sim}",
        texto="declaracion relevante sobre el tema",
        fecha=date(2025, 1, 1),
        participante="PRESIDENTA",
        conferencia="c1",
        url="https://gob.mx/1",
        similitud=sim,
    )


def test_refuses_without_evidence() -> None:
    with patch("lakehouse.services.agent.synthesizer.chat_text") as mock:
        answer, refusal = synthesize(Settings(), "pregunta", [], [])
    assert refusal is True
    assert answer == REFUSAL_TEXT
    mock.assert_not_called()


def test_refuses_when_weak_evidence() -> None:
    # Evidencia no vacia aunque de similitud baja NO dispara negativa dura:
    # la suficiencia la juzga el sintetizador anclado a la evidencia.
    results = [BuscarDeclaracionesOutput(evidencias=[_evidencia(0.3)])]
    with patch(
        "lakehouse.services.agent.synthesizer.chat_text", return_value="Respuesta citada"
    ) as mock:
        answer, refusal = synthesize(Settings(), "pregunta", [], results)
    assert refusal is False
    assert answer == "Respuesta citada"
    mock.assert_called_once()


def test_refuses_when_tool_returns_no_evidence() -> None:
    results = [BuscarDeclaracionesOutput(evidencias=[])]
    answer, refusal = synthesize(Settings(), "pregunta", [], results)
    assert refusal is True
    assert "No encontré" in answer


def test_answers_with_strong_evidence() -> None:
    results = [BuscarDeclaracionesOutput(evidencias=[_evidencia(0.9)])]
    with patch(
        "lakehouse.services.agent.synthesizer.chat_text", return_value="Respuesta citada"
    ) as mock:
        answer, refusal = synthesize(Settings(), "pregunta", [], results)
    assert refusal is False
    assert answer == "Respuesta citada"
    mock.assert_called_once()


def test_format_results_covers_three_tools() -> None:
    results = [
        BuscarDeclaracionesOutput(evidencias=[_evidencia(0.9)]),
        ConsultarClusterOutput(
            cluster=ClusterDetalle(cluster_id=1, etiqueta="energia", tamano=10),
            evidencias=[
                EvidenciaCluster(
                    evidence_id="kc",
                    texto="declaracion",
                    fecha=date(2025, 1, 1),
                    participante="PRESIDENTA",
                    conferencia="conf_1",
                    url="https://gob.mx",
                    pertenencia=0.8,
                )
            ],
        ),
        ExplorarTemasOutput(
            clusters=[
                ClusterResumen(
                    cluster_id=2,
                    etiqueta="salud",
                    terminos=["salud"],
                    tamano=5,
                    cohesion=0.6,
                    fecha_inicio=date(2025, 1, 1),
                    fecha_fin=date(2025, 1, 2),
                )
            ]
        ),
    ]
    text = format_results(results)
    assert "declaracion" in text
    assert "Cluster" in text
    assert "Tema" in text
