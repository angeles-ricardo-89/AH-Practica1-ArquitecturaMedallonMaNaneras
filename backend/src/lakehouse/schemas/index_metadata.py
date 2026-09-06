from __future__ import annotations

from pydantic import BaseModel


class IndexMetadata(BaseModel):
    provider: str
    model: str
    dimension: int
    task_type: str
    format_version: str
    built_at: str
    corpus_hash: str
