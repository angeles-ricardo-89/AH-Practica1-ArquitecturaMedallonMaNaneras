from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "local"
    source_archive_url: str = "https://www.gob.mx/presidencia/es/archivo/articulos"

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "mananeras"
    postgres_user: str = "mananeras"
    postgres_password: str = "mananeras"

    ducklake_catalog: str = "postgres"
    ducklake_data_path: str = "data/lakehouse/ducklake_files.duckdb"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "embeddinggemma"

    llamacpp_base_url: str = "http://localhost:9200/v1"
    llamacpp_model: str = "gemma4"

    rag_top_k: int = 8
    max_context_tokens: int = 8192
    max_ingest_pool: int = 6
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
