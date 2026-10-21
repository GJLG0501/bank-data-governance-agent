import json

import pytest

from scripts import knowledge_corpus as corpus

pytestmark = pytest.mark.retrieval
CASES = json.loads(corpus.CASES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def retrieval_session():
    with corpus.RetrievalSession() as session:
        yield session


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_actual_ollama_pgvector_retrieval(retrieval_session, case):
    results = retrieval_session.search(case["question"], case["k"])
    pointers = {result["metadata"]["json_pointer"] for result in results}
    assert set(case["expected_pointers"]) <= pointers
    assert all(result["source"] == corpus.SOURCE for result in results)
    assert all(result["source_version"] == "1.0" for result in results)
    assert all(result["metadata"]["embedding_digest"] == retrieval_session.model.digest for result in results)
    distances = [result["cosine_distance"] for result in results]
    assert distances == sorted(distances)
    if case["name"] == "credit_score_absence":
        absence = next(result for result in results if result["metadata"]["json_pointer"] in case["expected_pointers"])
        assert absence["metadata"]["kind"] == "explicit_absence"
        assert "There is no CUSTOMER.credit_score field." in absence["content"]
