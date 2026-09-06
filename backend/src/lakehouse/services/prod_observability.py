from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg

from lakehouse.db.connection import get_database_url
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.db.pgvector_conn import build_neon_connection_string
from lakehouse.log_config import get_logger

if TYPE_CHECKING:
    from lakehouse.config import Settings

logger = get_logger(__name__, layer="service")

_COLS = (
    "run_id, capa, status, started_at, finished_at, "
    "records_in, records_out, dlq_count, error_message"
)


def sync_production_observability(settings: Settings) -> dict[str, int]:
    """Replica las corridas del pipeline (observability.pipeline_runs) a produccion.

    Copia las corridas registradas en el Postgres local hacia Neon para que el
    dashboard productivo muestre el estado real del medallon. Idempotente por
    run_id (upsert).
    """
    if not settings.neon_database_url:
        raise RuntimeError("NEON_DATABASE_URL es obligatorio para sincronizar observabilidad")
    source_conn_str = get_database_url(settings)
    target_conn_str = build_neon_connection_string(settings.neon_database_url)

    ensure_observability_tables(target_conn_str)

    with psycopg.connect(source_conn_str) as src:
        rows = src.execute(f"SELECT {_COLS} FROM observability.pipeline_runs").fetchall()

    if not rows:
        logger.info("observabilidad_sin_corridas_locales")
        return {"copied": 0}

    upsert = f"""
        INSERT INTO observability.pipeline_runs ({_COLS})
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id) DO UPDATE SET
            capa = EXCLUDED.capa,
            status = EXCLUDED.status,
            started_at = EXCLUDED.started_at,
            finished_at = EXCLUDED.finished_at,
            records_in = EXCLUDED.records_in,
            records_out = EXCLUDED.records_out,
            dlq_count = EXCLUDED.dlq_count,
            error_message = EXCLUDED.error_message
    """
    with psycopg.connect(target_conn_str) as conn:
        cur = conn.cursor()
        for row in rows:
            cur.execute(upsert, row)
        conn.commit()

    logger.info("observabilidad_sincronizada", corridas=len(rows))
    return {"copied": len(rows)}
