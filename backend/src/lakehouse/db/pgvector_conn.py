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


def build_neon_connection_string(database_url: str) -> str:
    if "-pooler" not in database_url:
        raise ValueError(
            "Neon production connection requires a pooled endpoint (host containing '-pooler')"
        )
    if "sslmode=require" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"
    return database_url
