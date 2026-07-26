from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RagCorpusRecord(BaseModel):
    chunk_key: str = Field(..., min_length=1)
    conference_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    participant: str = Field(...)
    chunk_text: str = Field(..., min_length=1)
    payload: str = Field(...)
    embedding: list[float] | None = Field(default=None)

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
