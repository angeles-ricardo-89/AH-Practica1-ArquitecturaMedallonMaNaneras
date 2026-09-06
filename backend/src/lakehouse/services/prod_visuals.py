from __future__ import annotations

from urllib.parse import unquote, urlsplit

from lakehouse.config import Settings
from lakehouse.db.pgvector_conn import build_neon_connection_string
from lakehouse.log_config import get_logger
from lakehouse.pipeline.clustering import run_clustering, run_labeling
from lakehouse.pipeline.enrichment import _compute_umap_3d

logger = get_logger(__name__, layer="service")


def target_settings(settings: Settings) -> Settings:
    """Devuelve Settings cuyos ``postgres_*`` apuntan a la base Neon objetivo.

    El codigo de clustering deriva su conexion de ``postgres_*``; para ejecutarlo
    contra Neon se reutilizan esos campos sin tocar las funciones existentes.
    """
    url = settings.neon_database_url
    if not url:
        raise RuntimeError("neon_database_url es obligatorio para sincronizar visuales")
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise RuntimeError("URL Neon sin host valido")
    target = Settings(app_env=settings.app_env)
    target.postgres_host = host
    target.postgres_port = parsed.port or 5432
    target.postgres_user = unquote(parsed.username or "")
    target.postgres_password = unquote(parsed.password or "")
    target.postgres_db = (parsed.path.lstrip("/").split("?")[0]) or "neondb"
    # El modelo de embedding real del indice objetivo es Gemini (no embeddinggemma).
    target.ollama_embed_model = settings.gemini_embedding_model or "gemini-embedding-001"
    return target


def sync_production_visuals(settings: Settings) -> dict[str, object]:
    """Recalcula embedding_3d y clusters sobre los embeddings GEMINI de Neon.

    Reutiliza el pipeline existente: UMAP-3D (enrichment), UMAP+HDBSCAN y
    etiquetado (clustering) apuntando la conexion a Neon. No toca el entorno local.
    """
    if not settings.neon_database_url:
        raise RuntimeError(
            "NEON_DATABASE_URL es obligatorio para sincronizar visuales de produccion"
        )
    conn_str = build_neon_connection_string(settings.neon_database_url)
    target = target_settings(settings)

    logger.info("Recalculando embedding_3d sobre Neon", corpus="gemini")
    updated_3d = _compute_umap_3d(conn_str)

    logger.info("Recalculando clustering sobre Neon", corpus="gemini")
    cluster_result = run_clustering(target, force=True)
    if cluster_result is None or "run_id" not in cluster_result:
        raise RuntimeError("Clustering no produjo un run_id")
    run_id = cluster_result["run_id"]

    label_result = run_labeling(target, run_id=str(run_id))
    logger.info(
        "Visuales productivas sincronizadas",
        updated_3d=updated_3d,
        clusters=cluster_result.get("clusters"),
        run_id=str(run_id),
        labels=label_result,
    )
    return {
        "embedding_3d_updated": updated_3d,
        "run_id": str(run_id),
        "clusters": cluster_result.get("clusters"),
        "noise": cluster_result.get("noise"),
        "labeling": label_result,
    }
