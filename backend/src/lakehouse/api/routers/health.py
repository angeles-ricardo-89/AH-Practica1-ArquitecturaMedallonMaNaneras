from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    description="Returns status and version when the API is running",
)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
