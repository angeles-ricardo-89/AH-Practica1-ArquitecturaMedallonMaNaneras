import psycopg
from fastapi import APIRouter, Query

from lakehouse.config import Settings
from lakehouse.schemas.observability import (
    LayerRun,
    PipelineLayersResponse,
    PipelineLogs,
    PipelineStatus,
)
from lakehouse.services.log_reader import count_log_lines, read_log
from lakehouse.services.status_writer import read_status

LOG_FILE_PATH = "data/lakehouse/logs/pipeline.log"
STATUS_FILE_PATH = "data/lakehouse/logs/cron.status"

router = APIRouter(prefix="/observability", tags=["observability"])

SEMAPHORE_COLORS: dict[str, str] = {
    "ok": "green",
    "running": "yellow",
    "error": "red",
}


def _get_pg_conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@router.get(
    "/status",
    response_model=PipelineStatus,
    summary="Get pipeline status",
    description="Returns the current pipeline status including semaphore color",
)
def get_status() -> PipelineStatus:
    data = read_status(STATUS_FILE_PATH)
    status = data.get("status", "unknown")
    return PipelineStatus(
        status=status,
        last_run=data.get("last_run", ""),
        last_success=data.get("last_success", ""),
        records_count=data.get("records_count", 0),
        semaphore=SEMAPHORE_COLORS.get(status, "gray"),
    )


@router.get(
    "/logs",
    response_model=PipelineLogs,
    summary="Get pipeline logs",
    description="Returns the last N lines of the pipeline log file",
)
def get_logs(lines: int = Query(50, ge=1, le=500)) -> PipelineLogs:
    log_lines = read_log(LOG_FILE_PATH, lines=lines)
    total = count_log_lines(LOG_FILE_PATH)
    return PipelineLogs(lines=log_lines, total_lines=total)


@router.get(
    "/pipeline/layers",
    response_model=PipelineLayersResponse,
    summary="Get pipeline status per layer",
    description="Returns the latest run for each medallion layer (bronze, silver, gold)",
)
def get_pipeline_layers() -> PipelineLayersResponse:
    conn_str = _get_pg_conn_str()
    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT ON (capa)
                    capa, status, run_id,
                    EXTRACT(EPOCH FROM (finished_at - started_at)) AS duracion_seg,
                    records_in, records_out, dlq_count,
                    started_at, finished_at
                FROM observability.pipeline_runs
                ORDER BY capa, started_at DESC
            """)
            rows = cur.fetchall()
    except (psycopg.Error, OSError):
        return PipelineLayersResponse(
            layers=[],
            health_global="sin datos",
            ultima_corrida_global="",
        )

    layers = []
    latest_global = ""
    for row in rows:
        started = row[7]
        finished = row[8]
        layers.append(
            LayerRun(
                capa=row[0],
                status=row[1] if row[1] else "unknown",
                run_id=row[2],
                duracion_seg=float(row[3]) if row[3] is not None else None,
                records_in=row[4] or 0,
                records_out=row[5] or 0,
                dlq_count=row[6] or 0,
                started_at=started.isoformat() if started else None,
                finished_at=finished.isoformat() if finished else None,
            )
        )
        if started and str(started) > latest_global:
            latest_global = str(started)

    statuses = {layer.status for layer in layers}
    if not statuses:
        health = "sin datos"
    elif "error" in statuses:
        health = "Failed"
    elif "running" in statuses:
        health = "Degraded"
    elif statuses == {"ok"} and len(layers) == 3:
        health = "Healthy"
    else:
        health = "Degraded"

    return PipelineLayersResponse(
        layers=layers,
        health_global=health,
        ultima_corrida_global=latest_global,
    )
