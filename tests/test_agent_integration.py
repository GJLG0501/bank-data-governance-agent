from bank_governance.security import simulated_access
import json

import pytest

from scripts import data_steward_agent as steward
from scripts import knowledge_corpus as corpus

pytestmark = pytest.mark.agent
CASES = json.loads((corpus.ROOT / "tests/fixtures/agent_cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live_agent():
    with steward.agent_session(security=simulated_access(),data_model='legacy_metadata') as agent:
        yield agent


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_local_llama_agent_uses_evidence_and_supported_capabilities(live_agent, case):
    live_agent.history.clear()
    reply = live_agent.ask(case["question"])
    assert reply.status == case["status"]
    if case["status"] == "capability_unavailable":
        assert reply.tool_calls == 0
        assert reply.references == []
    else:
        assert 1 <= reply.tool_calls <= 2
    if case["pointer"]:
        assert case["pointer"] in {ref["json_pointer"] for ref in reply.references}
        by_document = {e["document_id"]: e for e in reply.evidence}
        for ref in reply.references:
            assert ref["source"] == corpus.SOURCE
            assert ref["source_version"] == "1.0"
            assert ref["document_id"] in by_document
            assert ref["json_pointer"] == by_document[ref["document_id"]]["json_pointer"]
        if case["status"] == "explicit_absence":
            assert any(ref["kind"] == "explicit_absence" for ref in reply.references)
    else:
        assert reply.references == []
    # No se exige una redaccion exacta ni una puntuacion especifica del modelo.
    assert reply.answer.strip()


def test_real_followup_reuses_only_session_context(live_agent):
    live_agent.history.clear()
    first = live_agent.ask("¿Qué significa CUSTOMER.annual_income?")
    followup = live_agent.ask("¿Y en qué unidad se expresa?")
    assert first.status == followup.status == "grounded"
    assert any(ref["json_pointer"] == "/tables/CUSTOMER/fields/annual_income" for ref in followup.references)
    assert followup.tool_calls >= 1
