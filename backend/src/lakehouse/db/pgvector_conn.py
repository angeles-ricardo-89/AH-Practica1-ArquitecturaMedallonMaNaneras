from __future__ import annotations

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="db")


def get_pgvector_connection_string(
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"
