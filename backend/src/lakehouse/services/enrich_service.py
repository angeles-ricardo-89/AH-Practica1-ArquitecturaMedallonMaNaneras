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
from lakehouse.schemas.gold import EnrichmentResult, WindowRecord
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
        run_gold_enrichment: bool = True,
        run_clustering: bool = False,
        run_semantic_cluster_labeling: bool = False,
    ) -> EnrichmentResult:
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
            return EnrichmentResult()

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
            return EnrichmentResult()

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
            return EnrichmentResult(total=len(windows))

        self._logger.info(
            "Iniciando enriquecimiento Gold",
            ventanas=len(windows),
            conference_date=conference_date,
        )

        ensure_gold_tables(self._pg_conn_str)

        enrichment_result = EnrichmentResult(total=len(windows))

        if run_gold_enrichment:
            self._logger.info("Ejecutando enriquecimiento Gold")
            result = enrich_interventions(
                windows=windows,
                conference_date=conference_date,
                pg_conn_str=self._pg_conn_str,
                ollama_base_url=self._settings.ollama_base_url,
                ollama_model=self._settings.ollama_embed_model,
                workers=workers,
            )

            enrichment_result.embedded = result.get("embedded", 0)
            enrichment_result.failed_to_embed = result.get("failed_to_embed", 0)

            if result and result.get("embedded", 0) > 0:
                self._logger.info("Ejecutando UMAP 3D sobre embeddings")
                from lakehouse.pipeline.enrichment import _compute_umap_3d  # noqa: PLC0415

                enrichment_result.mapped_3d = _compute_umap_3d(self._pg_conn_str)

        cluster_result: dict | None = None
        if run_clustering:
            self._logger.info("Ejecutando clusterizacion semantica")
            try:
                from lakehouse.pipeline.clustering import (  # noqa: PLC0415
                    run_clustering as _run_clustering,
                )

                cluster_result = _run_clustering(self._settings, force=run_clustering)
                if cluster_result and cluster_result.get("skipped"):
                    self._logger.info(
                        "clusterizacion_omitida",
                        run_id=cluster_result.get("run_id"),
                    )
                elif cluster_result:
                    self._logger.info(
                        "clusterizacion_completada",
                        run_id=cluster_result.get("run_id"),
                        clusters=cluster_result.get("clusters"),
                        noise=cluster_result.get("noise"),
                    )
                if cluster_result:
                    enrichment_result.clustered = cluster_result.get("clusters", 0)
                    enrichment_result.noise = cluster_result.get("noise", 0)

            except Exception:
                self._logger.exception("clusterizacion_fallida")
                cluster_result = None

        if run_semantic_cluster_labeling:
            self._logger.info("Ejecutando autoetiquetado semantico")
            try:
                from lakehouse.pipeline.clustering import run_labeling  # noqa: PLC0415

                label_result = run_labeling(
                    self._settings,
                    run_id=cluster_result["run_id"] if cluster_result else None,
                )
                if label_result:
                    self._logger.info(
                        "etiquetado_completado",
                        run_id=label_result.get("run_id"),
                        completed=label_result.get("completed"),
                        failed=label_result.get("failed"),
                    )
                    enrichment_result.clustered_with_labels = label_result.get("completed", 0)
                    enrichment_result.failed_to_label = label_result.get("failed", 0)
            except Exception:
                self._logger.exception("etiquetado_fallido")
        enrichment_result.failed = (
            enrichment_result.failed_to_embed + enrichment_result.failed_to_label
        )
        return enrichment_result
