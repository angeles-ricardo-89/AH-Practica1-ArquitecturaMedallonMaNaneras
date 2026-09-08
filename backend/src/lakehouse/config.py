from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "local"
    source_archive_url: str = "https://www.gob.mx/presidencia/es/archivo/articulos"

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "mananeras"
    postgres_user: str = "mananeras"
    postgres_password: str = "mananeras"

    db_connect_timeout: int = 5
    db_statement_timeout_ms: int = 10000

    ducklake_catalog: str = "postgres"
    ducklake_data_path: str = "data/lakehouse/ducklake_files.duckdb"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "embeddinggemma"

    llamacpp_base_url: str = "http://localhost:9200/v1"
    llamacpp_model: str = "gemma-4-12b"

    model_request_timeout: float = 10.0

    rag_top_k: int = 8
    max_context_tokens: int = 10000
    max_ingest_pool: int = 1
    temporal_parser_temperature: float = 0.1
    temporal_parser_max_retries: int = 3
    temporal_parser_max_tokens: int = 8192
    app_timezone: str = "America/Mexico_City"

    umap_clustering_n_components: int = 30
    umap_clustering_n_neighbors: int = 50
    umap_clustering_min_dist: float = 0.0
    umap_clustering_metric: str = "cosine"
    umap_clustering_random_state: int = 42

    hdbscan_min_cluster_size: int = 50
    hdbscan_min_samples: int = 5
    hdbscan_metric: str = "euclidean"
    hdbscan_algorithm: str = "best"
    hdbscan_cluster_selection_method: str = "eom"
    hdbscan_n_jobs: int = -1

    k_hdbscan_sampling: int = 5

    cluster_label_max_chars_per_chunk: int = 1500
    cluster_label_max_retries: int = 2
    cluster_label_prompt_version: str = "v1"

    jwt_secret: str = ""
    csrf_secret: str = ""
    jwt_expire_minutes: int = 60
    jwt_issuer: str = "lakehouse-mananeras"
    jwt_audience: str = "lakehouse-api"
    auth_cookie_name: str = "access_token"
    csrf_header_name: str = "X-CSRF-Token"
    demo_user_1_username: str = ""
    demo_user_1_password: str = ""
    demo_user_2_username: str = ""
    demo_user_2_password: str = ""

    login_rate_limit: int = 5
    chat_rate_limit: int = 10
    daily_rate_limit: int = 100
    cors_allowed_origins: list[str] = []
    max_request_body_bytes: int = 65536

    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_dimension: int = 768
    index_format_version: str = "v1"
    neon_database_url: str = ""
    frontend_dist_dir: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def demo_users(self) -> list[tuple[str, str]]:
        pairs = [
            (self.demo_user_1_username, self.demo_user_1_password),
            (self.demo_user_2_username, self.demo_user_2_password),
        ]
        return [(u, p) for u, p in pairs if u and p]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
