from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RagCorpusRecord(BaseModel):
    chunk_key: str = Field(..., min_length=1)
    conference_id: str = Field(..., min_length=1)
    conference_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    participant: str = Field(...)
    chunk_text: str = Field(..., min_length=1)
    payload: str = Field(...)
    url: str = Field(default="")
    embedding: list[float] | None = Field(default=None)

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WindowRecord(BaseModel):
    chunk_key: str = Field(..., min_length=1)
    conference_id: str = Field(..., min_length=1)
    conference_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    participant: str = Field(default="DESCONOCIDO")
    pregunta_activa: str = Field(default="")
    text: str = Field(..., min_length=1)
    url: str = Field(default="")
    window_index: int = Field(..., ge=0)
