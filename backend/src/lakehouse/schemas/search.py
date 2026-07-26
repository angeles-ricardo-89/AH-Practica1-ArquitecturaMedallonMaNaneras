from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)
    filters: dict[str, str] | None = Field(default=None)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @model_validator(mode="before")
    @classmethod
    def reject_extra_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            allowed = {"query", "top_k", "filters"}
            extra = set(data) - allowed
            if extra:
                raise ValueError(f"Extra fields not allowed: {extra}")
        return data


class SearchResponse(BaseModel):
    results: list[dict] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    strategy: str = Field(default="hnsw")
