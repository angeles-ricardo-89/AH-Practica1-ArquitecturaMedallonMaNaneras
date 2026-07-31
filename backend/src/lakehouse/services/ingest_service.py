import asyncio

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import drop_bronze_tables, ensure_bronze_table
from lakehouse.log_config import get_logger
from lakehouse.pipeline.ingestion import Ingestor


class IngestService:
    def __init__(self, settings: Settings, duckdb_conn) -> None:
        self._settings = settings
        self._conn = duckdb_conn
        self._logger = get_logger(__name__, layer="service")

    async def run(
        self,
        dry_run: bool = False,
        max_articles: int | None = None,
        clean: bool = False,
    ) -> dict:
        self._logger.info("Ejecutando ingesta Bronze", dry_run=dry_run, clean=clean)
        if clean:
            if dry_run:
                self._logger.warning("--clean es ignorado en dry-run")
            else:
                await asyncio.to_thread(drop_bronze_tables, self._conn)
        if not dry_run:
            await asyncio.to_thread(ensure_bronze_table, self._conn)

        ingestor = Ingestor(
            db_path=self._settings.ducklake_data_path,
            source_archive_url=self._settings.source_archive_url,
            max_articles=max_articles,
        )
        result = await ingestor.run(dry_run=dry_run)
        self._logger.info("Ingesta Bronze finalizada", **result)
        return result
