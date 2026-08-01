from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import (
    drop_gold_tables,
    enrich_interventions,
    ensure_gold_tables,
)
from lakehouse.schemas.silver import InterventionRecord


class EnrichService:
    def __init__(self, settings: Settings, duckdb_conn, pg_conn_str: str) -> None:
        self._settings = settings
        self._conn = duckdb_conn
        self._pg_conn_str = pg_conn_str
        self._logger = get_logger(__name__, layer="service")

    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
        clean: bool = False,
        workers: int = 1,
    ) -> dict:
        rows = self._conn.execute(
            """
            SELECT i.intervention_key, i.conference_id, i.participant, i.text,
                   i.pregunta_activa, i.chunk_index, i.url, c.date AS conference_date
            FROM silver.interventions i
            LEFT JOIN silver.conferences c ON c.conference_id = i.conference_id
            """
        ).fetchall()
        self._conn.close()

        interventions = [
            InterventionRecord(
                intervention_key=r[0],
                conference_id=r[1],
                participant=r[2],
                text=r[3],
                pregunta_activa=r[4],
                chunk_index=r[5],
                url=r[6],
                conference_date=r[7],
            )
            for r in rows
        ]

        if not interventions:
            self._logger.warning("No hay intervenciones en Silver para enriquecer")
            return {"embedded": 0, "failed": 0, "total": 0}

        if clean:
            if dry_run:
                self._logger.warning("--clean es ignorado en dry-run")
            else:
                drop_gold_tables(self._pg_conn_str)

        if dry_run:
            self._logger.info(
                "Simulacion: intervenciones listas para Gold",
                cantidad=len(interventions),
            )
            return {"embedded": 0, "failed": 0, "total": len(interventions)}

        self._logger.info(
            "Iniciando enriquecimiento Gold",
            intervenciones=len(interventions),
            conference_date=conference_date,
        )
        ensure_gold_tables(self._pg_conn_str)
        return enrich_interventions(
            interventions=interventions,
            conference_date=conference_date,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
            workers=workers,
        )
