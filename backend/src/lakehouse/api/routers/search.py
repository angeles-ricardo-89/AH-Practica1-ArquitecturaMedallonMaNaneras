from fastapi import APIRouter, Depends

from lakehouse.api.deps import SearchService, get_search_service
from lakehouse.schemas.search import SearchRequest, SearchResponse

router = APIRouter(tags=["search"])


@router.post(
    "/search/",
    response_model=SearchResponse,
    summary="Semantic search",
    description="Search the RAG corpus for relevant chunks",
)
async def search(
    request: SearchRequest,
    search_service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    results, total = await search_service.search(
        query=request.query,
        top_k=request.top_k,
        strategy=request.strategy,
        filters=request.filters,
    )
    return SearchResponse(
        results=results,
        total=total,
        strategy=request.strategy,
    )
