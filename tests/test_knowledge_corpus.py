from collections import Counter
from dataclasses import replace
import json
from types import SimpleNamespace
import uuid

from langchain_core.documents import Document
import pytest

from scripts import knowledge_corpus as corpus


@pytest.fixture
def documents():
    return corpus.build_documents()


def test_corpus_count_and_atomic_chunks(documents):
    assert Counter(doc.metadata["kind"] for doc in documents) == {
        "catalog": 1, "table": 3, "field": 14, "relationship": 2, "explicit_absence": 4}
    assert len({doc.id for doc in documents}) == 24
    assert max(len(doc.page_content) for doc in documents) < 1200


def test_all_catalog_content_is_preserved_exactly(documents):
    metadata = json.loads(corpus.METADATA_PATH.read_text(encoding="utf-8-sig"))
    by_pointer = {doc.metadata["json_pointer"]: json.loads(doc.page_content) for doc in documents}
    overview = by_pointer["/"]
    assert overview == {key: metadata[key] for key in ("dataset_name", "version", "description")}
    for table, definition in metadata["tables"].items():
        assert by_pointer[f"/tables/{table}"]["description"] == definition["description"]
        assert by_pointer[f"/tables/{table}"]["columns"] == list(definition["fields"])
        for field, spec in definition["fields"].items():
            pointer = f"/tables/{table}/fields/{field}"
            assert by_pointer[pointer] == {"field": f"{table}.{field}", "definition": spec}
            if "foreign_key" in spec:
                assert by_pointer[pointer + "/foreign_key"]["foreign_key"] == spec["foreign_key"]
    for index, absence in enumerate(metadata["known_absences_for_exercise"]):
        assert by_pointer[f"/known_absences_for_exercise/{index}"] == {"explicit_catalog_absence": absence}


def test_every_document_has_traceable_metadata(documents):
    for doc in documents:
        uuid.UUID(doc.id)
        assert doc.metadata["source"] == corpus.SOURCE
        assert doc.metadata["source_version"] == "1.0"
        assert len(doc.metadata["source_sha256"]) == 64
        assert doc.metadata["chunk_sha256"] == corpus.sha256(doc.page_content)
        assert {"table", "field", "kind", "json_pointer", "renderer_version"} <= doc.metadata.keys()


def test_absences_are_not_defined_fields(documents):
    credit = next(doc for doc in documents if doc.metadata["field"] == "credit_score")
    assert credit.metadata["table"] == "CUSTOMER"
    assert credit.metadata["kind"] == "explicit_absence"
    assert "There is no CUSTOMER.credit_score field." in credit.page_content
    fees = next(doc for doc in documents if doc.metadata["json_pointer"] == "/known_absences_for_exercise/0")
    assert "does not say whether" in fees.page_content
    assert all("credit_score" not in doc.page_content for doc in documents if doc.metadata["kind"] == "field")


def test_deterministic_ids_and_model_isolation(documents):
    assert documents == corpus.build_documents()
    model = corpus.ModelIdentity("test-embedding", "digest-a", 3)
    identifier, stored = corpus.storage_documents(documents, model)
    assert corpus.storage_documents(documents, model) == (identifier, stored)
    assert identifier != corpus.corpus_identity(documents, replace(model, digest="digest-b"))
    assert identifier != corpus.corpus_identity(documents, replace(model, dimension=4))
    assert set(doc.id for doc in stored).isdisjoint(doc.id for doc in documents)


def test_source_revision_produces_new_ids(documents, tmp_path):
    source = json.loads(corpus.METADATA_PATH.read_text(encoding="utf-8-sig"))
    source["version"] = "test-revision"
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    revised = corpus.build_documents(path)
    assert set(doc.id for doc in documents).isdisjoint(doc.id for doc in revised)


def test_document_artifact_is_reproducible(documents):
    saved = [json.loads(line) for line in corpus.CORPUS_PATH.read_text(encoding="utf-8").splitlines()]
    assert saved == [{"id": doc.id, "page_content": doc.page_content, "metadata": doc.metadata} for doc in documents]


@pytest.mark.parametrize("vectors,count,dimension", [
    ([[1.0, 2.0]], 1, 3), ([[0.0] * 3], 1, 3), ([[1.0, float("nan"), 2.0]], 1, 3),
    ([[1.0, float("inf"), 2.0]], 1, 3), ([], 1, 3), ([], 0, 0), ([], 0, 16001),
])
def test_invalid_vectors_are_rejected(vectors, count, dimension):
    with pytest.raises(ValueError):
        corpus.validate_vectors(vectors, count, dimension)


def test_retrieval_returns_sources_and_cosine_similarity():
    class StubStore:
        embeddings = SimpleNamespace(embed_query=lambda text: [1.0, 2.0, 3.0])

        def similarity_search_with_score_by_vector(self, vector, *, k, filter):
            assert filter == {"corpus_id": {"$eq": "only-this-corpus"}}
            assert k == 5
            return [(Document(id="id", page_content="original", metadata={
                "source": corpus.SOURCE, "source_version": "1.0", "corpus_id": "only-this-corpus"}), 0.25)]

    results = corpus.search_store(StubStore(), "question", "only-this-corpus", 3)
    assert results[0]["content"] == "original"
    assert results[0]["cosine_distance"] == 0.25
    assert results[0]["cosine_similarity"] == 0.75
    assert results[0]["source"] == corpus.SOURCE


@pytest.mark.parametrize("question,k", [("", 5), ("   ", 5), ("query", 0), ("query", 21)])
def test_invalid_queries_are_rejected(question, k):
    with pytest.raises(ValueError):
        corpus.search_store(None, question, "corpus", 3, k)
