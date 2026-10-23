"""Architecture acceptance without PostgreSQL, Ollama or cloud requests."""
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from langchain_core.messages import AIMessage

from bank_governance import providers,config,coordinator,hybrid
from bank_governance.context import TurnContext
from bank_governance.contracts import (AtomicExplanation,AtomicClaim,VerificationOperation,
    AgentReply,SpecialistRequest,Evidence)
from bank_governance.errors import AgentError,ProviderError
from bank_governance.retrieval import HybridRetriever,contextual_query
from bank_governance.security import simulated_access
from scripts import new_bank_documents as docs,new_bank_rag as rag


@pytest.fixture
def backend():
    manifest=json.loads(rag.INDEX_PATH.read_text(encoding='utf-8'))
    model=rag.legacy.ModelIdentity(**manifest['embedding_model'])
    _,stored=docs.storage_documents(docs.build_documents(),model)
    return SimpleNamespace(expected={d.id:d for d in stored},corpus_id=manifest['corpus_id'],
        search=Mock(return_value=[]))


def test_config_separates_model_from_embeddings(monkeypatch):
    monkeypatch.setattr(config,'dotenv_values',lambda *_args,**_kw:{})
    c=config.load_config({'BANK_LLM_MODEL':'another-local','OLLAMA_EMBEDDING_MODEL':'unchanged'})
    assert c.model=='another-local' and c.context==8192 and c.provider=='ollama'
    assert 'key' not in c.model_dump()
    assert config.DEFAULT_DATA_MODEL=='legacy_metadata'


@pytest.mark.parametrize('env',[{'BANK_LLM_PROVIDER':'other'},{'BANK_LLM_CONTEXT':'-1'},
    {'BANK_LLM_TIMEOUT':'0'},{'BANK_LLM_PROVIDER':'gemini'}])
def test_invalid_configuration_rejected(env,monkeypatch):
    monkeypatch.setattr(config,'dotenv_values',lambda *_args,**_kw:{})
    with pytest.raises(ValueError):config.load_config(env)


def test_local_factory_verifies_identity_tools_and_context():
    client=Mock();client.show.return_value=SimpleNamespace(capabilities=['tools'])
    factory=Mock();local=Mock();digest=Mock(return_value='digest')
    h=providers.create_model(config.LLMConfig(),client_cls=Mock(return_value=client),
                             digest_fn=digest,ollama_cls=local,remote_cls=factory)
    assert h.identity['digest']=='digest'
    assert local.call_args.kwargs['num_ctx']==8192
    factory.assert_not_called()


def test_local_incompatibility_has_no_fallback():
    client=Mock();client.show.return_value=SimpleNamespace(capabilities=[]);cloud=Mock()
    with pytest.raises(ProviderError,match='no declara soporte'):
        providers.create_model(config.LLMConfig(),client_cls=Mock(return_value=client),
            digest_fn=Mock(return_value='id'),remote_cls=cloud)
    cloud.assert_not_called()


def test_remote_factory_mock_no_invoke_no_secret_in_identity():
    remote=Mock();remote.return_value=Mock()
    handle=providers.create_model(config.LLMConfig(provider='gemini',model='test-gemini',allow_cloud=True),
        remote_cls=remote,environ={'GOOGLE_API_KEY':'secret-fixture'})
    assert remote.call_args.kwargs['vertexai'] is False
    remote.return_value.invoke.assert_not_called()
    assert 'secret-fixture' not in repr(handle)
    assert handle.identity['digest'] is None


def test_remote_needs_explicit_authorization_and_credentials():
    remote=Mock()
    with pytest.raises(ProviderError,match='BANK_ALLOW_CLOUD'):
        providers.create_model(config.LLMConfig(provider='gemini',model='g'),remote_cls=remote,environ={})
    with pytest.raises(ProviderError,match='credencial'):
        providers.create_model(config.LLMConfig(provider='gemini',model='g',allow_cloud=True),remote_cls=remote,environ={})
    remote.assert_not_called()


def test_context_advances_period_without_carrying_evidence():
    c=TurnContext('new_bank_2026','corpus').begin('Define cfg.fact_sdos_captacoloca_m.saldo_apertura en abril')
    c.accept(AgentReply('grounded','old fact',references=[{'json_pointer':'/entries/temporal.opening_balance'}],
                       evidence=[{'document_id':'old-doc'}]))
    c.begin('¿Y en el mes siguiente?')
    assert c.period=='mayo' and c.pending_referent
    assert c.evidence_ids==[] and 'old fact' not in repr(c.public_state())
    assert c.identifiers==['cfg.fact_sdos_captacoloca_m.saldo_apertura']


