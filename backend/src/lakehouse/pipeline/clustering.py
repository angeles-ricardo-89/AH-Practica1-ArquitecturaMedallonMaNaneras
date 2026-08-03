from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import psycopg
import umap
from hdbscan import HDBSCAN
from sklearn.preprocessing import normalize

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="gold")


def ensure_clustering_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_id INTEGER NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS cluster_pertenencia REAL NULL
    """)
    cur.execute("""
        ALTER TABLE gold.rag_corpus
        ADD COLUMN IF NOT EXISTS clustering_run_id UUID NULL
    """)
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_cluster_pertenencia_range'
            ) THEN
                ALTER TABLE gold.rag_corpus
                ADD CONSTRAINT chk_cluster_pertenencia_range
                CHECK (cluster_pertenencia IS NULL OR (cluster_pertenencia >= 0.0 AND cluster_pertenencia <= 1.0));
            END IF;
        END $$;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.clustering_runs (
            run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            status              VARCHAR NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running','completed','failed','partial')),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at         TIMESTAMPTZ,
            input_count         INTEGER NOT NULL DEFAULT 0,
            valid_count         INTEGER NOT NULL DEFAULT 0,
            rejected_count      INTEGER NOT NULL DEFAULT 0,
            cluster_count       INTEGER NOT NULL DEFAULT 0,
            noise_count         INTEGER NOT NULL DEFAULT 0,
            labeled_cluster_count INTEGER NOT NULL DEFAULT 0,
            failed_label_count  INTEGER NOT NULL DEFAULT 0,
            corpus_fingerprint  VARCHAR NOT NULL DEFAULT '',
            parameters_hash     VARCHAR NOT NULL DEFAULT '',
            embedding_model     VARCHAR NOT NULL DEFAULT '',
            umap_parameters     JSONB NOT NULL DEFAULT '{}',
            hdbscan_parameters  JSONB NOT NULL DEFAULT '{}',
            labeling_parameters JSONB NOT NULL DEFAULT '{}',
            error_message       TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.cluster_labels (
            clustering_run_id   UUID NOT NULL REFERENCES gold.clustering_runs(run_id),
            cluster_id          INTEGER NOT NULL CHECK (cluster_id >= 0),
            cluster_label       VARCHAR,
            label_status        VARCHAR NOT NULL DEFAULT 'pending'
                                CHECK (label_status IN ('pending','completed','failed')),
            sample_size         INTEGER NOT NULL DEFAULT 0,
            sample_chunk_keys   TEXT[] NOT NULL DEFAULT '{}',
            model_name          VARCHAR DEFAULT '',
            prompt_version      VARCHAR DEFAULT '',
            attempt_count       INTEGER NOT NULL DEFAULT 0,
            error_message       TEXT DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (clustering_run_id, cluster_id)
        )
    """)
    conn.commit()
