import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lakehouse.api.body_limit import BodySizeLimitMiddleware
from lakehouse.api.deps import get_current_user
from lakehouse.api.routers import (
    auth,
    chat,
    clusters,
    config,
    conversations,
    embeddings,
    health,
    observability,
    search,
)
from lakehouse.api.security_headers import SecurityHeadersMiddleware
from lakehouse.config import Settings
from lakehouse.services.demo_users import ensure_demo_users


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = Settings()
    conn_str = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    ensure_demo_users(conn_str, settings.demo_users())
    yield


def create_app(settings: Settings) -> FastAPI:
    docs_kwargs: dict[str, Any] = {}
    if settings.app_env == "production":
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(
        title="Lakehouse Mañaneras API",
        description="API para el pipeline de datos de las conferencias mañaneras",
        version="0.1.0",
        lifespan=lifespan,
        **docs_kwargs,
    )
    app.add_middleware(SecurityHeadersMiddleware, production=settings.app_env == "production")
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)

    protected = [Depends(get_current_user)]

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(search.router, dependencies=protected)
    app.include_router(chat.router, dependencies=protected)
    app.include_router(observability.router, dependencies=protected)
    app.include_router(config.router, dependencies=protected)
    app.include_router(embeddings.router, dependencies=protected)
    app.include_router(clusters.router, dependencies=protected)
    app.include_router(conversations.router, dependencies=protected)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        logging.getLogger("lakehouse").exception("RuntimeError no controlado", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app(Settings())
