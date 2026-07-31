import hashlib

from lakehouse.config import Settings
from lakehouse.db.merge import (
    drop_silver_tables,
    ensure_silver_tables,
    insert_dlq_record,
    merge_conference,
    merge_intervention,
)
from lakehouse.log_config import ProgressReporter, get_logger
from lakehouse.pipeline.parsing import (
    build_conference_record,
    parse_conference_date,
    parse_html_to_interventions,
)
from lakehouse.schemas.silver import DLQRejectRecord


class ParseService:
    def __init__(self, settings: Settings, duckdb_conn) -> None:
        self._settings = settings
        self._conn = duckdb_conn
        self._logger = get_logger(__name__, layer="service")

    def run(
        self,
        dry_run: bool = False,
        conference_date: str | None = None,
        clean: bool = False,
    ) -> dict:
        if clean:
            if dry_run:
                self._logger.warning("--clean es ignorado en dry-run")
            else:
                drop_silver_tables(self._conn)
        if not dry_run:
            ensure_silver_tables(self._conn)
        rows = self._conn.execute("SELECT source_url, raw_html FROM bronze.raw_html").fetchall()
        total_interventions = 0
        total_dlq = 0
        self._logger.info("Iniciando parseo Silver", html_count=len(rows))
        reporter = ProgressReporter(total=len(rows), label="silver")
        for idx, (source_url, raw_html) in enumerate(rows):
            reporter.update(idx + 1)
            interventions, dlq = self._process_row(source_url, raw_html, conference_date, dry_run)
            total_interventions += interventions
            total_dlq += dlq
        reporter.finish()
        self._logger.info(
            "Parseo Silver completado",
            interventions=total_interventions,
            dlq=total_dlq,
        )
        return {"interventions": total_interventions, "dlq": total_dlq}

    def _process_row(
        self,
        source_url: str,
        raw_html: str,
        conference_date: str | None,
        dry_run: bool,
    ) -> tuple[int, int]:
        date = conference_date or parse_conference_date(raw_html, source_url)
        if date is None:
            conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
            dlq = DLQRejectRecord(
                source_record_id=conference_id,
                rejection_reason="unknown_date",
                raw_data=source_url,
            )
            if not dry_run:
                insert_dlq_record(self._conn, dlq)
            self._logger.warning("Fecha desconocida, articulo enviado a DLQ", source_url=source_url)
            return 0, 1
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
            merge_conference(self._conn, conference)
            self._logger.info(
                "Registro de conferencia insertado", conference_id=conference.conference_id
            )
        interventions = 0
        dlq = 0
        for record in records:
            if not dry_run:
                if isinstance(record, DLQRejectRecord):
                    self._logger.warning("Registro rechazado, insertando en DLQ", record=record)
                    insert_dlq_record(self._conn, record)
                    dlq += 1
                else:
                    merge_intervention(self._conn, record)
                    interventions += 1
            elif isinstance(record, DLQRejectRecord):
                dlq += 1
            else:
                interventions += 1
        return interventions, dlq
