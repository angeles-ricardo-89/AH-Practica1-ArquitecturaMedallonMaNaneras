from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    conversation_id: str | None = Field(default=None)
    top_k: int = Field(default=8, ge=1, le=50)


class SourceChunk(BaseModel):
    conference_date: str = Field(...)
    conference_id: str = Field(..., min_length=1)
    participant: str = Field(...)
    chunk_text: str = Field(...)
    similarity: float = Field(..., ge=0.0, le=1.0)
    conference_url: str = Field(default="")
    pregunta_activa: str = Field(default="")
    qualitative_label: str = Field(default="Media")
    embedding_3d: list[float] | None = Field(default=None)


class ChatResponse(BaseModel):
    answer: str = Field(...)
    sources: list[SourceChunk] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    model_used: str = Field(default="")
    latency_ms: float = Field(default=0.0)