@pytest.mark.parametrize('q',['¿Cuál es el cierre que abre mayo?',
    '¿Qué cierre inicia abril?','¿Cómo empieza el saldo de junio?'])
def test_general_indirect_retrieval(backend,q):
    r=HybridRetriever(backend,security=simulated_access());results=r.search(q,k=5)
    ids={x['metadata']['entry_id'] for x in results}
    assert 'temporal.opening_balance' in ids or 'field.cfg.fact_sdos_captacoloca_m.saldo_apertura' in ids
    assert backend.search.call_count<=2 and len(results)<=5
    assert all(x['metadata']['corpus_id']==backend.corpus_id for x in results)


def test_retrieval_unknown_field_and_unrelated_stay_empty(backend):
    r=HybridRetriever(backend,security=simulated_access())
    assert r.search('dim.dim_cliente.color_favorito')==[]
    assert r.search('Receta de tortilla')==[]
    backend.search.assert_not_called()


def test_indirect_followup_uses_structured_temporal_referent(backend):
    context=TurnContext('new_bank_2026',backend.corpus_id,period='mayo',concepts=['/entries/temporal.calendar'])
    context.begin('¿Y en el mes siguiente?')
    results=HybridRetriever(backend,context,security=simulated_access()).search('¿Qué ocurre después?',k=5)
    assert context.period=='junio'
    assert any('opening_balance' in x['metadata']['entry_id'] or 'saldo_apertura' in x['metadata']['entry_id'] for x in results)


def test_lexical_scope_is_mandatory(backend):
    next(iter(backend.expected.values())).metadata['model_id']='other'
    with pytest.raises(ValueError,match='scope'):HybridRetriever(backend,security=simulated_access()).search('saldo_apertura marzo')


@pytest.mark.parametrize('kind,entry,kwargs,expected',[
    ('calendar_previous','temporal.opening_balance',{'period':'abril'},'marzo'),
    ('transaction_sign','transaction.TDC.300',{'product':'TDC','code':300},'-1'),
    ('physical_nullability','field.cfg.fact_sdos_captacoloca_m.fec_informacion',
     {'identifier':'cfg.fact_sdos_captacoloca_m.fec_informacion'},'true'),
    ('formula_identity','rule.amounts.personal',{'expression':'pago=ROUND(anterior*0.05,2)'},'pago=ROUND(anterior*0.05,2)')])
def test_verifiable_operations_use_cited_sources(backend,kind,entry,kwargs,expected):
    source=next(d for d in backend.expected.values() if d.metadata['entry_id']==entry)
    op=VerificationOperation(kind=kind,expected=expected,**kwargs)
    assert hybrid.verify_operation(op,[source])[0]
    assert not hybrid.verify_operation(op.model_copy(update={'expected':'incorrect'}),[source])[0]
    assert not hybrid.verify_operation(op,[])[0]


def atomic_agent(backend,entry):
    doc=next(d for d in backend.expected.values() if d.metadata['entry_id']==entry)
    evidence=Evidence('E1',doc.id,doc.page_content,doc.metadata['source'],'1',None,None,
        doc.metadata['json_pointer'],doc.metadata['kind'],None,model_id='new_bank_2026',
        corpus_id=backend.corpus_id,claims=doc.metadata['claims'])
    return SimpleNamespace(_evidence={doc.id:evidence},retriever=backend)


def test_documented_absence_does_not_disappear_with_model_abstention(backend):
    a=atomic_agent(backend,'absence.currency')
    reply=hybrid.ground_atomic(a,'¿Cuál es la moneda?',AtomicExplanation(status='insufficient_evidence',claims=[]),1)
    assert reply.status=='explicit_absence' and reply.references and 'no especifican' in reply.answer
    other=hybrid.ground_atomic(a,'Describe segmento',AtomicExplanation(status='insufficient_evidence',claims=[]),1)
    assert other.status=='insufficient_evidence'


def test_operation_validation_does_not_certify_generated_sentence(backend):
    a=atomic_agent(backend,'temporal.opening_balance')
    draft=AtomicExplanation(status='answer',claims=[AtomicClaim(text='Una explicación propuesta.',
        evidence_ids=['E1'],claim_type='inference',operation=VerificationOperation(
            kind='calendar_previous',period='abril',expected='marzo'))])
    reply=hybrid.ground_atomic(a,'Explica abril',draft,1)
    assert reply.status=='explanation_requires_review'
    assert reply.validation_results[0]['validation']=='operation_verified_semantics_unverified'
    assert 'pendiente' in reply.answer and 'marzo' in reply.answer
    bad=draft.model_copy(update={'claims':[draft.claims[0].model_copy(update={'evidence_ids':['E999']})]})
    with pytest.raises(AgentError,match='inexistente'):hybrid.ground_atomic(a,'Explica abril',bad,1)


