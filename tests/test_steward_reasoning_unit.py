"""Objective boundaries of the experimental response contract; no services."""
from types import SimpleNamespace

import pytest

from scripts import data_steward_agent as agent
from scripts.steward_reasoning_context import build_context


def test_general_calendar_validation():
    for month,prior in [('febrero','enero'),('marzo','febrero'),('abril','marzo'),
                        ('mayo','abril'),('junio','mayo')]:
        assert agent.valid_calendar_statement(f'Para {month}, saldo_apertura procede del cierre de {prior}.')
    assert not agent.valid_calendar_statement('Para abril, saldo_apertura procede del cierre de enero.')
    assert not agent.valid_calendar_statement('El cierre de marzo es el cierre de febrero.')
    assert not agent.valid_calendar_statement('El cierre de enero es el saldo inicial de la cuenta.')
    assert not agent.valid_calendar_statement('El cierre de febrero es el cierre del mes calendario anterior.')


def test_temporary_context_has_verified_sources_and_calendar():
    context=build_context()
    assert 'EXPERIMENTO' in context['label']
    assert len(context['calendar_examples'])==6
    assert context['calendar_examples'][0]['meaning']=='saldo inicial de la cuenta'
    assert context['calendar_examples'][3]['meaning']=='cierre de marzo'


def test_experimental_mode_is_explicit_and_scoped():
    model=SimpleNamespace(bind_tools=lambda _:None,with_structured_output=lambda *_args,**_kwargs:None)
    retriever=SimpleNamespace()
    with pytest.raises(ValueError,match='requiere new_bank_2026'):
        agent.DataStewardAgent(model,retriever,response_mode='grounded_generation_experimental')
    with pytest.raises(ValueError,match='contexto conceptual'):
        agent.DataStewardAgent(model,retriever,data_model='new_bank_2026',conceptual_context={})
    assert agent.DEFAULT_DATA_MODEL=='legacy_metadata'


def test_generated_reference_must_be_current_and_calendar_correct():
    model=SimpleNamespace(bind_tools=lambda _:None,with_structured_output=lambda *_args,**_kwargs:None)
    a=agent.DataStewardAgent(model,SimpleNamespace(),data_model='new_bank_2026',
                             response_mode='grounded_generation_experimental')
    a._evidence={'doc':agent.Evidence('E1','doc',
        'saldo_apertura desde febrero es cierre calendario anterior. En marzo representa cierre de febrero.',
        'catalog','1',None,None,'/entries/temporal.opening_balance','temporal_rule',None,
        model_id='new_bank_2026')}
    bad=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='Para abril, saldo_apertura procede del cierre de enero.',evidence_ids=['E1'])])
    assert a._ground_explanation('¿Y para abril?',bad,1).diagnostic=='all_statements_rejected'
    mixed=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='Para abril, saldo_apertura procede del cierre de marzo.',evidence_ids=['E1']),
        agent.GroundedStatement(text='Para abril, saldo_apertura procede del cierre de enero.',evidence_ids=['E1'])])
    partial=a._ground_explanation('¿Y para abril?',mixed,1)
    assert partial.status=='grounded' and partial.diagnostic=='filtered_unsupported_statements:1'
    assert 'cierre de marzo' in partial.answer and 'cierre de enero' not in partial.answer
    a._evidence['doc']=agent.Evidence('E1','doc','retiro=ROUND(anterior*0.05,2)',
        'catalog','1',None,None,'/entries/rule.amounts.deposits','financial_rule',None,
        model_id='new_bank_2026')
    percent=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='El retiro equivale al 5% del anterior.',evidence_ids=['E1'])])
    assert a._ground_explanation('¿Qué porcentaje?',percent,1).status=='grounded'
    labelled=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='El retiro equivale al 5% del anterior (E1).',evidence_ids=['E1'])])
    assert '(E1)' not in a._ground_explanation('¿Qué porcentaje?',labelled,1).answer
    free=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='El retiro equivale al 5% del anterior E999.',evidence_ids=['E1'])])
    assert a._ground_explanation('¿Qué porcentaje?',free,1).diagnostic=='all_statements_rejected'
    invented=agent.GroundedExplanation(status='grounded',statements=[
        agent.GroundedStatement(text='Una regla.',evidence_ids=['E999'])])
    with pytest.raises(agent.AgentError,match='inexistente'):
        a._ground_explanation('¿Cuál regla?',invented,1)
