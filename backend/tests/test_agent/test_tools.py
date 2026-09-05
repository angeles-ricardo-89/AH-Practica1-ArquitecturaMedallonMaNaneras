from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import psycopg
import pytest

from lakehouse.config import Settings
from lakehouse.pipeline.clustering import ensure_clustering_schema
from lakehouse.schemas.agent import (
    BuscarDeclaracionesInput,
    ConsultarClusterInput,
    ExplorarTemasInput,
)
from lakehouse.services.agent.tools import (
    buscar_declaraciones,
    consultar_cluster,
    explorar_temas,
)

EMB = [0.0] * 768
EMB_STR = "[" + ",".join(["0.0"] * 768) + "]"


@pytest.fixture
def cluster_seed(pg_conn_str: str):
    run_id = str(uuid.uuid4())
    with psycopg.connect(pg_conn_str) as conn:
        ensure_clustering_schema(conn)
        conn.execute(
            "INSERT INTO gold.clustering_runs (run_id, status, cluster_count, noise_count) "
            "VALUES (%s, 'completed', 2, 0)",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO gold.cluster_labels "
            "(clustering_run_id, cluster_id, cluster_label, label_status) "
            "VALUES (%s, %s, %s, 'completed')",
            (run_id, 0, "energia"),
        )
        conn.execute(
            "INSERT INTO gold.cluster_labels "
            "(clustering_run_id, cluster_id, cluster_label, label_status) "
            "VALUES (%s, %s, %s, 'completed')",
            (run_id, 1, "salud"),
        )
        chunks = [
            ("agent_k1", "c1", "2025-01-01", "PARTICIPANTE A", "texto sobre energia electrica y reforma energetica nacional del pais", "u1", 0, 0.9),
            ("agent_k2", "c2", "2025-06-01", "PARTICIPANTE B", "otro texto sobre energia y la comision federal de electricidad de mexico", "u2", 0, 0.5),
            ("agent_k3", "c3", "2025-02-01", "PARTICIPANTE A", "texto sobre salud publica y el sistema nacional de vacunacion", "u3", 1, 0.8),
        ]
        for key, conf, dt, part, txt, url, cid, pert in chunks:
            conn.execute(
                "INSERT INTO gold.rag_corpus (chunk_key, conference_id, conference_date, "
                "participant, chunk_text, url, embedding, cluster_id, cluster_pertenencia, "
                "clustering_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (key, conf, dt, part, txt, url, EMB_STR, cid, pert, run_id),
            )
        conn.commit()
    yield run_id
    with psycopg.connect(pg_conn_str) as conn:
        conn.execute("DELETE FROM gold.cluster_labels WHERE clustering_run_id = %s", (run_id,))
        conn.execute("DELETE FROM gold.rag_corpus WHERE chunk_key LIKE 'agent_k%'")
        conn.execute("DELETE FROM gold.clustering_runs WHERE run_id = %s", (run_id,))
        conn.commit()


def test_explorar_temas_orders_by_size(cluster_seed) -> None:
    out = explorar_temas(Settings(), ExplorarTemasInput(limite=5))
    assert [c.cluster_id for c in out.clusters] == [0, 1]
    assert out.clusters[0].etiqueta == "energia"
    assert out.clusters[0].tamano == 2


def test_explorar_temas_filters_by_texto(cluster_seed) -> None:
    out = explorar_temas(Settings(), ExplorarTemasInput(texto="salud", limite=5))
    assert [c.cluster_id for c in out.clusters] == [1]


def test_consultar_cluster_returns_evidence_sorted(cluster_seed) -> None:
    out = consultar_cluster(Settings(), ConsultarClusterInput(cluster_id=0, limite=8))
    assert out.cluster.etiqueta == "energia"
    assert out.cluster.tamano == 2
    assert len(out.evidencias) == 2
    assert out.evidencias[0].pertenencia >= out.evidencias[1].pertenencia


def test_consultar_cluster_unknown(cluster_seed) -> None:
    out = consultar_cluster(Settings(), ConsultarClusterInput(cluster_id=99, limite=8))
    assert out.cluster.tamano == 0
    assert out.evidencias == []


def test_buscar_declaraciones_prefilters_date(cluster_seed) -> None:
    with patch("lakehouse.services.agent.tools._embed_query", return_value=EMB):
        out = buscar_declaraciones(
            Settings(),
            BuscarDeclaracionesInput(
                consulta="energia",
                fecha_inicio=date(2025, 5, 1),
                fecha_fin=date(2025, 12, 31),
                top_k=8,
            ),
        )
    assert all(e.fecha >= date(2025, 5, 1) for e in out.evidencias)
    assert all(e.fecha <= date(2025, 12, 31) for e in out.evidencias)


def test_buscar_declaraciones_prefilters_participante(cluster_seed) -> None:
    with patch("lakehouse.services.agent.tools._embed_query", return_value=EMB):
        out = buscar_declaraciones(
            Settings(),
            BuscarDeclaracionesInput(consulta="x", participante="PARTICIPANTE A", top_k=8),
        )
    assert out.evidencias
    assert all(e.participante == "PARTICIPANTE A" for e in out.evidencias)