def test_graph_uses_only_real_steward_without_extra_model():
    steward=Mock();steward.data_model='new_bank_2026';steward.ask.return_value=AgentReply('grounded','catalog',references=[{'source':'valid'}])
    graph=coordinator.build_graph(steward)
    out=graph.invoke({'request':SpecialistRequest(question='Define saldo_apertura',model_id='new_bank_2026').model_dump()})
    assert out['result']['references']==[{'source':'valid'}]
    assert out['result']['specialist']=='data_steward'
    assert steward.ask.call_count==1


@pytest.mark.parametrize('capability,question',[('analytics','Compara saldos'),('quality','Busca duplicados'),
    ('catalog','Calcula el promedio de saldos'),('catalog','Detecta anomalías de fechas')])
def test_graph_never_improvises_unimplemented_capabilities(capability,question):
    steward=Mock();graph=coordinator.build_graph(steward)
    result=graph.invoke({'request':SpecialistRequest(question=question,capability=capability).model_dump()})['result']
    assert result['status']=='capability_unavailable'
    steward.ask.assert_not_called()


def test_graph_sanitizes_errors_and_rejects_model_mismatch():
    steward=Mock();steward.data_model='legacy_metadata';steward.ask.side_effect=AgentError('secret-input')
    graph=coordinator.build_graph(steward)
    result=graph.invoke({'request':SpecialistRequest(question='Define income').model_dump()})['result']
    assert result['status']=='error' and 'secret-input' not in repr(result)
    result=graph.invoke({'request':SpecialistRequest(question='Define saldo',model_id='new_bank_2026').model_dump()})['result']
    assert result['status']=='error' and steward.ask.call_count==1


def test_observability_logs_usage_without_content_or_thoughts():
    events=[];handle=providers.ModelHandle(Mock(),{'provider':'ollama','name':'local'},config.LLMConfig())
    runnable=Mock()
    def invoke(messages,config):
        callback=config['callbacks'][0]
        callback.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=AIMessage(
            content='secret reasoning',usage_metadata={'input_tokens':8192,'output_tokens':10,'total_tokens':8202}))]]))
        return 'done'
    runnable.invoke.side_effect=invoke
    assert providers.ObservedRunnable(runnable,handle,events.append,'test').invoke([SimpleNamespace(content='private question')])=='done'
    assert events[0]['possible_truncation'] and events[0]['input_tokens']==8192
    assert 'secret' not in repr(events) and 'private' not in repr(events)


def test_graph_disables_remote_tracing(monkeypatch):
    from langsmith import get_tracing_context
    monkeypatch.setenv('LANGSMITH_TRACING','true')
    steward=Mock();steward.data_model='legacy_metadata'
    def ask(_question):
        assert get_tracing_context()['enabled'] is False
        return AgentReply('grounded','safe')
    steward.ask.side_effect=ask
    coordinator.build_graph(steward).invoke({'request':SpecialistRequest(question='Define income').model_dump()})


def test_new_cli_passes_explicit_modes_through_graph(capsys):
    from contextlib import contextmanager
    from bank_governance.cli import main
    captured={};agent=Mock();agent.data_model='new_bank_2026'
    agent.ask.return_value=AgentReply('grounded','catalog',references=[{'source':'safe'}])
    @contextmanager
    def session(**kwargs):
        captured.update(kwargs)
        yield agent
    assert main(['ask','Define saldo_apertura','--data-model','new_bank_2026',
                 '--retrieval-mode','hybrid','--coordinator','--json'],session_factory=session)==0
    assert captured['retrieval_mode']=='hybrid' and captured['response_mode']=='extractive'
    assert json.loads(capsys.readouterr().out)['references']==[{'source':'safe'}]


def test_provider_binding_incompatibility_is_explicit():
    model=Mock();model.bind_tools.side_effect=NotImplementedError('secret-payload')
    handle=providers.ModelHandle(model,{'provider':'gemini','name':'test'},config.LLMConfig())
    with pytest.raises(ProviderError,match='herramientas') as error:
        providers.ObservedModel(handle,lambda e:None).bind_tools([])
    assert 'secret-payload' not in str(error.value)
