from __future__ import annotations

from typing import TYPE_CHECKING, LiteralString, cast

import psycopg

from lakehouse.db.connection import pg_conn_str_with_timeouts, pg_connect
from lakehouse.db.pgvector_conn import get_pgvector_connection_string
from lakehouse.pipeline.enrichment import MIN_CHUNK_LENGTH
from lakehouse.schemas.agent import (
    BuscarDeclaracionesInput,
    BuscarDeclaracionesOutput,
    ClusterDetalle,
    ClusterResumen,
    ConsultarClusterInput,
    ConsultarClusterOutput,
    Evidencia,
    EvidenciaCluster,
    ExplorarTemasInput,
    ExplorarTemasOutput,
)
from lakehouse.services.rag_search import _embed_query

if TYPE_CHECKING:
    from pydantic import BaseModel

    from lakehouse.config import Settings

TOOL_NAMES = {"buscar_declaraciones", "explorar_temas", "consultar_cluster"}

TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "buscar_declaraciones": BuscarDeclaracionesInput,
    "explorar_temas": ExplorarTemasInput,
    "consultar_cluster": ConsultarClusterInput,
}


def _conn_str(settings: Settings) -> str:
    return get_pgvector_connection_string(
        settings.postgres_host,
        settings.postgres_port,
        settings.postgres_db,
        settings.postgres_user,
        settings.postgres_password,
    )


def _conn_str_with_timeouts(settings: Settings) -> str:
    return pg_conn_str_with_timeouts(
        _conn_str(settings),
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    )


