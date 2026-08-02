from pydantic import BaseModel, Field


class Embedding3DPoint(BaseModel):
    chunk_key: str = Field(...)
    x: float = Field(...)
    y: float = Field(...)
    z: float = Field(...)
    conference_date: str = Field(...)


class Embedding3DResponse(BaseModel):
    points: list[Embedding3DPoint] = Field(default_factory=list)
