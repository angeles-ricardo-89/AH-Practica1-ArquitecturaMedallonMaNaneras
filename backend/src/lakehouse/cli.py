import asyncio
import hashlib
from datetime import UTC, datetime

import psycopg
import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.db.pgvector_conn import build_neon_connection_string
from lakehouse.log_config import get_logger
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.pipeline.interrupt import install_graceful_interrupt, interrupt_state
from lakehouse.pipeline.verify import ensure_verify_database, verify_pipeline
from lakehouse.services.enrich_service import EnrichService
from lakehouse.services.gemini_embedding import (
    RETRIEVAL_DOCUMENT,
    GeminiEmbeddingAdapter,
)
from lakehouse.services.index_metadata import GOOGLE_PROVIDER
from lakehouse.services.ingest_service import IngestService
from lakehouse.services.neon_bootstrap import bootstrap_neon_schema
from lakehouse.services.parse_service import ParseService
from lakehouse.services.prod_visuals import sync_production_visuals as run_sync_visuals
from lakehouse.services.reindex_production import reindex_corpus

logger = get_logger(__name__, layer="cli")
app = typer.Typer()
pipeline_app = typer.Typer()
app.add_typer(pipeline_app, name="pipeline", help="Pipeline commands")


def _get_pg_conn_str(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _write_pipeline_run(
    pg_conn_str: str,
    capa: str,
    status: str,
    started_at: str,
    records_in: int = 0,
    records_out: int = 0,
    dlq_count: int = 0,
    error_message: str | None = None,
) -> None:
    run_id = hashlib.sha256(f"{capa}:{started_at}".encode()).hexdigest()
    finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with psycopg.connect(pg_conn_str) as conn:
            conn.execute(
                """INSERT INTO observability.pipeline_runs
                (run_id, capa, status, started_at, finished_at, records_in, records_out, dlq_count, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    records_in = EXCLUDED.records_in,
                    records_out = EXCLUDED.records_out,
                    dlq_count = EXCLUDED.dlq_count,
                    error_message = EXCLUDED.error_message""",
                (
                    run_id,
                    capa,
                    status,
                    started_at,
                    finished_at,
                    records_in,
                    records_out,
                    dlq_count,
                    error_message,
                ),
            )
            conn.commit()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo escribir pipeline_run", capa=capa, run_id=run_id)


def _write_final_run(
    pg_conn_str: str,
    capa: str,
    started_at: str,
    dry_run: bool,
    *,
    records_in: int,
    records_out: int,
    dlq_count: int = 0,
) -> None:
    """Escribe el estado final de la corrida: 'interrupted' si hubo senal, si no 'ok'."""
    if interrupt_state.requested():
        if not dry_run:
            _write_pipeline_run(
                pg_conn_str,
                capa,
                "interrupted",
                started_at,
                records_in=records_in,
                records_out=records_out,
                dlq_count=dlq_count,
            )
        typer.echo("Pipeline interrumpido")
        raise typer.Exit(code=130)
    if not dry_run:
        _write_pipeline_run(
            pg_conn_str,
            capa,
            "ok",
            started_at,
            records_in=records_in,
            records_out=records_out,
            dlq_count=dlq_count,
        )


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
    clean: bool = typer.Option(default=False, help="Drop bronze tables before ingesting"),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="bronze"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "bronze", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    try:
        with install_graceful_interrupt():
            result = asyncio.run(
                service.run(dry_run=dry_run, max_articles=max_articles, clean=clean)
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "bronze", "error", started_at, error_message=str(e))
        raise

    records = result.get("records_inserted", 0)
    _write_final_run(
        pg_conn_str,
        "bronze",
        started_at,
        dry_run,
        records_in=records,
        records_out=records,
    )
    if dry_run:
        typer.echo(f"Simulacion: {result['html_count']} articulos encontrados")
    else:
        typer.echo(f"Ingesta completada: {records} registros insertados")


@pipeline_app.command()
def parse(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(
        None, "--date", help="Conference date (default: from data)"
    ),
    clean: bool = typer.Option(default=False, help="Drop silver tables before parsing"),
    workers: int = typer.Option(default=1, help="Parallel parse workers (ProcessPoolExecutor)"),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="silver"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "silver", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = ParseService(settings=settings, duckdb_conn=conn)
    try:
        with install_graceful_interrupt():
            result = service.run(
                dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "silver", "error", started_at, error_message=str(e))
        raise

    interventions = result.get("interventions", 0)
    _write_final_run(
        pg_conn_str,
        "silver",
        started_at,
        dry_run,
        records_in=interventions,
        records_out=interventions,
        dlq_count=result.get("dlq", 0),
    )
    typer.echo(f"Parsing completado: {result['interventions']} intervenciones, {result['dlq']} DLQ")


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(None, "--date", help="Conference date"),
    clean: bool = typer.Option(default=False, help="Drop gold tables before enriching"),
    workers: int = typer.Option(default=1, help="Parallel Ollama embedding workers"),
    run_clustering: bool = typer.Option(
        default=False,
        help="Fuerza re-clusterizacion semantica (UMAP+HDBSCAN) sobre el corpus",
    ),
    run_semantic_cluster_labeling: bool = typer.Option(
        default=False,
        help="Ejecuta autoetiquetado LLM sobre clusters existentes de la ultima corrida",
    ),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        try:
            ensure_observability_tables(pg_conn_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "No se pudo inicializar observability, continuando sin tracking", capa="gold"
            )
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "gold", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = EnrichService(
        settings=settings,
        duckdb_conn=conn,
        pg_conn_str=pg_conn_str,
    )
    try:
        with install_graceful_interrupt():
            run_gold_enrichment = not run_clustering and not run_semantic_cluster_labeling
            if run_gold_enrichment:
                run_clustering = True
            if run_clustering:
                run_semantic_cluster_labeling = True

            result = service.run(
                dry_run=dry_run,
                conference_date=conference_date,
                clean=clean,
                workers=workers,
                run_gold_enrichment=run_gold_enrichment,
                run_clustering=run_clustering,
                run_semantic_cluster_labeling=run_semantic_cluster_labeling,
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "gold", "error", started_at, error_message=str(e))
        raise

    _write_final_run(
        pg_conn_str,
        "gold",
        started_at,
        dry_run,
        records_in=result.total,
        records_out=result.embedded,
    )
    typer.echo(
        f"Enriquecimiento completado: {result.embedded} incrustados, {result.failed_to_embed} fallidos, {result.mapped_3d} mapeados 3D, {result.failed_to_map} fallidos, {result.clustered} clusterizados, {result.noise} ruido, {result.clusters} clusters, {result.clustered_with_labels} clusterizados con etiquetas, {result.failed_to_label} fallidos, "
        f"{result.failed} fallidos de {result.total} totales"
    )


@pipeline_app.command()
def verify(
    fixture_dir: str = typer.Option(
        "tests/fixtures/bronze",
        "--fixture-dir",
        help="Directorio con la muestra Bronze congelada (HTML gob.mx)",
    ),
    clean: bool = typer.Option(
        default=False, help="Reinicia Bronze/Silver/Gold antes de verificar"
    ),
) -> None:
    settings = Settings()
    ensure_verify_database(settings)
    result = verify_pipeline(settings, fixture_dir, clean=clean)
    typer.echo("Verificacion del pipeline (Bronze→Silver→Gold→clustering→etiquetado):")
    typer.echo(f"  Bronze: {result['bronze']} registros")
    typer.echo(
        f"  Silver: {result['silver_conferences']} conferencias, "
        f"{result['silver_interventions']} intervenciones, {result['silver_dlq']} DLQ"
    )
    typer.echo(f"  Gold: {result['gold_embedded']}/{result['gold_total']} embeddings")
    typer.echo(f"  Clustering: {result['clusters']} clusters, {result['noise']} ruido")
    typer.echo(
        f"  Etiquetado: {result['labels_completed']} completados, "
        f"{result['labels_failed']} fallidos"
    )


@pipeline_app.command()
def reindex_production(
    source_table: str = typer.Option(
        "gold.rag_corpus",
        "--source-table",
        help="Tabla Gold local de origen (fuente de la reindexacion)",
    ),
    batch_size: int = typer.Option(
        default=16,
        help="Tamano de lote para embeddings Gemini",
    ),
) -> None:
    """Re-embebe el corpus local con Gemini hacia la base Neon productiva.

    Prepara el esquema objetivo (bootstrap idempotente) y reindexa TODOS los
    chunks hacia un indice independiente, registrando los metadatos del indice.
    """
    settings = Settings()
    if not settings.neon_database_url:
        raise typer.BadParameter(
            "NEON_DATABASE_URL es obligatorio (Secret Manager o env) para reindexar a produccion"
        )
    source_conn_str = _get_pg_conn_str(settings)
    target_conn_str = build_neon_connection_string(settings.neon_database_url)

    logger.info(
        "Preparando esquema productivo en Neon",
        target=target_conn_str.split("@")[-1],
    )
    bootstrap_neon_schema(target_conn_str)

    adapter = GeminiEmbeddingAdapter(
        settings.gemini_api_key,
        settings.gemini_embedding_model,
        settings.gemini_embedding_dimension,
    )
    logger.info(
        "Reindexando corpus a produccion",
        source=source_table,
        target=source_table,
        model=settings.gemini_embedding_model,
        dimension=settings.gemini_embedding_dimension,
    )
    result = reindex_corpus(
        source_conn_str=source_conn_str,
        target_conn_str=target_conn_str,
        embed_documents=adapter.embed_documents,
        provider=GOOGLE_PROVIDER,
        model=settings.gemini_embedding_model,
        dimension=settings.gemini_embedding_dimension,
        task_type=RETRIEVAL_DOCUMENT,
        format_version=settings.index_format_version,
        source_table=source_table,
        target_table=source_table,
        batch_size=batch_size,
    )
    typer.echo(
        f"Reindexacion productiva completada: {result['embedded']}/{result['total']} "
        f"embeddings reindexados"
    )


@pipeline_app.command(name="sync-production-visuals")
def sync_visuals_cmd() -> None:
    """Recalcula embedding_3d y clusters sobre los embeddings Gemini de Neon.

    Ejecuta UMAP-3D + UMAP/HDBSCAN + etiquetado contra el indice productivo
    (Neon) y escribe los resultados de vuelta en Neon. No toca el entorno local.
    """
    settings = Settings()
    result = run_sync_visuals(settings)
    typer.echo(
        f"Visuales productivas sincronizadas: embedding_3d {result['embedding_3d_updated']} "
        f"filas, run {result['run_id']}, {result['clusters']} clusters, "
        f"etiquetado={result['labeling']}"
    )


@app.command()
def evaluate_rag() -> None:
    logger.info("Iniciando evaluacion RAG (LLM-as-a-Judge)")
    result = evaluate_rag_fn()
    if result.get("status") == "error":
        logger.error("Evaluacion RAG fallo", message=result.get("message"))
        typer.echo(f"RAG Evaluation failed: {result.get('message', 'unknown error')}")
        raise typer.Exit(code=1)
    logger.info(
        "Evaluacion RAG completada",
        total=result["total"],
        fidelidad=result["avg_fidelity"],
        relevancia=result["avg_relevance"],
        cobertura=result.get("avg_coverage", 0),
    )
    typer.echo(
        f"RAG Evaluation: {result['total']} preguntas, "
        f"fidelidad={result['avg_fidelity']}%, "
        f"relevancia={result['avg_relevance']}%, "
        f"cobertura={result.get('avg_coverage', 0)}%"
    )


if __name__ == "__main__":
    app()
