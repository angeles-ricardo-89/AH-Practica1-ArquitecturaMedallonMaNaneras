from __future__ import annotations

from lakehouse.config import Settings
from lakehouse.services import rag_search
from lakehouse.services.agent import llm


class _FakeEmbedding:
    def __init__(self, api_key: str, model: str, dimension: int = 768) -> None:
        self.api_key = api_key
        self.model = model
        self.dimension = dimension

    def embed_query(self, text: str) -> list[float]:
        return [0.5, 0.5, 0.5]


class _FakeChat:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.last_kwargs: dict = {}

    def generate(
        self,
        messages: list[dict],
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        self.last_kwargs = {
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
            "response_mime_type": response_mime_type,
        }
        return "plan respuesta"


def _prod_settings() -> Settings:
    return Settings(
        app_env="production",
        gemini_api_key="test-key",
        gemini_chat_model="gemini-prod",
        gemini_embedding_model="gemini-embed-prod",
        neon_database_url="postgresql://u:p@h-pooler.example.com/db",
    )


class TestEmbedSearchQuery:
    def test_local_uses_ollama(self, monkeypatch) -> None:
        calls: list[tuple] = []

        def fake_ollama(query: str, base_url: str, model: str) -> list[float]:
            calls.append((query, base_url, model))
            return [1.0]

        monkeypatch.setattr(rag_search, "_embed_query", fake_ollama)
        settings = Settings(app_env="local")
        result = rag_search.embed_search_query(settings, "reforma")
        assert result == [1.0]
        assert calls == [("reforma", settings.ollama_base_url, settings.ollama_embed_model)]

    def test_production_uses_gemini(self, monkeypatch) -> None:
        captured: dict = {}

        def factory(api_key: str, model: str, dimension: int = 768) -> _FakeEmbedding:
            captured["api_key"] = api_key
            captured["model"] = model
            captured["dimension"] = dimension
            return _FakeEmbedding(api_key, model, dimension)

        monkeypatch.setattr(rag_search, "GeminiEmbeddingAdapter", factory)
        settings = _prod_settings()
        assert rag_search.embed_search_query(settings, "energia") == [0.5, 0.5, 0.5]
        assert captured["api_key"] == settings.gemini_api_key
        assert captured["model"] == settings.gemini_embedding_model
        assert captured["dimension"] == settings.gemini_embedding_dimension


class TestLlmDispatch:
    def test_active_chat_model(self) -> None:
        assert llm.active_chat_model(_prod_settings()) == "gemini-prod"
        assert llm.active_chat_model(Settings(app_env="local")) == Settings().llamacpp_model

    def test_chat_json_production_sets_json_mime(self, monkeypatch) -> None:
        fake = _FakeChat("k", "m")
        captured: dict = {}

        def factory(api_key: str, model: str) -> _FakeChat:
            captured["api_key"] = api_key
            captured["model"] = model
            return fake

        monkeypatch.setattr(llm, "GeminiChatAdapter", factory)
        out = llm.chat_json(_prod_settings(), [{"role": "user", "content": "hola"}], max_tokens=512)
        assert out == "plan respuesta"
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "gemini-prod"
        assert fake.last_kwargs["response_mime_type"] == "application/json"
        assert fake.last_kwargs["max_output_tokens"] == 512

    def test_chat_text_local_posts_to_llamacpp(self, monkeypatch) -> None:
        def fake_post(
            settings: object,
            messages: list[dict],
            *,
            json_mode: bool,
            max_tokens: int,
            temperature: float,
        ) -> str:
            assert json_mode is False
            return "respuesta local"

        monkeypatch.setattr(llm, "_post", fake_post)
        assert llm.chat_text(Settings(app_env="local"), [{"role": "user", "content": "hola"}]) == (
            "respuesta local"
        )
