from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from lakehouse.config import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


class SearchService:
    async def search(
        self,
        query: str = "",
        top_k: int = 8,
        strategy: str = "hnsw",
        filters: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        _ = (query, top_k, strategy, filters)
        return [], 0


async def get_search_service() -> AsyncIterator[SearchService]:
    yield SearchService()
