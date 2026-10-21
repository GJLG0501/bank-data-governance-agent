-- Plantilla aplicada por scripts.knowledge_corpus DESPUES de medir el modelo.
-- {dimension} es un entero validado; {schema} se cita como identificador SQL.
-- No cambia las tablas bancarias ni la extension vector.
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.corpora (
    corpus_id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{{64}}$'),
    renderer_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_digest TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension BETWEEN 1 AND 16000),
    document_count INTEGER NOT NULL CHECK (document_count > 0)
);

CREATE TABLE IF NOT EXISTS {schema}.documents (
    id UUID PRIMARY KEY,
    corpus_id UUID NOT NULL REFERENCES {schema}.corpora(corpus_id) ON DELETE RESTRICT,
    content TEXT NOT NULL CHECK (length(content) > 0),
    metadata JSONB NOT NULL CHECK (
        jsonb_typeof(metadata) = 'object' AND metadata ?& ARRAY[
            'source', 'source_version', 'source_sha256', 'table', 'field', 'kind',
            'json_pointer', 'renderer_version', 'chunk_sha256', 'document_id',
            'embedding_model', 'embedding_digest', 'embedding_dimension'
        ]
    ),
    embedding public.vector({dimension}) NOT NULL
);

CREATE INDEX IF NOT EXISTS bank_knowledge_documents_corpus_idx
    ON {schema}.documents(corpus_id);
