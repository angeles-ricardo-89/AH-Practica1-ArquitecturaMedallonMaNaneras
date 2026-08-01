from unittest.mock import MagicMock, patch

from lakehouse.config import Settings
from lakehouse.schemas.gold import WindowRecord
from lakehouse.schemas.silver import InterventionRecord
from lakehouse.services.enrich_service import EnrichService, build_windows_from_conference


class TestEnrichService:
    def test_run_dry_run_returns_metrics(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        result = service.run(dry_run=True)
        assert result["total"] == 0

    def test_run_conferencia_sin_fecha_es_omitida(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", None),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            result = service.run(dry_run=False)
        assert result == {"embedded": 0, "failed": 0, "total": 0}
        mock_enrich.assert_not_called()

    def test_run_intervenciones_cortas_no_construyen_windows(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "t", "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            result = service.run(dry_run=False)
        assert result == {"embedded": 0, "failed": 0, "total": 0}
        mock_enrich.assert_not_called()

    def test_run_no_dry_run_calls_enrich(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables") as mock_ensure,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(dry_run=False)
        assert result["embedded"] == 1
        mock_ensure.assert_called_once()
        mock_enrich.assert_called_once()
        windows = mock_enrich.call_args.kwargs["windows"]
        assert len(windows) == 1
        assert isinstance(windows[0], WindowRecord)

    def test_run_propaga_fecha_desde_silver_conferences(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            service.run(dry_run=False)

        sql = conn.execute.call_args[0][0]
        assert "FROM silver.interventions" in sql
        assert "JOIN silver.conferences" in sql
        windows = mock_enrich.call_args.kwargs["windows"]
        assert windows[0].conference_date == "2025-03-01"
        assert mock_enrich.call_args.kwargs["conference_date"] is None

    def test_run_dry_run_con_intervenciones_no_llama_enrich(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables") as mock_ensure,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            result = service.run(dry_run=True)
        assert result["total"] == 1
        mock_ensure.assert_not_called()
        mock_enrich.assert_not_called()

    def test_run_clean_drops_gold_tables(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.drop_gold_tables") as mock_drop,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(clean=True)
        assert result["embedded"] == 1
        mock_drop.assert_called_once()

    def test_run_clean_ignored_in_dry_run(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.drop_gold_tables") as mock_drop,
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            service.run(clean=True, dry_run=True)
        mock_drop.assert_not_called()

    def test_run_propaga_workers_a_enrich_interventions(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            result = service.run(workers=4)
        assert result["embedded"] == 1
        _, kwargs = mock_enrich.call_args
        assert kwargs["workers"] == 4

    def test_run_default_workers_is_one(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            service.run()
        _, kwargs = mock_enrich.call_args
        assert kwargs["workers"] == 1

    def test_run_grupos_por_conferencia_con_dos_conferencias(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("cA", "P1", "Texto largo de la conferencia A " * 3, "", 0, "https://a", "2025-03-01"),
            (
                "cA",
                "P2",
                "Otro texto largo de la conferencia A " * 3,
                "",
                1,
                "https://a",
                "2025-03-01",
            ),
            ("cB", "P3", "Texto largo de la conferencia B " * 3, "", 0, "https://b", "2025-06-10"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            service.run(dry_run=False)

        windows = mock_enrich.call_args.kwargs["windows"]
        assert len(windows) == 2
        confs = {w.conference_id for w in windows}
        assert confs == {"cA", "cB"}
        dates = {w.conference_date for w in windows}
        assert dates == {"2025-03-01", "2025-06-10"}
        assert mock_enrich.call_args.kwargs["conference_date"] is None

    def test_run_conferencia_sin_fecha_otras_si_se_procesan(self):
        settings = Settings()
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("cA", "P1", "Texto largo de la conferencia A " * 3, "", 0, "https://a", None),
            ("cB", "P2", "Texto largo de la conferencia B " * 3, "", 0, "https://b", "2025-06-10"),
        ]
        service = EnrichService(
            settings=settings,
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
        ):
            mock_enrich.return_value = {"embedded": 1, "failed": 0, "total": 1}
            service.run(dry_run=False)

        windows = mock_enrich.call_args.kwargs["windows"]
        assert len(windows) == 1
        assert windows[0].conference_id == "cB"
        assert windows[0].conference_date == "2025-06-10"


class TestBuildWindowsFromConference:
    def test_filters_short_sorts_and_builds_windows(self) -> None:
        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}",
                conference_id="c1",
                participant="P",
                text="Sí, seguridad." if i == 1 else "Texto largo " * 20,
                pregunta_activa="",
                chunk_index=i,
                url="https://u",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert len(windows) == 1
        assert windows[0].conference_id == "c1"
        assert windows[0].chunk_key.startswith("c1_w000_")
        assert "Sí, seguridad." not in windows[0].text  # filtrado

    def test_all_short_returns_empty(self) -> None:
        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}",
                conference_id="c1",
                participant="P",
                text="Sí.",
                pregunta_activa="",
                chunk_index=i,
                url="",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert windows == []

    def test_empty_input_returns_empty(self) -> None:
        assert build_windows_from_conference([], conference_date="2025-03-01") == []

    def test_sorts_by_chunk_index(self) -> None:
        records = [
            InterventionRecord(
                intervention_key=f"k{i:03d}",
                conference_id="c1",
                participant="P",
                text=f"Texto {3 - i}: " + "contenido largo " * 10,
                pregunta_activa="",
                chunk_index=3 - i,
                url="",
                conference_date="2025-03-01",
            )
            for i in range(3)
        ]
        windows = build_windows_from_conference(records, conference_date="2025-03-01")
        assert windows[0].text.startswith("P: Texto 1: contenido largo")
