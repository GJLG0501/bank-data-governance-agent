"""Opt-in actual retrieval from the pinned published RAG; no SQL writes."""
import json
import os
from pathlib import Path

import pytest

from scripts import new_bank_rag as rag
from scripts import new_bank_rag_publication as publication
from bank_governance.security import simulated_access

pytestmark=[pytest.mark.integration,pytest.mark.retrieval]
CASES=json.loads(rag.CASES_PATH.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def report():
    value=os.environ.get('BANK_NEW_RAG_PUBLICATION_STATE')
    if not value: pytest.skip('Explicit BANK_NEW_RAG_PUBLICATION_STATE required')
    path=Path(value).resolve()
    assert path.is_relative_to(rag.runtime.LOCAL.resolve()) and path.name=='state.json'
    state=json.loads(path.read_text(encoding='utf-8'))
    assert path.parent.name=='rag_publication_'+state['run_id'] and state['status']=='published_verified'
    # Publication's historical preflight pins the agent's former source hash.
    # Agent integration intentionally changes it; this regression validates the
    # immutable corpus through its own scoped, read-only session instead.
    from scripts.steward_catalog import catalog_session
    with catalog_session('new_bank_2026',security=simulated_access()) as retriever:
        output=rag.evaluate(retriever,CASES)
    rag.runtime.save(path.parent/'published-retrieval.json',output)
    return output


@pytest.mark.parametrize('index,case',list(enumerate(CASES)),ids=[case['id'] for case in CASES])
def test_published_scoped_retrieval(report,index,case):
    outcome=report['cases'][index]
    assert outcome['passed'],json.dumps(outcome,ensure_ascii=False)
