import pytest
from pydantic import ValidationError

from lakehouse.schemas.search import SearchRequest, SearchResponse


class TestSearchRequest:
    def test_valid_request(self):
        r = SearchRequest(query="reforma energética")
        assert r.query == "reforma energética"
        assert r.top_k == 8

    def test_custom_top_k(self):
        r = SearchRequest(query="salud", top_k=3)
        assert r.top_k == 3

    def test_rejects_empty_query(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="")

    def test_rejects_blank_query(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="   ")

    def test_rejects_query_too_long(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="x" * 501)

    def test_accepts_500_char_query(self):
        r = SearchRequest(query="x" * 500)
        assert len(r.query) == 500

    def test_rejects_top_k_below_1(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", top_k=0)

    def test_rejects_top_k_above_50(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", top_k=51)

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", unknown_field="x")


class TestSearchResponse:
    def test_empty_response(self):
        r = SearchResponse(results=[], total=0, strategy="hnsw")
        assert r.total == 0
        assert r.results == []