def _latest_run_id(conn_str: str) -> str | None:
    with psycopg.connect(conn_str) as conn:
        row = conn.execute(
            "SELECT run_id FROM gold.clustering_runs "
            "WHERE status IN ('completed', 'partial') ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return str(row[0]) if row else None


def buscar_declaraciones(
    settings: Settings, entrada: BuscarDeclaracionesInput
) -> BuscarDeclaracionesOutput:
    query_vector = _embed_query(
        entrada.consulta, settings.ollama_base_url, settings.ollama_embed_model
    )
    embedding_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    where = ["LENGTH(chunk_text) >= %s"]
    params: list = [MIN_CHUNK_LENGTH]
    if entrada.fecha_inicio is not None:
        where.append("conference_date >= %s")
        params.append(entrada.fecha_inicio)
    if entrada.fecha_fin is not None:
        where.append("conference_date <= %s")
        params.append(entrada.fecha_fin)
    if entrada.participante:
        where.append("participant ILIKE %s")
        params.append(f"%{entrada.participante}%")
    where_sql = " AND ".join(where)

    sql = cast(
        "LiteralString",
        f"""
        SELECT chunk_key, chunk_text, conference_date, conference_id, participant, url,
            1 - (embedding <=> %s::vector) AS similarity,
            embedding_3d, cluster_id, pregunta_activa
        FROM gold.rag_corpus
        WHERE {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
    )
    full_params = [embedding_str, *params, embedding_str, entrada.top_k]

    with pg_connect(
        _conn_str(settings),
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    ) as conn:
        rows = conn.execute(sql, full_params).fetchall()

    evidencias = []
    for r in rows:
        embedding_3d_raw = r[7]
        embedding_3d = list(embedding_3d_raw) if embedding_3d_raw is not None else None
        evidencias.append(
            Evidencia(
                evidence_id=r[0],
                texto=r[1],
                fecha=r[2],
                conferencia=r[3],
                participante=r[4],
                url=r[5],
                similitud=float(r[6]),
                embedding_3d=embedding_3d,
                cluster_id=r[8],
                pregunta_activa=r[9] or "",
            )
        )
    return BuscarDeclaracionesOutput(evidencias=evidencias)


def explorar_temas(settings: Settings, entrada: ExplorarTemasInput) -> ExplorarTemasOutput:
    run_id = _latest_run_id(_conn_str_with_timeouts(settings))
    if run_id is None:
        return ExplorarTemasOutput(clusters=[])

    where = ["gl.clustering_run_id = %s", "gl.label_status = 'completed'"]
    params: list = [run_id]
    if entrada.texto:
        where.append("gl.cluster_label ILIKE %s")
        params.append(f"%{entrada.texto}%")
    where_sql = " AND ".join(where)
    params.append(entrada.limite)

    sql = cast(
        "LiteralString",
        f"""
        SELECT gl.cluster_id, gl.cluster_label,
               COUNT(g.chunk_key) AS tamano,
               AVG(g.cluster_pertenencia) AS cohesion,
               MIN(g.conference_date) AS fecha_inicio,
               MAX(g.conference_date) AS fecha_fin
        FROM gold.cluster_labels gl
        JOIN gold.rag_corpus g
          ON g.cluster_id = gl.cluster_id AND g.clustering_run_id = gl.clustering_run_id
        WHERE {where_sql}
        GROUP BY gl.cluster_id, gl.cluster_label
        ORDER BY tamano DESC
        LIMIT %s
        """,
    )

    with pg_connect(
        _conn_str(settings),
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    ) as conn:
        rows = conn.execute(sql, params).fetchall()

    clusters = [
        ClusterResumen(
            cluster_id=r[0],
            etiqueta=r[1],
            terminos=[r[1]] if r[1] else [],
            tamano=r[2],
            cohesion=round(float(r[3]), 4) if r[3] is not None else None,
            fecha_inicio=r[4],
            fecha_fin=r[5],
        )
        for r in rows
    ]
    return ExplorarTemasOutput(clusters=clusters)


def consultar_cluster(settings: Settings, entrada: ConsultarClusterInput) -> ConsultarClusterOutput:
    run_id = _latest_run_id(_conn_str_with_timeouts(settings))
    if run_id is None:
        return ConsultarClusterOutput(
            cluster=ClusterDetalle(cluster_id=entrada.cluster_id, etiqueta=None, tamano=0),
            evidencias=[],
        )

    with pg_connect(
        _conn_str(settings),
        connect_timeout=settings.db_connect_timeout,
        statement_timeout_ms=settings.db_statement_timeout_ms,
    ) as conn:
        meta = conn.execute(
            "SELECT gl.cluster_label, COUNT(g.chunk_key) "
            "FROM gold.cluster_labels gl "
            "JOIN gold.rag_corpus g "
            "  ON g.cluster_id = gl.cluster_id AND g.clustering_run_id = gl.clustering_run_id "
            "WHERE gl.clustering_run_id = %s AND gl.cluster_id = %s "
            "GROUP BY gl.cluster_id, gl.cluster_label",
            (run_id, entrada.cluster_id),
        ).fetchone()

        if meta is None:
            return ConsultarClusterOutput(
                cluster=ClusterDetalle(cluster_id=entrada.cluster_id, etiqueta=None, tamano=0),
                evidencias=[],
            )

        label, tamano = meta[0], meta[1]
        rows = conn.execute(
            "SELECT chunk_key, chunk_text, conference_date, participant, url, "
            "cluster_pertenencia, embedding_3d, pregunta_activa "
            "FROM gold.rag_corpus WHERE clustering_run_id = %s AND cluster_id = %s "
            "ORDER BY cluster_pertenencia DESC NULLS LAST, chunk_key LIMIT %s",
            (run_id, entrada.cluster_id, entrada.limite),
        ).fetchall()

    evidencias = []
    for r in rows:
        embedding_3d_raw = r[6]
        embedding_3d = list(embedding_3d_raw) if embedding_3d_raw is not None else None
        evidencias.append(
            EvidenciaCluster(
                evidence_id=r[0],
                texto=r[1],
                fecha=r[2],
                participante=r[3],
                url=r[4],
                pertenencia=round(float(r[5]), 4) if r[5] is not None else None,
                embedding_3d=embedding_3d,
                pregunta_activa=r[7] or "",
            )
        )
    return ConsultarClusterOutput(
        cluster=ClusterDetalle(cluster_id=entrada.cluster_id, etiqueta=label, tamano=tamano),
        evidencias=evidencias,
    )
