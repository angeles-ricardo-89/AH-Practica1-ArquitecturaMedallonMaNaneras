import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
from lakehouse.db.connection import get_database_url
from lakehouse.services.demo_users import ensure_demo_users
from lakehouse.services.index_metadata import validate_index_at_startup


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = Settings()
    conn_str = get_database_url(settings)
    ensure_demo_users(conn_str, settings.demo_users())
    validate_index_at_startup(settings)
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
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, production=settings.app_env == "production")

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

    _mount_frontend_static(app, settings)

    return app


def _mount_frontend_static(app: FastAPI, settings: Settings) -> None:
    """Sirve el build del frontend bajo el mismo origen cuando hay dist (produccion).

    Build unico web+API: los routers ya registrados tienen prioridad sobre el
    fallback SPA, de modo que los endpoints de la API no se ven afectados.
    """
    dist = Path(settings.frontend_dist_dir) if settings.frontend_dist_dir else None
    if dist is None or not dist.is_dir():
        return
    index_file = dist / "index.html"
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        accept = request.headers.get("accept", "")
        if "text/html" not in accept:
            raise HTTPException(status_code=404)
        return FileResponse(index_file)


app = create_app(Settings())
