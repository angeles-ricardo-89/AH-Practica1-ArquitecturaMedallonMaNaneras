import hashlib
from concurrent.futures import Future, ProcessPoolExecutor, as_completed

import duckdb

from lakehouse.config import Settings
from lakehouse.db.duckdb_conn import get_connection
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
from lakehouse.schemas.silver import ConferenceRecord, DLQRejectRecord, InterventionRecord


def _parse_one_row(
    source_url: str,
    raw_html: str,
    conference_date: str | None,
) -> tuple[ConferenceRecord | None, list[InterventionRecord], list[DLQRejectRecord]]:
    date = conference_date or parse_conference_date(raw_html, source_url)
    if date is None:
        conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
        dlq = DLQRejectRecord(
            source_record_id=conference_id,
            rejection_reason="unknown_date",
            raw_data=source_url,
        )
        return None, [], [dlq]

    records = parse_html_to_interventions(
        raw_html=raw_html, source_url=source_url, conference_date=date
    )
    conference = build_conference_record(
        source_url=source_url, conference_date=date, raw_html=raw_html
    )
    interventions = [r for r in records if isinstance(r, InterventionRecord)]
    dlq = [r for r in records if isinstance(r, DLQRejectRecord)]
    return conference, interventions, dlq


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
        workers: int = 1,
    ) -> dict:
        workers = max(1, workers)

        if clean:
            if dry_run:
                self._logger.warning("--clean es ignorado en dry-run")
            else:
                drop_silver_tables(self._conn)
        if not dry_run:
            ensure_silver_tables(self._conn)

        rows = self._conn.execute("SELECT source_url, raw_html FROM bronze.raw_html").fetchall()
        self._conn.close()

        total_interventions = 0
        total_dlq = 0
        self._logger.info("Iniciando parseo Silver", html_count=len(rows), workers=workers)
        reporter = ProgressReporter(total=len(rows), label="silver")

        if rows:
            write_conn = None
            if not dry_run:
                write_conn = get_connection(self._settings.ducklake_data_path)
            try:
                if workers > 1:
                    total_interventions, total_dlq = self._run_parallel(
                        rows=rows,
                        write_conn=write_conn,
                        conference_date=conference_date,
                        reporter=reporter,
                        workers=workers,
                    )
                else:
                    total_interventions, total_dlq = self._run_sequential(
                        rows=rows,
                        write_conn=write_conn,
                        conference_date=conference_date,
                        reporter=reporter,
                    )
            finally:
                if write_conn is not None:
                    write_conn.close()

        reporter.finish()
        self._logger.info(
            "Parseo Silver completado",
            interventions=total_interventions,
            dlq=total_dlq,
        )
        return {"interventions": total_interventions, "dlq": total_dlq}

    def _run_sequential(
        self,
        rows: list[tuple[str, str]],
        write_conn: duckdb.DuckDBPyConnection | None,
        conference_date: str | None,
        reporter: ProgressReporter,
    ) -> tuple[int, int]:
        total_interventions = 0
        total_dlq = 0
        for source_url, raw_html in rows:
            conference, interventions, dlq_records = _parse_one_row(
                source_url, raw_html, conference_date
            )
            if write_conn is not None:
                if conference is not None:
                    merge_conference(write_conn, conference)
                for record in interventions:
                    merge_intervention(write_conn, record)
            for dlq in dlq_records:
                if write_conn is not None:
                    insert_dlq_record(write_conn, dlq)
            total_interventions += len(interventions)
            total_dlq += len(dlq_records)
            reporter.tick()
        return total_interventions, total_dlq

    def _run_parallel(
        self,
        rows: list[tuple[str, str]],
        write_conn: duckdb.DuckDBPyConnection | None,
        conference_date: str | None,
        reporter: ProgressReporter,
        workers: int,
    ) -> tuple[int, int]:
        total_interventions = 0
        total_dlq = 0

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures: dict[Future, tuple[str, str]] = {}
            for source_url, raw_html in rows:
                future = pool.submit(_parse_one_row, source_url, raw_html, conference_date)
                futures[future] = (source_url, raw_html)

            for future in as_completed(futures):
                conference, interventions, dlq_records = future.result()
                if write_conn is not None:
                    if conference is not None:
                        merge_conference(write_conn, conference)
                    for record in interventions:
                        merge_intervention(write_conn, record)
                for dlq in dlq_records:
                    if write_conn is not None:
                        insert_dlq_record(write_conn, dlq)

                total_interventions += len(interventions)
                total_dlq += len(dlq_records)
                reporter.tick()

        return total_interventions, total_dlq
