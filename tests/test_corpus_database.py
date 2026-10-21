from dataclasses import replace

import pytest
from psycopg import sql

from scripts import bank_data as bank
from scripts import knowledge_corpus as corpus

pytestmark = pytest.mark.integration


class StorageTestEmbeddings:
    """Solo para contratos de persistencia, nunca para evaluar recuperacion real."""
    calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [[1.0, 2.0, 3.0] for _ in texts]


def test_ingestion_is_atomic_idempotent_and_separate(isolated_database, metadata):
    conn, schema = isolated_database
    before = bank.fetch_data(conn, metadata, schema)
    documents = corpus.build_documents()
    embeddings = StorageTestEmbeddings()
    model = corpus.ModelIdentity("storage-test", "digest-a", 3)
    first = corpus.ingest(conn, documents, embeddings, model, schema)
    calls = embeddings.calls
    second = corpus.ingest(conn, documents, embeddings, model, schema)
    assert first["documents"] == second["documents"] == 24
    assert first["corpus_id"] == second["corpus_id"]
    assert second["status"] == "sin cambios"
    assert embeddings.calls == calls
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.documents").format(sql.Identifier(schema))).fetchone()[0] == 24
    assert bank.fetch_data(conn, metadata, schema) == before


def test_different_models_get_different_corpora(isolated_database):
    conn, schema = isolated_database
    documents = corpus.build_documents()
    model = corpus.ModelIdentity("storage-test", "digest-a", 3)
    embeddings = StorageTestEmbeddings()
    first = corpus.ingest(conn, documents, embeddings, model, schema)
    second = corpus.ingest(conn, documents, embeddings, replace(model, digest="digest-b"), schema)
    assert first["corpus_id"] != second["corpus_id"]
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.documents").format(sql.Identifier(schema))).fetchone()[0] == 48


def test_dimension_mismatch_is_refused(isolated_database):
    conn, schema = isolated_database
    corpus.initialize_storage(conn, 3, schema)
    with pytest.raises(ValueError, match="dimension incompatible"):
        corpus.initialize_storage(conn, 4, schema)


def test_existing_content_is_never_silently_replaced(isolated_database):
    conn, schema = isolated_database
    documents = corpus.build_documents()
    model = corpus.ModelIdentity("storage-test", "digest-a", 3)
    embeddings = StorageTestEmbeddings()
    corpus.ingest(conn, documents, embeddings, model, schema)
    conn.execute(sql.SQL("UPDATE {}.documents SET content='changed only in rollback test' WHERE id=(SELECT min(id::text)::uuid FROM {}.documents)").format(
        sql.Identifier(schema), sql.Identifier(schema)))
    with pytest.raises(ValueError, match="no se sobrescribira"):
        corpus.ingest(conn, documents, embeddings, model, schema)


def test_failed_ingestion_rolls_back_manifest(isolated_database):
    conn, schema = isolated_database
    documents = corpus.build_documents()
    model = corpus.ModelIdentity("storage-test", "digest-a", 3)
    corpus.initialize_storage(conn, 3, schema)

    class FailingEmbeddings:
        calls = 0

        def embed_documents(self, texts):
            self.calls += 1
            if self.calls > 1:
                raise ValueError("simulated local embedding failure")
            return [[1.0, 2.0, 3.0] for _ in texts]

    with pytest.raises(ValueError, match="simulated"), conn.transaction():
        corpus.ingest(conn, documents, FailingEmbeddings(), model, schema)
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.corpora").format(sql.Identifier(schema))).fetchone()[0] == 0
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.documents").format(sql.Identifier(schema))).fetchone()[0] == 0


def test_database_write_failure_rolls_back_partial_documents(isolated_database):
    conn, schema = isolated_database
    corpus.initialize_storage(conn, 3, schema)
    conn.execute(sql.SQL("""
        CREATE FUNCTION {}.reject_field() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.metadata ->> 'kind' = 'field' THEN
                RAISE EXCEPTION 'simulated corpus write failure';
            END IF;
            RETURN NEW;
        END $fn$;
        CREATE TRIGGER reject_field BEFORE INSERT ON {}.documents
        FOR EACH ROW EXECUTE FUNCTION {}.reject_field();
    """).format(sql.Identifier(schema), sql.Identifier(schema), sql.Identifier(schema)))
    import psycopg
    with pytest.raises(psycopg.Error), conn.transaction():
        corpus.ingest(conn, corpus.build_documents(), StorageTestEmbeddings(),
                      corpus.ModelIdentity("storage-test", "digest-a", 3), schema)
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.corpora").format(sql.Identifier(schema))).fetchone()[0] == 0
    assert conn.execute(sql.SQL("SELECT count(*) FROM {}.documents").format(sql.Identifier(schema))).fetchone()[0] == 0
