import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.log_config import get_logger
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.services.enrich_service import EnrichService
from lakehouse.services.ingest_service import IngestService
from lakehouse.services.parse_service import ParseService

logger = get_logger(__name__, layer="cli")
app = typer.Typer()
pipeline_app = typer.Typer()
app.add_typer(pipeline_app, name="pipeline", help="Pipeline commands")


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    service = IngestService(settings=settings, duckdb_conn=conn)
    result = service.run(dry_run=dry_run, max_articles=max_articles)
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
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    service = ParseService(settings=settings, duckdb_conn=conn)
    result = service.run(dry_run=dry_run, conference_date=conference_date)
    typer.echo(
        f"Parsing completado: {result['interventions']} intervenciones, {result['dlq']} DLQ"
    )


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(None, "--date", help="Conference date"),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    pg_conn_str = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    service = EnrichService(
        settings=settings, duckdb_conn=conn, pg_conn_str=pg_conn_str,
    )
    result = service.run(dry_run=dry_run, conference_date=conference_date)
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
    )
    typer.echo(
        f"RAG Evaluation: {result['total']} preguntas, "
        f"fidelidad={result['avg_fidelity']}%, "
        f"relevancia={result['avg_relevance']}%"
    )

if __name__ == "__main__":
    app()
