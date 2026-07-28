from datetime import UTC, datetime

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import enrich_interventions, ensure_gold_tables
from lakehouse.schemas.silver import InterventionRecord


class EnrichService:
    def __init__(self, settings: Settings, duckdb_conn, pg_conn_str: str):
        self._settings = settings
        self._conn = duckdb_conn
        self._pg_conn_str = pg_conn_str
        self._logger = get_logger(__name__, layer="service")

    def run(self, dry_run: bool = False, conference_date: str | None = None) -> dict:
        rows = self._conn.execute(
            "SELECT intervention_key, conference_id, participant, text, "
            "pregunta_activa, chunk_index, url "
            "FROM silver.interventions"
        ).fetchall()
        self._conn.close()

        interventions = [
            InterventionRecord(
                intervention_key=r[0], conference_id=r[1], participant=r[2],
                text=r[3], pregunta_activa=r[4], chunk_index=r[5], url=r[6],
            )
            for r in rows
        ]

        if not interventions:
            self._logger.warning("No hay intervenciones en Silver para enriquecer")
            return {"embedded": 0, "failed": 0, "total": 0}

        if dry_run:
            self._logger.info(
                "Simulacion: intervenciones listas para Gold", cantidad=len(interventions),
            )
            return {"embedded": 0, "failed": 0, "total": len(interventions)}

        date = conference_date or str(datetime.now(UTC).date())
        self._logger.info(
            "Iniciando enriquecimiento Gold",
            intervenciones=len(interventions), conference_date=date,
        )
        ensure_gold_tables(self._pg_conn_str)
        result = enrich_interventions(
            interventions=interventions,
            conference_date=date,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
        )
        return result
