from pathlib import Path

from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.config import ConfigResponse, ModelosConfig
from lakehouse.services.agent.llm import active_chat_model

router = APIRouter(tags=["config"])


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Get application configuration",
    description="Returns environment, version, docker status, and model names",
)
def get_config() -> ConfigResponse:
    settings = Settings()
    embedding = (
        settings.gemini_embedding_model if settings.is_production else settings.ollama_embed_model
    )
    return ConfigResponse(
        ambiente=settings.app_env,
        docker=Path("/.dockerenv").exists(),
        version="0.1.0",
        modelos=ModelosConfig(
            llm=active_chat_model(settings),
            embedding=embedding,
        ),
    )
