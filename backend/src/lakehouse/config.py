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
    max_ingest_pool: int = 1
    temporal_parser_temperature: float = 0.1
    temporal_parser_max_retries: int = 3
    temporal_parser_max_tokens: int = 1200

    umap_clustering_n_components: int = 15
    umap_clustering_n_neighbors: int = 30
    umap_clustering_min_dist: float = 0.0
    umap_clustering_metric: str = "cosine"
    umap_clustering_random_state: int = 42

    hdbscan_min_cluster_size: int = 15
    hdbscan_min_samples: int = 5
    hdbscan_metric: str = "euclidean"
    hdbscan_algorithm: str = "best"
    hdbscan_cluster_selection_method: str = "eom"
    hdbscan_n_jobs: int = -1

    k_hdbscan_sampling: int = 5

    cluster_label_max_chars_per_chunk: int = 1500
    cluster_label_max_retries: int = 2
    cluster_label_prompt_version: str = "v1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
