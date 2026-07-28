import hashlib
from datetime import UTC, datetime

import typer

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
from lakehouse.db.merge import (
    ensure_silver_tables,
    insert_dlq_record,
    merge_conference,
    merge_intervention,
)
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import enrich_interventions, ensure_gold_tables
from lakehouse.pipeline.evaluate_rag import evaluate_rag as evaluate_rag_fn
from lakehouse.pipeline.ingestion import Ingestor
from lakehouse.pipeline.parsing import (
    build_conference_record,
    parse_conference_date,
    parse_html_to_interventions,
)
from lakehouse.schemas.silver import DLQRejectRecord, InterventionRecord

logger = get_logger(__name__, layer="cli")
app = typer.Typer()
pipeline_app = typer.Typer()
app.add_typer(pipeline_app, name="pipeline", help="Pipeline commands")


@pipeline_app.command()
def ingest(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    max_articles: int | None = typer.Option(default=None, help="Limit articles to fetch"),
) -> None:
    logger.info(
        "Ejecutando ingesta Bronze",
        dry_run=dry_run,
        max_articles=max_articles,
    )
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
    logger.info("Ingesta Bronze finalizada", **result)


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
    logger.info("Iniciando parseo Silver", html_count=len(rows))
    for source_url, raw_html in rows:
        date = conference_date or parse_conference_date(raw_html, source_url)
        if date is None:
            conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
            dlq = DLQRejectRecord(
                source_record_id=conference_id,
                rejection_reason="unknown_date",
                raw_data=source_url,
            )
            if not dry_run:
                insert_dlq_record(conn, dlq)
            total_dlq += 1
            logger.warning("Fecha desconocida, articulo enviado a DLQ", source_url=source_url)
            continue
        records = parse_html_to_interventions(
            raw_html=raw_html,
            source_url=source_url,
            conference_date=date,
        )
        if not dry_run:
            conference = build_conference_record(
                source_url=source_url,
                conference_date=date,
                raw_html=raw_html,
            )
            merge_conference(conn, conference)
        for record in records:
            if not dry_run:
                if isinstance(record, DLQRejectRecord):
                    logger.warning("Registro rechazado, insertando en DLQ", record=record)
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
    logger.info(
        "Parseo Silver completado",
        interventions=total_interventions,
        dlq=total_dlq,
    )
    typer.echo(f"Parsing completado: {total_interventions} intervenciones, {total_dlq} DLQ")


@pipeline_app.command()
def enrich(
    dry_run: bool = typer.Option(default=False, help="Simulate without writing"),
    conference_date: str | None = typer.Option(None, "--date", help="Conference date"),
) -> None:
    settings = Settings()
    conn = get_connection(settings.ducklake_data_path)
    rows = conn.execute(
        "SELECT i.intervention_key, i.conference_id, i.participant, i.text, i.pregunta_activa, i.chunk_index, i.url "
        "FROM silver.interventions i"
    ).fetchall()
    conn.close()

    interventions = [
        InterventionRecord(
            intervention_key=r[0],
            conference_id=r[1],
            participant=r[2],
            text=r[3],
            pregunta_activa=r[4],
            chunk_index=r[5],
            url=r[6],
        )
        for r in rows
    ]

    if not interventions:
        logger.warning("No hay intervenciones en Silver para enriquecer")
        typer.echo("No hay intervenciones para enriquecer")
        raise typer.Exit(code=0)

    if dry_run:
        logger.info("Simulación: intervenciones listas para Gold", cantidad=len(interventions))
        typer.echo(f"Simulacion: {len(interventions)} intervenciones listas para enriquecer")
        return

    logger.info(
        "Iniciando enriquecimiento Gold desde CLI",
        intervenciones=len(interventions),
        conference_date=conference_date or str(datetime.now(UTC).date()),
    )

    pg_conn_str = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    ensure_gold_tables(pg_conn_str)
    result = enrich_interventions(
        interventions=interventions,
        conference_date=conference_date or str(datetime.now(UTC).date()),
        pg_conn_str=pg_conn_str,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_embed_model,
    )
    typer.echo(
        f"Enriquecimiento completado: {result['embedded']} incrustados, "
        f"{result['failed']} fallidos de {result['total']} totales"
    )


@app.command()
def evaluate_rag() -> None:
    logger.info("Iniciando evaluación RAG (LLM-as-a-Judge)")
    result = evaluate_rag_fn()
    if result.get("status") == "error":
        logger.error("Evaluación RAG falló", message=result.get("message"))
        typer.echo(f"RAG Evaluation failed: {result.get('message', 'unknown error')}")
        raise typer.Exit(code=1)
    logger.info(
        "Evaluación RAG completada",
        total=result["total"],
        fidelidad=result["avg_fidelity"],
        relevancia=result["avg_relevance"],
    )
    typer.echo(
        f"RAG Evaluation: {result['total']} preguntas, "
        f"fidelidad={result['avg_fidelity']}%, "
        f"relevancia={result['avg_relevance']}%"
    )
