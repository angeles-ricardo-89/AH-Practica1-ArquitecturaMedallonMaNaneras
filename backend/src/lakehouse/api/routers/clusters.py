import psycopg
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.schemas.cluster import ClusterDataResponse, ClusterInfo, ClusterPoint

router = APIRouter(tags=["clusters"])


def _get_pg_conn_str() -> str:
    settings = Settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _fetch_cluster_data(conn_str: str, run_id: str | None = None) -> ClusterDataResponse:
    with psycopg.connect(conn_str) as conn:
        cur = conn.cursor()
        if run_id:
            cur.execute(
                "SELECT run_id, status, cluster_count, noise_count "
                "FROM gold.clustering_runs WHERE run_id = %s",
                (run_id,),
            )
        else:
            cur.execute(
                "SELECT run_id, status, cluster_count, noise_count "
                "FROM gold.clustering_runs "
                "WHERE status IN ('completed', 'partial') "
                "ORDER BY started_at DESC LIMIT 1"
            )
        run_row = cur.fetchone()
        if not run_row:
            return ClusterDataResponse(
                run_id="",
                status="not_found",
                cluster_count=0,
                noise_count=0,
            )
        run_id_val, status, cluster_count, noise_count = run_row

        cur.execute(
            """
            SELECT gl.cluster_id, gl.cluster_label, gl.label_status,
                   gl.sample_size, gl.sample_chunk_keys
            FROM gold.cluster_labels gl
            WHERE gl.clustering_run_id = %s
            ORDER BY gl.cluster_id
        """,
            (run_id_val,),
        )
        label_rows = cur.fetchall()

        labels_map: dict[int, ClusterInfo] = {}
        for cid, label, ls, ss, sck in label_rows:
            labels_map[cid] = ClusterInfo(
                cluster_id=cid,
                label=label if ls == "completed" else None,
                sample_chunk_keys=list(sck) if sck else [],
            )

        cur.execute(
            """
            SELECT g.cluster_id, COUNT(*) AS cnt, AVG(g.cluster_pertenencia) AS avg_p
            FROM gold.rag_corpus g
            WHERE g.clustering_run_id = %s AND g.cluster_id IS NOT NULL
            GROUP BY g.cluster_id
            ORDER BY g.cluster_id
        """,
            (run_id_val,),
        )
        count_rows = cur.fetchall()

        for cid, cnt, avg_p in count_rows:
            if cid in labels_map:
                labels_map[cid].chunk_count = cnt
                labels_map[cid].avg_membership = round(float(avg_p), 4) if avg_p else 0.0
            else:
                labels_map[cid] = ClusterInfo(
                    cluster_id=cid,
                    chunk_count=cnt,
                    avg_membership=round(float(avg_p), 4) if avg_p else 0.0,
                )

        cur.execute(
            """
            SELECT g.chunk_key, g.cluster_id, g.cluster_pertenencia,
                   g.embedding_3d[1] AS x, g.embedding_3d[2] AS y, g.embedding_3d[3] AS z
            FROM gold.rag_corpus g
            WHERE g.clustering_run_id = %s AND g.embedding_3d IS NOT NULL
        """,
            (run_id_val,),
        )
        point_rows = cur.fetchall()

        points = [
            ClusterPoint(
                chunk_key=ck,
                cluster_id=int(cid) if cid is not None else -1,
                pertenencia=round(float(p), 4) if p else 0.0,
                x=round(float(x), 4) if x else 0.0,
                y=round(float(y), 4) if y else 0.0,
                z=round(float(z), 4) if z else 0.0,
            )
            for ck, cid, p, x, y, z in point_rows
            if x is not None and y is not None and z is not None
        ]

    return ClusterDataResponse(
        run_id=str(run_id_val),
        status=status,
        cluster_count=cluster_count,
        noise_count=noise_count,
        clusters=[labels_map[cid] for cid in sorted(labels_map)],
        points=points,
    )


@router.get(
    "/clusters/latest",
    response_model=ClusterDataResponse,
    summary="Get latest clustering run data",
    description="Returns cluster labels, points, and metadata for the most recent clustering run",
)
def get_clusters_latest() -> ClusterDataResponse:
    conn_str = _get_pg_conn_str()
    return _fetch_cluster_data(conn_str)


@router.get(
    "/clusters/{run_id}",
    response_model=ClusterDataResponse,
    summary="Get clustering run data by ID",
    description="Returns cluster labels, points, and metadata for a specific clustering run",
)
def get_clusters_by_run(run_id: str) -> ClusterDataResponse:
    conn_str = _get_pg_conn_str()
    return _fetch_cluster_data(conn_str, run_id=run_id)
