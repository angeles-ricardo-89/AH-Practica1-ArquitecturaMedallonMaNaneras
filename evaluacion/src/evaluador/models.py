from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Estado(str, Enum):
    CUMPLE = "CUMPLE"
    PARCIAL = "PARCIAL"
    NO_CUMPLE = "NO_CUMPLE"
    INCONCLUSO = "INCONCLUSO"


@dataclass
class Evidencia:
    path: str
    descripcion: str
    contenido: str = ""


@dataclass
class ResultadoCriterio:
    id: str
    nombre: str
    estado: Estado
    score: float
    max_score: float
    strategy: str = ""
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    hallazgos_evidencia: list[Evidencia] = field(default_factory=list)


@dataclass
class ResultadoEjecucion:
    comando: str
    codigo_salida: int
    stdout: str
    stderr: str
    duracion_ms: int
    excepcion: str = ""


@dataclass
class CorridaEvaluacion:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    commit: str | None = None
    resultados: list[ResultadoCriterio] = field(default_factory=list)
    ejecuciones: list[ResultadoEjecucion] = field(default_factory=list)
    score_total: float = 0.0
    max_score: float = 100.0
    supuestos: list[str] = field(default_factory=list)
    limitaciones: list[str] = field(default_factory=list)
    directorio: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "commit": self.commit,
            "score": self.score_total,
            "max_score": self.max_score,
            "criteria": [
                {
                    "id": r.id,
                    "name": r.nombre,
                    "status": r.estado.value,
                    "score": r.score,
                    "max_score": r.max_score,
                    "strategy": r.strategy,
                    "rationale": r.rationale,
                    "evidence": r.evidence,
                    "findings": r.findings,
                    "limitations": r.limitations,
                }
                for r in self.resultados
            ],
        }
