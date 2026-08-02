from pydantic import BaseModel, Field


class PipelineStatus(BaseModel):
    status: str = Field(default="unknown")
    last_run: str = Field(default="")
    last_success: str = Field(default="")
    records_count: int = Field(default=0, ge=0)
    semaphore: str = Field(default="gray")


class PipelineLogs(BaseModel):
    lines: list[str] = Field(default_factory=list)
    total_lines: int = Field(default=0, ge=0)


class LayerRun(BaseModel):
    capa: str = Field(...)
    status: str = Field(default="unknown")
    run_id: str = Field(...)
    duracion_seg: float | None = Field(default=None)
    records_in: int = Field(default=0, ge=0)
    records_out: int = Field(default=0, ge=0)
    dlq_count: int = Field(default=0, ge=0)
    started_at: str | None = Field(default=None)
    finished_at: str | None = Field(default=None)


class PipelineLayersResponse(BaseModel):
    layers: list[LayerRun] = Field(default_factory=list)
    health_global: str = Field(default="sin datos")
    ultima_corrida_global: str = Field(default="")
