from pydantic import BaseModel, Field


class PipelineStatus(BaseModel):
    status: str = Field(default="unknown")
    last_run: str = Field(default="")
    last_success: str = Field(default="")
    records_count: int = Field(default=0, ge=0)


class PipelineLogs(BaseModel):
    lines: list[str] = Field(default_factory=list)
    total_lines: int = Field(default=0, ge=0)
