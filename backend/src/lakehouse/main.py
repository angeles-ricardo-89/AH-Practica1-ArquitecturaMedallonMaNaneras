from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lakehouse.api.routers import chat, clusters, config, embeddings, health, observability, search


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield


app = FastAPI(
    title="Lakehouse Mañaneras API",
    description="API para el pipeline de datos de las conferencias mañaneras",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(observability.router)
app.include_router(config.router)
app.include_router(embeddings.router)
app.include_router(clusters.router)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
    )
