from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class ConferenceRecord(BaseModel):
    conference_id: str = Field(..., min_length=1)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(...)
    url: str = Field(..., min_length=1)

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InterventionRecord(BaseModel):
    intervention_key: str = Field(..., min_length=1)
    conference_id: str = Field(..., min_length=1)
    participant: str = Field(default="DESCONOCIDO")
    text: str = Field(...)
    pregunta_activa: str = Field(default="")
    chunk_index: int = Field(..., ge=0)
    url: str = Field(default="")

    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def parent_key(self) -> str:
        return (
            self.intervention_key.rsplit("_", 2)[0]
            if self.intervention_key.count("_") >= 2
            else self.intervention_key
        )

    @field_validator("participant")
    @classmethod
    def uppercase_participant(cls, v: str) -> str:
        return v.strip().upper() if v else "DESCONOCIDO"


class DLQRejectRecord(BaseModel):
    source_record_id: str = Field(..., min_length=1)
    rejection_reason: str = Field(..., min_length=1)
    raw_data: str = Field(..., min_length=1)

    rejected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
