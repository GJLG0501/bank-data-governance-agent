"""Small opt-in local acceptance. SELECT-only corpus retrieval, no ingestion."""
from bank_governance.security import simulated_access
import json
import pytest
from bank_governance.steward import agent_session
from scripts import new_bank_runtime_validation as rt

pytestmark=pytest.mark.agent


def save(rows):
    folder=rt.LOCAL/'architecture-live-results.json'
    folder.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def test_small_local_integration():
    rows=[];events=[]
    try:
        with agent_session(security=simulated_access(),data_model='new_bank_2026',retrieval_mode='hybrid',debug=events.append) as agent:
            for question in ['¿Qué moneda especifican los SQL?',
                             '¿Cuál es el cierre que abre mayo?', '¿Y en el mes siguiente?']:
                reply=agent.ask(question);rows.append({'question':question,**reply.to_dict()})
                assert reply.references,reply.to_dict()
                assert all(ref['model_id']=='new_bank_2026' for ref in reply.references)
            # Retrieval coverage is separate from the LLM's choice of extracts.
            assert any('temporal.opening_balance' in ref['json_pointer'] or 'saldo_apertura' in ref['json_pointer']
                       for ref in rows[1]['evidence'])
        with agent_session(security=simulated_access(),data_model='new_bank_2026',response_mode='hybrid_experimental',
                           retrieval_mode='hybrid',debug=events.append) as agent:
            absence=agent.ask('¿Cuál es la moneda?');rows.append({'question':'moneda híbrida',**absence.to_dict()})
            assert absence.status=='explicit_absence' and absence.references
            explanation=agent.ask('¿Qué cierre representa saldo_apertura en abril?')
            rows.append({'question':'apertura abril híbrida',**explanation.to_dict()})
            assert explanation.status in ('grounded','explanation_requires_review'),explanation.to_dict()
            assert explanation.validation_results and explanation.references
    finally:
        save({'responses':rows,'events':events})
