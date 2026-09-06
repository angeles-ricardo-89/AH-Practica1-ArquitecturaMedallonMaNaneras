from __future__ import annotations

import psycopg

from lakehouse.db.auth_memory import ensure_auth_memory_tables
from lakehouse.db.index_metadata import ensure_index_metadata_tables
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.db.rate_limit import ensure_rate_limit_tables
from lakehouse.log_config import get_logger
from lakehouse.pipeline.clustering import ensure_clustering_schema
from lakehouse.pipeline.enrichment import ensure_gold_tables

logger = get_logger(__name__, layer="service")


def bootstrap_neon_schema(conn_str: str) -> None:
    """Asegura el esquema minimo que la API productiva requiere (idempotente).

    Crea (si no existen): extension pgvector, corpus gold con indice HNSW,
    columnas/tablas de clustering, tablas de auth/memoria, rate limits,
    metadatos de indice y observabilidad. No toca datos existentes.
    """
    with psycopg.connect(conn_str) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    ensure_gold_tables(conn_str)
    with psycopg.connect(conn_str) as conn:
        ensure_clustering_schema(conn)
    ensure_auth_memory_tables(conn_str)
    ensure_rate_limit_tables(conn_str)
    ensure_index_metadata_tables(conn_str)
    ensure_observability_tables(conn_str)
    logger.info("Esquema productivo asegurado sobre la base de datos objetivo")
