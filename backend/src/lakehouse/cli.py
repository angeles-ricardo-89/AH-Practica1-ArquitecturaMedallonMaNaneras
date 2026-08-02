import asyncio
import hashlib
from datetime import UTC, datetime

import psycopg
import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.db.observability_conn import ensure_observability_tables
from lakehouse.log_config import get_logger
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.services.enrich_service import EnrichService
from lakehouse.services.ingest_service import IngestService
from lakehouse.services.parse_service import ParseService

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
                ON CONFLICT (run_id) DO NOTHING""",
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


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
    clean: bool = typer.Option(default=False, help="Drop bronze tables before ingesting"),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        ensure_observability_tables(pg_conn_str)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "bronze", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    try:
        result = asyncio.run(service.run(dry_run=dry_run, max_articles=max_articles, clean=clean))
        if not dry_run:
            records = result.get("records_inserted", 0)
            _write_pipeline_run(
                pg_conn_str, "bronze", "ok", started_at, records_in=records, records_out=records
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "bronze", "error", started_at, error_message=str(e))
        raise
    if dry_run:
        typer.echo(f"Simulacion: {result['html_count']} articulos encontrados")
    else:
        typer.echo(f"Ingesta completada: {result['records_inserted']} registros insertados")


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
        ensure_observability_tables(pg_conn_str)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        _write_pipeline_run(pg_conn_str, "silver", "running", started_at)

    conn = get_connection(settings.ducklake_data_path)
    service = ParseService(settings=settings, duckdb_conn=conn)
    try:
        result = service.run(
            dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers
        )
        if not dry_run:
            _write_pipeline_run(
                pg_conn_str,
                "silver",
                "ok",
                started_at,
                records_in=result.get("interventions", 0),
                records_out=result.get("interventions", 0),
                dlq_count=result.get("dlq", 0),
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "silver", "error", started_at, error_message=str(e))
        raise
    typer.echo(f"Parsing completado: {result['interventions']} intervenciones, {result['dlq']} DLQ")


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(None, "--date", help="Conference date"),
    clean: bool = typer.Option(default=False, help="Drop gold tables before enriching"),
    workers: int = typer.Option(default=1, help="Parallel Ollama embedding workers"),
) -> None:
    settings = Settings()
    pg_conn_str = _get_pg_conn_str(settings)
    if not dry_run:
        ensure_observability_tables(pg_conn_str)
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
        result = service.run(
            dry_run=dry_run, conference_date=conference_date, clean=clean, workers=workers
        )
        if not dry_run:
            _write_pipeline_run(
                pg_conn_str,
                "gold",
                "ok",
                started_at,
                records_in=result.get("total", 0),
                records_out=result.get("embedded", 0),
            )
    except Exception as e:
        if not dry_run:
            _write_pipeline_run(pg_conn_str, "gold", "error", started_at, error_message=str(e))
        raise
    typer.echo(
        f"Enriquecimiento completado: {result['embedded']} incrustados, "
        f"{result['failed']} fallidos de {result['total']} totales"
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
