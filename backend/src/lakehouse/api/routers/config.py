from pathlib import Path

from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.config import ConfigResponse, ModelosConfig

router = APIRouter(tags=["config"])


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Get application configuration",
    description="Returns environment, version, docker status, and model names",
)
def get_config() -> ConfigResponse:
    settings = Settings()
    return ConfigResponse(
        ambiente=settings.app_env,
        docker=Path("/.dockerenv").exists(),
        version="0.1.0",
        modelos=ModelosConfig(
            llm=settings.llamacpp_model,
            embedding=settings.ollama_embed_model,
        ),
    )
