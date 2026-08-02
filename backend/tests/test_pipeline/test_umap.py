from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from lakehouse.pipeline.enrichment import _compute_umap_3d
from lakehouse.services.enrich_service import EnrichService


class TestComputeUmap3d:
    def test_returns_0_and_warns_when_umap_not_importable(self) -> None:
        with (
            patch.dict(sys.modules, {"umap": None}),
            patch("lakehouse.pipeline.enrichment.logger") as mock_logger,
        ):
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_logger.warning.assert_called_once()

    def test_calls_add_embedding_3d_column_before_select(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("k1", [0.1] * 3),
            ("k2", [0.2] * 3),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": SimpleNamespace(UMAP=MagicMock())}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column") as mock_add,
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_add.assert_called_once_with("postgresql://u:p@h:5433/d")

    def test_returns_0_when_column_ensure_fails(self) -> None:
        with (
            patch.dict(sys.modules, {"umap": SimpleNamespace(UMAP=MagicMock())}),
            patch(
                "lakehouse.db.observability_conn.add_embedding_3d_column",
                side_effect=RuntimeError("db down"),
            ) as mock_add,
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.pipeline.enrichment.logger") as mock_logger,
        ):
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_add.assert_called_once()
        mock_connect.assert_not_called()
        mock_logger.exception.assert_called_once()

    def test_returns_0_when_fewer_than_4_rows(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("k1", [0.1] * 3),
            ("k2", [0.2] * 3),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_conn.commit.assert_not_called()

    def test_updates_embedding_3d_for_all_chunks(self) -> None:
        rows = [(f"k{i}", [float(i), float(i + 1), float(i + 2)]) for i in range(4)]
        coords = np.array(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
                [10.0, 11.0, 12.0],
            ]
        )
        mock_reducer = MagicMock()
        mock_reducer.fit_transform.return_value = coords
        mock_umap_class = MagicMock(return_value=mock_reducer)
        fake_umap = SimpleNamespace(UMAP=mock_umap_class)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": fake_umap}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 4
        mock_umap_class.assert_called_once_with(n_components=3, random_state=42, n_neighbors=3)
        mock_reducer.fit_transform.assert_called_once()

        update_calls = [
            call
            for call in mock_cursor.execute.call_args_list
            if "UPDATE gold.rag_corpus" in call[0][0]
        ]
        assert len(update_calls) == 4
        for call, key, expected in zip(update_calls, [f"k{i}" for i in range(4)], coords):
            params = call[0][1]
            assert params[3] == key
            assert params[0] == float(expected[0])
            assert params[1] == float(expected[1])
            assert params[2] == float(expected[2])
        mock_conn.commit.assert_called_once()

    def test_returns_0_when_select_fails(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = RuntimeError("db down")
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": SimpleNamespace(UMAP=MagicMock())}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_conn.commit.assert_not_called()

    def test_filters_null_embeddings_and_runs_umap(self) -> None:
        rows = [
            ("k0", [0.0, 0.0, 0.0]),
            ("k1", None),
            ("k2", [1.0, 1.0, 1.0]),
            ("k3", None),
            ("k4", [2.0, 2.0, 2.0]),
            ("k5", [3.0, 3.0, 3.0]),
        ]
        coords = np.array(
            [
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
                [10.0, 11.0, 12.0],
            ]
        )
        mock_reducer = MagicMock()
        mock_reducer.fit_transform.return_value = coords
        mock_umap_class = MagicMock(return_value=mock_reducer)
        fake_umap = SimpleNamespace(UMAP=mock_umap_class)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": fake_umap}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 4
        mock_umap_class.assert_called_once_with(n_components=3, random_state=42, n_neighbors=3)
        mock_reducer.fit_transform.assert_called_once()
        update_keys = [
            call[0][1][3]
            for call in mock_cursor.execute.call_args_list
            if "UPDATE gold.rag_corpus" in call[0][0]
        ]
        assert update_keys == ["k0", "k2", "k4", "k5"]
        mock_conn.commit.assert_called_once()

    def test_returns_0_when_null_embedding_drops_below_4(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("k0", [0.0, 0.0, 0.0]),
            ("k1", None),
            ("k2", [1.0, 1.0, 1.0]),
            ("k3", [2.0, 2.0, 2.0]),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": SimpleNamespace(UMAP=MagicMock())}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_conn.commit.assert_not_called()

    def test_returns_0_when_conversion_fails(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("k0", [0.0, 0.0, 0.0]),
            ("k1", [1.0, 1.0, 1.0]),
            ("k2", [2.0, 2.0]),
            ("k3", [3.0, 3.0, 3.0]),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.dict(sys.modules, {"umap": SimpleNamespace(UMAP=MagicMock())}),
            patch("lakehouse.pipeline.enrichment.psycopg.connect") as mock_connect,
            patch("lakehouse.db.observability_conn.add_embedding_3d_column"),
            patch("lakehouse.pipeline.enrichment.logger"),
        ):
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = _compute_umap_3d("postgresql://u:p@h:5433/d")

        assert result == 0
        mock_conn.commit.assert_not_called()


class TestEnrichServiceCallsUmap:
    def _service(self) -> EnrichService:
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("c1", "P", "Texto de prueba " * 10, "", 0, "https://example.com", "2025-03-01"),
        ]
        return EnrichService(
            settings=MagicMock(),
            duckdb_conn=conn,
            pg_conn_str="postgresql://u:p@h:5433/d",
        )

    def test_run_calls_umap_when_embedded(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
        ):
            mock_enrich.return_value = {"embedded": 2, "failed": 0, "total": 2}
            result = self._service().run(dry_run=False)

        assert result["embedded"] == 2
        mock_umap.assert_called_once_with("postgresql://u:p@h:5433/d")

    def test_run_skips_umap_when_nothing_embedded(self) -> None:
        with (
            patch("lakehouse.services.enrich_service.ensure_gold_tables"),
            patch("lakehouse.services.enrich_service.enrich_interventions") as mock_enrich,
            patch("lakehouse.pipeline.enrichment._compute_umap_3d") as mock_umap,
        ):
            mock_enrich.return_value = {"embedded": 0, "failed": 0, "total": 2}
            result = self._service().run(dry_run=False)

        assert result["embedded"] == 0
        mock_umap.assert_not_called()
