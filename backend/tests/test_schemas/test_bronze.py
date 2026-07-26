import pytest
from pydantic import ValidationError

from lakehouse.schemas.bronze import BronzeRecord, IngestionManifest


class TestIngestionManifest:
    def test_valid_manifest(self):
        m = IngestionManifest(
            run_id="run_abc123",
            source_url="https://example.com",
            html_count=5,
            status="completed",
        )
        assert m.run_id == "run_abc123"
        assert m.html_count == 5
        assert m.status == "completed"

    def test_default_status(self):
        m = IngestionManifest(
            run_id="run_abc",
            source_url="https://example.com",
            html_count=0,
        )
        assert m.status == "pending"

    def test_rejects_negative_html_count(self):
        with pytest.raises(ValidationError):
            IngestionManifest(
                run_id="run_abc",
                source_url="https://example.com",
                html_count=-1,
            )


class TestBronzeRecord:
    def test_valid_record(self):
        r = BronzeRecord(
            ingestion_run_id="run_abc",
            source_url="https://example.com",
            raw_html="<html></html>",
            content_hash="a" * 64,
        )
        assert r.ingestion_run_id == "run_abc"
        assert r.content_hash == "a" * 64

    def test_content_hash_must_be_64_chars(self):
        with pytest.raises(ValidationError):
            BronzeRecord(
                ingestion_run_id="run_abc",
                source_url="https://example.com",
                raw_html="<html></html>",
                content_hash="too_short",
            )

    def test_content_hash_rejects_non_hex(self):
        with pytest.raises(ValidationError):
            BronzeRecord(
                ingestion_run_id="run_abc",
                source_url="https://example.com",
                raw_html="<html></html>",
                content_hash="z" * 64,
            )

    def test_rejects_empty_raw_html(self):
        with pytest.raises(ValidationError):
            BronzeRecord(
                ingestion_run_id="run_abc",
                source_url="https://example.com",
                raw_html="",
                content_hash="a" * 64,
            )
