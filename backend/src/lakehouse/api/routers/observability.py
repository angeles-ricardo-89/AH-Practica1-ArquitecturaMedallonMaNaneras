from fastapi import APIRouter, Query

from lakehouse.schemas.observability import PipelineLogs, PipelineStatus
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
