import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class IngestionManifest(BaseModel):
    run_id: str = Field(..., min_length=1, description="Unique ingestion run ID")
    source_url: str = Field(..., description="Source URL ingested")
    html_count: int = Field(..., ge=0, description="Number of HTML pages ingested")
    status: str = Field(default="pending", description="Ingestion status")

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BronzeRecord(BaseModel):
    ingestion_run_id: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    raw_html: str = Field(..., min_length=1)
    content_hash: str = Field(..., min_length=64, max_length=64)

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("content_hash")
    @classmethod
    def must_be_hex(cls, v: str) -> str:
        if not re.match(r"^[0-9a-f]{64}$", v):
            raise ValueError("content_hash must be a 64-character hex string")
        return v
