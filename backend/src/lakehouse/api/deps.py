from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from lakehouse.config import Settings
from lakehouse.services.rag_search import search_gold_corpus


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
        _ = strategy
        results = search_gold_corpus(query, top_k)
        if filters:
            filtered = []
            for r in results:
                match = True
                for key, val in filters.items():
                    if key in r and str(r[key]) != val:
                        match = False
                        break
                if match:
                    filtered.append(r)
            results = filtered
        return results, len(results)


async def get_search_service() -> AsyncIterator[SearchService]:
    yield SearchService()
