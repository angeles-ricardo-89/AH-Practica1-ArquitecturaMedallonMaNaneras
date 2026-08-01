from collections import defaultdict

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.pipeline.enrichment import (
    MIN_CHUNK_LENGTH,
    build_window_key,
    build_window_text,
    build_windows,
    drop_gold_tables,
    enrich_interventions,
    ensure_gold_tables,
)
from lakehouse.schemas.gold import WindowRecord
from lakehouse.schemas.silver import InterventionRecord


def build_windows_from_conference(
    interventions: list[InterventionRecord],
    conference_date: str,
) -> list[WindowRecord]:
    filtered = sorted(
        (i for i in interventions if len(i.text) >= MIN_CHUNK_LENGTH),
        key=lambda i: i.chunk_index,
    )
    if not filtered:
        return []
    windows = build_windows(filtered)
    records = []
    for idx, window in enumerate(windows):
        text = build_window_text(window)
        records.append(
            WindowRecord(
                chunk_key=build_window_key(window[0].conference_id, idx, text),
                conference_id=window[0].conference_id,
                conference_date=conference_date,
                participant=window[0].participant,
                pregunta_activa="",
                text=text,
                url=window[0].url,
                window_index=idx,
            )
        )
    return records


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
            SELECT i.conference_id, i.participant, i.text,
                   i.pregunta_activa, i.chunk_index, i.url, c.date AS conference_date
            FROM silver.interventions i
            LEFT JOIN silver.conferences c ON c.conference_id = i.conference_id
            ORDER BY i.conference_id, i.chunk_index
            """
        ).fetchall()
        self._conn.close()

        interventions = [
            InterventionRecord(
                conference_id=r[0],
                participant=r[1],
                text=r[2],
                pregunta_activa=r[3],
                chunk_index=r[4],
                url=r[5],
                conference_date=r[6],
                intervention_key=f"{r[0]}_{r[4]:03d}",
            )
            for r in rows
        ]

        if not interventions:
            self._logger.warning("No hay intervenciones en Silver para enriquecer")
            return {"embedded": 0, "failed": 0, "total": 0}

        by_conference: dict[str, list[InterventionRecord]] = defaultdict(list)
        for i in interventions:
            by_conference[i.conference_id].append(i)

        windows: list[WindowRecord] = []
        for conf_id, group in by_conference.items():
            date = group[0].conference_date
            if not date:
                self._logger.warning(
                    "Conferencia sin fecha, omitida",
                    conference_id=conf_id,
                )
                continue
            windows.extend(build_windows_from_conference(group, conference_date=date))

        if not windows:
            self._logger.warning("No se construyeron ventanas desde Silver")
            return {"embedded": 0, "failed": 0, "total": 0}

        if clean:
            if dry_run:
                self._logger.warning("--clean es ignorado en dry-run")
            else:
                drop_gold_tables(self._pg_conn_str)

        if dry_run:
            self._logger.info(
                "Simulacion: ventanas listas para Gold",
                cantidad=len(windows),
            )
            return {"embedded": 0, "failed": 0, "total": len(windows)}

        self._logger.info(
            "Iniciando enriquecimiento Gold",
            ventanas=len(windows),
            conference_date=conference_date,
        )
        ensure_gold_tables(self._pg_conn_str)
        return enrich_interventions(
            windows=windows,
            conference_date=None,
            pg_conn_str=self._pg_conn_str,
            ollama_base_url=self._settings.ollama_base_url,
            ollama_model=self._settings.ollama_embed_model,
            workers=workers,
        )
