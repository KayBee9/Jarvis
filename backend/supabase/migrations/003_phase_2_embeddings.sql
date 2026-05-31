CREATE EXTENSION if not exists vector;

alter table memories
    add column if not exists embedding vector(384);

CREATE INDEX if not exists memories_embedding_idx
    ON memories 
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);