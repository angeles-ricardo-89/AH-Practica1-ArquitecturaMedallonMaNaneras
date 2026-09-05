from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from lakehouse.schemas.chat import SourceChunk


class ToolPlan(BaseModel):
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    motivo: str = Field(default="", max_length=500)


class ToolExecutionTrace(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_count: int = 0
    duration_ms: int = 0
    status: str = "ok"
    error: str = ""


class AgentTurnResult(BaseModel):
    question: str
    answer: str
    refusal: bool = False
    model_used: str = ""
    tool_executions: list[ToolExecutionTrace] = Field(default_factory=list)
    sources: list[SourceChunk] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0


class BuscarDeclaracionesInput(BaseModel):
    consulta: str = Field(..., min_length=1, max_length=2000)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    participante: str | None = Field(default=None, max_length=200)
    top_k: int = Field(default=8, ge=1, le=8)


class Evidencia(BaseModel):
    evidence_id: str
    texto: str
    fecha: date
    participante: str
    conferencia: str
    url: str
    similitud: float
    embedding_3d: list[float] | None = None
    cluster_id: int | None = None
    pregunta_activa: str = ""


class BuscarDeclaracionesOutput(BaseModel):
    evidencias: list[Evidencia]


class ExplorarTemasInput(BaseModel):
    texto: str | None = Field(default=None, max_length=2000)
    limite: int = Field(default=5, ge=1, le=5)


class ClusterResumen(BaseModel):
    cluster_id: int
    etiqueta: str | None
    terminos: list[str]
    tamano: int
    cohesion: float | None
    fecha_inicio: date | None
    fecha_fin: date | None


class ExplorarTemasOutput(BaseModel):
    clusters: list[ClusterResumen]


class ConsultarClusterInput(BaseModel):
    cluster_id: int = Field(..., ge=0)
    limite: int = Field(default=8, ge=1, le=8)


class ClusterDetalle(BaseModel):
    cluster_id: int
    etiqueta: str | None
    tamano: int


class EvidenciaCluster(BaseModel):
    evidence_id: str
    texto: str
    fecha: date
    participante: str
    url: str
    pertenencia: float | None
    embedding_3d: list[float] | None = None
    pregunta_activa: str = ""


class ConsultarClusterOutput(BaseModel):
    cluster: ClusterDetalle
    evidencias: list[EvidenciaCluster]
