from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql

from lakehouse.db.duckdb_conn import (
    drop_bronze_tables,
    ensure_bronze_table,
    get_connection,
)
from lakehouse.pipeline.scraper import compute_content_hash
from lakehouse.services.enrich_service import EnrichService
from lakehouse.services.parse_service import ParseService

if TYPE_CHECKING:
    import duckdb

    from lakehouse.config import Settings

FIXTURE_SOURCE_PREFIX = "https://fixture.local/"


def _pg_conn_str(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _admin_conn_str(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )


def ensure_verify_database(settings: Settings) -> None:
    """Crea la base de datos objetivo y la extension ``vector`` si no existen.

    Idempotente: usa la base ``postgres`` para crear la base configurada y activa
    ``vector`` en ella. Pensada para la verificacion aislada en contenedor.
    """
    try:
        with psycopg.connect(_admin_conn_str(settings), autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.postgres_db)))
    except psycopg.errors.DuplicateDatabase:
        pass

    with psycopg.connect(_pg_conn_str(settings)) as conn:
        conn.autocommit = True
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def _count(conn: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return row[0] if row else 0


def load_frozen_bronze(conn: duckdb.DuckDBPyConnection, fixture_dir: str) -> list[str]:
    """Inserta el HTML congelado de ``fixture_dir`` en ``bronze.raw_html``.

    La fuente de cada archivo se deriva de forma determinista de su nombre, de modo
    que ``content_hash`` y ``conference_id`` sean reproducibles entre ejecuciones.
    """
    fixture_path = Path(fixture_dir)
    hashes: list[str] = []
    for html_file in sorted(fixture_path.glob("*.html")):
        raw_html = html_file.read_text(encoding="utf-8")
        content_hash = compute_content_hash(raw_html)
        source_url = f"{FIXTURE_SOURCE_PREFIX}{html_file.name}"
        conn.execute(
            """
            INSERT OR IGNORE INTO bronze.raw_html
                (ingestion_run_id, source_url, raw_html, content_hash)
            VALUES (?, ?, ?, ?)
            """,
            ("verify_fixture", source_url, raw_html, content_hash),
        )
        hashes.append(content_hash)
    return hashes


def verify_pipeline(settings: Settings, fixture_dir: str, clean: bool = False) -> dict:
    """Ejecuta Bronze(fixture)→Silver→Gold→clustering→etiquetado y reporta conteos por capa.

    Retorna un dict con los conteos verificables de cada capa. Con ``clean=True`` se
    reinician las tablas de Bronze/Silver/Gold antes de correr (uso en entorno aislado).

    La muestra congelada es pequena, asi que se ajustan los parametros de clustering
    (UMAP/HDBSCAN) a una configuracion de pocos puntos; el default asume corpus grande.
    """
    settings.umap_clustering_n_components = 2
    settings.umap_clustering_n_neighbors = 10
    settings.hdbscan_min_cluster_size = 2
    settings.hdbscan_min_samples = 2

    bronze_conn = get_connection(settings.ducklake_data_path)
    if clean:
        drop_bronze_tables(bronze_conn)
    ensure_bronze_table(bronze_conn)
    load_frozen_bronze(bronze_conn, fixture_dir)
    bronze_count = _count(bronze_conn, "SELECT COUNT(*) FROM bronze.raw_html")
    bronze_conn.close()

    parse_service = ParseService(
        settings=settings,
        duckdb_conn=get_connection(settings.ducklake_data_path),
    )
    parse_service.run(clean=clean)

    silver_conn = get_connection(settings.ducklake_data_path)
    silver_interventions = _count(silver_conn, "SELECT COUNT(*) FROM silver.interventions")
    silver_conferences = _count(silver_conn, "SELECT COUNT(*) FROM silver.conferences")
    silver_dlq = _count(silver_conn, "SELECT COUNT(*) FROM silver.dlq")
    silver_conn.close()

    enrich_service = EnrichService(
        settings=settings,
        duckdb_conn=get_connection(settings.ducklake_data_path),
        pg_conn_str=_pg_conn_str(settings),
    )
    enrich_result = enrich_service.run(
        clean=clean,
        run_gold_enrichment=True,
        run_clustering=True,
        run_semantic_cluster_labeling=True,
    )

    return {
        "bronze": bronze_count,
        "silver_interventions": silver_interventions,
        "silver_conferences": silver_conferences,
        "silver_dlq": silver_dlq,
        "gold_total": enrich_result.total,
        "gold_embedded": enrich_result.embedded,
        "clusters": enrich_result.clustered,
        "noise": enrich_result.noise,
        "labels_completed": enrich_result.clustered_with_labels,
        "labels_failed": enrich_result.failed_to_label,
    }
