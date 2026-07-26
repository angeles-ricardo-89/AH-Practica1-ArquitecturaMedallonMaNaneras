from lakehouse.schemas.observability import PipelineLogs, PipelineStatus


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
