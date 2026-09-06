from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from lakehouse.db.index_metadata import read_index_metadata
from lakehouse.db.pgvector_conn import build_neon_connection_string
from lakehouse.services.gemini_embedding import RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY

if TYPE_CHECKING:
    from lakehouse.config import Settings
    from lakehouse.schemas.index_metadata import IndexMetadata

GOOGLE_PROVIDER = "google"


class IndexMetadataMismatchError(RuntimeError):
    pass


def build_corpus_hash(chunk_keys: list[str]) -> str:
    canonical = "".join(sorted(chunk_keys))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_query_config(
    metadata: IndexMetadata,
    *,
    provider: str,
    model: str,
    dimension: int,
    query_task_type: str,
) -> None:
    problems: list[str] = []
    if metadata.provider != provider:
        problems.append(f"provider '{metadata.provider}' != '{provider}'")
    if metadata.model != model:
        problems.append(f"model '{metadata.model}' != '{model}'")
    if metadata.dimension != dimension:
        problems.append(f"dimension {metadata.dimension} != {dimension}")
    if metadata.task_type != RETRIEVAL_DOCUMENT:
        problems.append(f"index task_type '{metadata.task_type}' != '{RETRIEVAL_DOCUMENT}'")
    if query_task_type != RETRIEVAL_QUERY:
        problems.append(f"query task_type '{query_task_type}' != '{RETRIEVAL_QUERY}'")
    if problems:
        raise IndexMetadataMismatchError("Index metadata mismatch: " + "; ".join(problems))


def validate_index_at_startup(settings: Settings) -> None:
    if not settings.is_production:
        return
    if not settings.neon_database_url:
        return
    conn_str = build_neon_connection_string(settings.neon_database_url)
    metadata = read_index_metadata(conn_str)
    if metadata is None:
        raise IndexMetadataMismatchError("No index metadata found in production database")
    validate_query_config(
        metadata,
        provider=GOOGLE_PROVIDER,
        model=settings.gemini_embedding_model,
        dimension=settings.gemini_embedding_dimension,
        query_task_type=RETRIEVAL_QUERY,
    )
