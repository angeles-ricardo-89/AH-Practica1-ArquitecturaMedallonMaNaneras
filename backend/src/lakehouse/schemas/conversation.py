from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from lakehouse.schemas.chat import SourceChunk


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=200)


class ConversationCreated(BaseModel):
    id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_activity_at: datetime


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]


class MessageItem(BaseModel):
    role: str
    content: str
    created_at: datetime
    model: str | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    sources: list[SourceChunk] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[MessageItem]


class AgentMessageRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class ToolTraceItem(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_count: int
    duration_ms: int
    status: str


class AgentMessageResponse(BaseModel):
    id: str
    answer: str
    refusal: bool = False
    model_used: str = ""
    tool_executions: list[ToolTraceItem] = Field(default_factory=list)
    sources: list[SourceChunk] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
