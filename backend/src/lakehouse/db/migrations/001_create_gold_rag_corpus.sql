CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.rag_corpus (
    chunk_key        VARCHAR PRIMARY KEY,
    conference_id    VARCHAR NOT NULL,
    conference_date  DATE NOT NULL,
    participant      VARCHAR NOT NULL,
    chunk_text       TEXT NOT NULL,
    payload          TEXT NOT NULL,
    url              VARCHAR DEFAULT '',
    embedding        vector(768),
    ingested_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_corpus_conference_date ON gold.rag_corpus (conference_date);
CREATE INDEX IF NOT EXISTS idx_rag_corpus_participant ON gold.rag_corpus (participant);

CREATE INDEX IF NOT EXISTS idx_rag_corpus_embedding_hnsw
    ON gold.rag_corpus
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
