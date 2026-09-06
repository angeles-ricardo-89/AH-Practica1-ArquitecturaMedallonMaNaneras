import psycopg
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.db.connection import get_database_url, pg_conn_str_with_timeouts
from lakehouse.schemas.embeddings import Embedding3DPoint, Embedding3DResponse

router = APIRouter(tags=["embeddings"])


def _get_pg_conn_str() -> str:
    settings = Settings()
    base = get_database_url(settings)
    return pg_conn_str_with_timeouts(
        base,
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


@router.get(
    "/embeddings/3d",
    response_model=Embedding3DResponse,
    summary="Get 3D embedding coordinates",
    description="Returns UMAP-reduced 3D coordinates for all chunks in Gold layer",
)
def get_embeddings_3d() -> Embedding3DResponse:
    conn_str = _get_pg_conn_str()
    try:
        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT chunk_key, embedding_3d, conference_date "
                "FROM gold.rag_corpus WHERE embedding_3d IS NOT NULL"
            )
            rows = cur.fetchall()
    except (psycopg.Error, OSError):
        return Embedding3DResponse(points=[])

    points = [
        Embedding3DPoint(
            chunk_key=row[0],
            x=float(row[1][0]),
            y=float(row[1][1]),
            z=float(row[1][2]),
            conference_date=str(row[2]),
        )
        for row in rows
        if row[1] and len(row[1]) == 3
    ]
    return Embedding3DResponse(points=points)
