from lakehouse.config import Settings


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.app_env == "local"
        assert s.postgres_host == "localhost"
        assert s.ollama_base_url == "http://localhost:11434"
        assert s.llamacpp_base_url == "http://localhost:9200/v1"
        assert s.rag_top_k == 8
        assert s.max_context_tokens == 10000
        assert s.llamacpp_model == "gemma-4-12b"
        assert s.ollama_embed_model == "embeddinggemma"
