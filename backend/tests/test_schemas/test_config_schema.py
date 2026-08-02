from lakehouse.schemas.config import ConfigResponse, ModelosConfig


class TestModelosConfig:
    def test_valid(self):
        m = ModelosConfig(llm="gemma4", embedding="embeddinggemma")
        assert m.llm == "gemma4"
        assert m.embedding == "embeddinggemma"


class TestConfigResponse:
    def test_valid(self):
        c = ConfigResponse(
            ambiente="dev",
            docker=True,
            version="0.1.0",
            modelos=ModelosConfig(llm="gemma4", embedding="embeddinggemma"),
        )
        assert c.ambiente == "dev"
        assert c.docker is True
        assert c.version == "0.1.0"
        assert c.modelos.llm == "gemma4"

    def test_desconocido_when_no_env(self):
        c = ConfigResponse(
            ambiente="desconocido",
            docker=False,
            version="0.1.0",
            modelos=ModelosConfig(llm="gemma4", embedding="embeddinggemma"),
        )
        assert c.ambiente == "desconocido"
