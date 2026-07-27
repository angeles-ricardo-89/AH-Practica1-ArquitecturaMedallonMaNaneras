import logging

import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.db.merge import ensure_silver_tables, insert_dlq_record, merge_intervention
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.pipeline.ingestion import Ingestor
from lakehouse.pipeline.parsing import parse_html_to_interventions
from lakehouse.schemas.silver import DLQRejectRecord

logger = logging.getLogger(__name__)
app = typer.Typer()
pipeline_app = typer.Typer()
app.add_typer(pipeline_app, name="pipeline", help="Pipeline commands")


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
) -> None:
    settings = Settings()
    ingestor = Ingestor(
        db_path=settings.ducklake_data_path,
        source_archive_url=settings.source_archive_url,
        max_articles=max_articles,
    )
    result = ingestor.run(dry_run=dry_run)
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
    if not dry_run:
        ensure_silver_tables(conn)
    rows = conn.execute("SELECT source_url, raw_html FROM bronze.raw_html").fetchall()
    total_interventions = 0
    total_dlq = 0
    for source_url, raw_html in rows:
        date = conference_date or "desconocida"
        records = parse_html_to_interventions(
            raw_html=raw_html,
            source_url=source_url,
            conference_date=date,
        )
        for record in records:
            if not dry_run:
                if isinstance(record, DLQRejectRecord):
                    insert_dlq_record(conn, record)
                    total_dlq += 1
                else:
                    merge_intervention(conn, record)
                    total_interventions += 1
            elif isinstance(record, DLQRejectRecord):
                total_dlq += 1
            else:
                total_interventions += 1
    conn.close()
    typer.echo(f"Parsing completado: {total_interventions} intervenciones, {total_dlq} DLQ")


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
) -> None:
    if dry_run:
        typer.echo("Simulacion: enriquecimiento pendiente de implementar")
    else:
        typer.echo("Enriquecimiento pendiente de implementar")


@app.command()
def evaluate_rag() -> None:
    result = evaluate_rag_fn()
    if result.get("status") == "error":
        typer.echo(f"RAG Evaluation failed: {result.get('message', 'unknown error')}")
        raise typer.Exit(code=1)
    typer.echo(
        f"RAG Evaluation: {result['total']} preguntas, "
        f"fidelidad={result['avg_fidelity']}%, "
        f"relevancia={result['avg_relevance']}%"
    )
