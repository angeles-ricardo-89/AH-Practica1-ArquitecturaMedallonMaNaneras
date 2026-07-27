from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.log_reader import count_log_lines, read_log
from lakehouse.services.status_writer import read_status, write_status
from lakehouse.services.token_estimator import estimate_tokens


class TestTokenEstimator:
    def test_estimate_empty(self):
        assert estimate_tokens("") == 1

    def test_estimate_single_char(self):
        assert estimate_tokens("x") == 1

    def test_estimate_short(self):
        assert estimate_tokens("hello") == 1

    def test_estimate_long(self):
        assert estimate_tokens("a" * 100) == 25


class TestContextBuilderEdgeCases:
    def test_empty_sources_empty_history(self):
        builder = ContextBuilder(max_context_tokens=100)
        context, usage = builder.build(
            query="q",
            system_prompt="sys",
            sources=[],
            history=[],
        )
        assert usage.prompt > 0
        assert "q" in context

    def test_truncation_when_system_and_query_exceed(self):
        builder = ContextBuilder(max_context_tokens=10)
        context, _usage = builder.build(
            query="query here please",
            system_prompt="a very long system prompt that will definitely exceed the token limit",
            sources=[],
        )
        assert "query" in context
        assert "system" in context

    def test_history_messages_with_various_roles(self):
        builder = ContextBuilder(max_context_tokens=200)
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        context, _usage = builder.build(
            query="second question",
            system_prompt="sys",
            sources=[],
            history=history,
        )
        assert "first question" in context
        assert "first answer" in context
        assert "second question" in context

    def test_truncate_to_tokens_zero(self):
        builder = ContextBuilder()
        result = builder._truncate_to_tokens("hello world", 0)
        assert result == ""

    def test_truncate_to_tokens_positive(self):
        builder = ContextBuilder()
        result = builder._truncate_to_tokens("hello world", 2)
        assert result == "hello wo"

    def test_format_history_empty(self):
        builder = ContextBuilder()
        result = builder._format_history([])
        assert result == ""

    def test_format_history_unknown_role(self):
        builder = ContextBuilder()
        result = builder._format_history([{"content": "hello"}])
        assert "unknown" in result
        assert "hello" in result

    def test_format_history_multiple(self):
        builder = ContextBuilder()
        result = builder._format_history(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "bye"},
            ]
        )
        assert "user: hi" in result
        assert "assistant: bye" in result


class TestLogReader:
    def test_read_log_nonexistent(self):
        lines = read_log("/nonexistent/path.log")
        assert lines == []

    def test_read_log_empty_file(self, tmp_path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")
        lines = read_log(str(log_file), lines=5)
        assert lines == [""]

    def test_read_log_single_line(self, tmp_path):
        log_file = tmp_path / "single.log"
        log_file.write_text("just one line")
        lines = read_log(str(log_file), lines=5)
        assert lines == ["just one line"]

    def test_read_log_fewer_lines_than_requested(self, tmp_path):
        log_file = tmp_path / "few.log"
        log_file.write_text("line1\nline2")
        lines = read_log(str(log_file), lines=50)
        assert len(lines) == 2

    def test_count_log_lines_nonexistent(self):
        assert count_log_lines("/nonexistent/path.log") == 0

    def test_count_log_lines_returns_total(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("a\nb\nc\n")
        assert count_log_lines(str(log_file)) == 3

    def test_log_reader_oserror(self, tmp_path):
        log_file = tmp_path / "locked.log"
        log_file.write_text("test data")
        log_file.chmod(0o000)
        lines = read_log(str(log_file))
        assert lines == []
        log_file.chmod(0o644)

    def test_count_log_lines_oserror(self, tmp_path):
        log_file = tmp_path / "locked2.log"
        log_file.write_text("test")
        log_file.chmod(0o000)
        assert count_log_lines(str(log_file)) == 0
        log_file.chmod(0o644)


class TestStatusWriter:
    def test_read_status_nonexistent(self):
        status = read_status("/nonexistent/status.json")
        assert status["status"] == "unknown"

    def test_read_status_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        status = read_status(str(f))
        assert status["status"] == "unknown"

    def test_write_and_read_ok(self, tmp_path):
        f = tmp_path / "cron.status"
        write_status(str(f), "ok")
        data = read_status(str(f))
        assert data["status"] == "ok"
        assert "last_run" in data
        assert "last_success" in data

    def test_write_and_read_running(self, tmp_path):
        f = tmp_path / "cron.status"
        write_status(str(f), "running")
        data = read_status(str(f))
        assert data["status"] == "running"
        assert "last_success" not in data

    def test_write_and_read_error(self, tmp_path):
        f = tmp_path / "cron.status"
        write_status(str(f), "error")
        data = read_status(str(f))
        assert data["status"] == "error"
