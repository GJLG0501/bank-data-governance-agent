"""Real Spanish retrieval evaluation, separate from ingestion and offline tests."""
import json
import os
from pathlib import Path

import pytest

from scripts import new_bank_documents as docs
from scripts import new_bank_rag as rag

pytestmark=[pytest.mark.integration,pytest.mark.retrieval]
CASES=json.loads(rag.CASES_PATH.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def evaluation():
    value=os.environ.get('BANK_NEW_RAG_CONTEXT')
    if not value: pytest.skip('Explicit BANK_NEW_RAG_CONTEXT required')
    path=Path(value).resolve()
    assert path.is_relative_to(rag.runtime.LOCAL.resolve()) and path.name=='state.json'
    ctx=json.loads(path.read_text(encoding='utf-8'))
    _,state=rag.runtime.load_state(ctx['isolated_state'])
    bundle=json.loads((path.parent/'prepared_vectors.json').read_text(encoding='utf-8'))
    documents=docs.build_documents()
    embeddings,model=rag.probe()
    rag.validate_bundle(bundle,documents,model)
    retriever=rag.CatalogRetriever(state,documents,embeddings,model,model_id=rag.MODEL_ID,
        corpus_id=bundle['manifest']['corpus_id'],index_manifest=bundle['manifest'])
    report=rag.evaluate(retriever,CASES)
    rag.runtime.save(path.parent/'retrieval-evaluation.json',report)
    return report


@pytest.mark.parametrize('index,case',list(enumerate(CASES)),ids=[case['id'] for case in CASES])
def test_actual_scoped_spanish_retrieval(evaluation,index,case):
    result=evaluation['cases'][index]
    assert result['passed'],json.dumps(result,ensure_ascii=False)
    assert all(set(origins)<={'upstream_explicit','technical_inference','mvp_proposal'}
        for origins in result['assertion_origins'])
