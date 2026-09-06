from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import psycopg

from lakehouse.db.pgvector_conn import build_neon_connection_string

if TYPE_CHECKING:
    from lakehouse.config import Settings


def get_database_url(settings: Settings) -> str:
    """Devuelve la URL de la capa de datos segun entorno.

    Produccion: exige ``neon_database_url`` y aplica TLS sobre el endpoint
    agrupado (``-pooler``); falla cerrado si falta o no es agrupado.
    Local/docker: URL postgres local construida desde ``postgres_*``.
    """
    if settings.is_production:
        if not settings.neon_database_url:
            raise RuntimeError("neon_database_url es obligatorio en produccion")
        return build_neon_connection_string(settings.neon_database_url)
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _is_pooled(conn_str: str) -> bool:
    """True si el endpoint es un pooler (Neon -pooler) que rechaza startup options."""
    return "-pooler" in conn_str


def pg_connect(
    conn_str: str,
    *,
    connect_timeout: int,
    statement_timeout_ms: int,
) -> psycopg.Connection:
    if _is_pooled(conn_str):
        return psycopg.connect(conn_str, connect_timeout=connect_timeout)
    return psycopg.connect(
        conn_str,
        connect_timeout=connect_timeout,
        options=f"-c statement_timeout={statement_timeout_ms}",
    )


def pg_conn_str_with_timeouts(
    conn_str: str,
    *,
    connect_timeout: int,
    statement_timeout_ms: int,
) -> str:
    if _is_pooled(conn_str):
        return f"{conn_str}{'&' if '?' in conn_str else '?'}connect_timeout={connect_timeout}"
    options = quote(f"-c statement_timeout={statement_timeout_ms}")
    params = f"connect_timeout={connect_timeout}&options={options}"
    separator = "&" if "?" in conn_str else "?"
    return f"{conn_str}{separator}{params}"
