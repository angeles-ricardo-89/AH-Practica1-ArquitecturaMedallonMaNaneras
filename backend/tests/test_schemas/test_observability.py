from lakehouse.schemas.observability import (
    LayerHistoryResponse,
    LayerRun,
    PipelineLayersResponse,
    PipelineLogs,
    PipelineStatus,
)


class TestPipelineStatus:
    def test_ok_status(self):
        s = PipelineStatus(
            status="ok",
            last_run="2024-10-01T10:00:00Z",
            last_success="2024-10-01T10:00:00Z",
            records_count=150,
        )
        assert s.status == "ok"
        assert s.records_count == 150


class TestPipelineLogs:
    def test_valid_logs(self):
        l = PipelineLogs(lines=["line1", "line2"], total_lines=2)
        assert len(l.lines) == 2


class TestLayerRun:
    def test_valid_layer_run(self):
        r = LayerRun(
            capa="bronze",
            status="ok",
            run_id="abc123",
            duracion_seg=12.4,
            records_in=150,
            records_out=150,
            dlq_count=0,
            started_at="2026-08-01T10:00:00Z",
            finished_at="2026-08-01T10:00:12Z",
        )
        assert r.capa == "bronze"
        assert r.duracion_seg == 12.4
        assert r.dlq_count == 0

    def test_defaults(self):
        r = LayerRun(capa="silver", status="running", run_id="xyz")
        assert r.records_in == 0
        assert r.records_out == 0
        assert r.dlq_count == 0
        assert r.duracion_seg is None
        assert r.started_at is None
        assert r.finished_at is None

    def test_valid_capas(self):
        for capa in ("bronze", "silver", "gold"):
            r = LayerRun(capa=capa, status="ok", run_id="x")
            assert r.capa == capa

    def test_valid_statuses(self):
        for status in ("running", "ok", "error", "unknown"):
            r = LayerRun(capa="bronze", status=status, run_id="x")
            assert r.status == status


class TestPipelineLayersResponse:
    def test_empty(self):
        r = PipelineLayersResponse(layers=[], health_global="sin datos", ultima_corrida_global="")
        assert r.health_global == "sin datos"
        assert r.layers == []

    def test_with_layers(self):
        layers = [
            LayerRun(capa="bronze", status="ok", run_id="a1"),
            LayerRun(capa="silver", status="ok", run_id="a2"),
            LayerRun(capa="gold", status="ok", run_id="a3"),
        ]
        r = PipelineLayersResponse(
            layers=layers,
            health_global="Healthy",
            ultima_corrida_global="2026-08-01T10:00:00Z",
        )
        assert len(r.layers) == 3
        assert r.health_global == "Healthy"


class TestLayerHistoryResponse:
    def test_empty(self):
        r = LayerHistoryResponse(capa="bronze", runs=[])
        assert r.capa == "bronze"
        assert r.runs == []

    def test_with_runs(self):
        runs = [
            LayerRun(capa="bronze", status="ok", run_id="r1"),
            LayerRun(capa="bronze", status="error", run_id="r2"),
        ]
        r = LayerHistoryResponse(capa="bronze", runs=runs)
        assert len(r.runs) == 2
        assert r.capa == "bronze"
