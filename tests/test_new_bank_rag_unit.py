"""Offline semantic catalog/corpus, scope and exact vector integrity contracts."""
import copy
from dataclasses import replace
import json
import uuid

import pytest

from scripts import new_bank_catalog as c
from scripts import new_bank_documents as d
from scripts import new_bank_rag as rag
from scripts import knowledge_corpus as old


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def denied(*args,**kwargs):
        pytest.fail('Offline RAG test attempted a service connection')
    monkeypatch.setattr(rag.runtime,'docker',denied)
    monkeypatch.setattr('psycopg.connect',denied)
    monkeypatch.setattr('socket.create_connection',denied)


@pytest.fixture(scope='module')
def documents():
    return d.build_documents()


@pytest.fixture(scope='module')
def prepared(documents):
    class Embeddings:
        def embed_documents(self,texts):
            return [[1.0]+[0.0]*1023 for text in texts]
    model=old.ModelIdentity('bge-large:latest','test-only-digest',1024)
    return rag.prepare_vectors(documents,Embeddings(),model),model


def test_catalog_artifact_and_source_hashes():
    assert d.load_catalog()==c.build_catalog()
    assert len(c.ddl_tables(c.source_inventory()))==5
    assert c.validate_catalog(d.load_catalog())['field']==42


def test_every_physical_column_and_nullable_declaration_matches_source():
    value=d.load_catalog()
    for table,ddl in c.ddl_tables(value['sources']).items():
        for field,physical in ddl['columns'].items():
            entry=value['entries']['field.'+table+'.'+field]
            for key,item in physical.items():
                if key!='source_ref': assert entry['attributes'][key]==item
            ref=entry['claims'][0]['source_refs'][0]
            lines=(c.ROOT/ref['path']).read_text(encoding='utf-8').splitlines()
            assert lines[ref['line_start']-1].strip().startswith(field+' ')
    assert value['entries']['field.cfg.fact_txn_captacoloca_d.saldo_txn']['attributes']['nullable_upstream']
    assert not value['entries']['field.dim.dim_cliente.num_cte']['attributes']['nullable_upstream']


def test_catalogs_products_signs_and_provenance():
    value=d.load_catalog()
    assert {e['attributes']['product'] for e in value['entries'].values() if e['kind']=='product'}=={'CHEQUES','AHORRO','TDC','C_PERSONAL'}
    tx=[e for e in value['entries'].values() if e['kind']=='transaction']
    assert len(tx)==9 and len({(e['attributes']['product'],e['attributes']['code']) for e in tx})==9
    assert value['entries']['transaction.TDC.300']['attributes']['economic_sign']==-1
    assert value['entries']['transaction.C_PERSONAL.450']['attributes']['economic_sign']==1
    assert value['entries']['auxiliary.cfg.ref_txn_modelo']['claims'][0]['classification']=='mvp_proposal'
    assert len(value['original_tables'])==5 and len(value['auxiliary_tables'])==2


@pytest.mark.parametrize('mutation',['range','hash','classification','coverage'])
def test_invalid_catalog_provenance_and_coverage_are_rejected(mutation):
    value=copy.deepcopy(d.load_catalog())
    entry=value['entries']['auxiliary.cfg.ref_txn_modelo']
    if mutation=='range': entry['claims'][0]['source_refs'][0]['line_end']=999999
    if mutation=='hash': entry['claims'][0]['source_refs'][0]['sha256']='0'*64
    if mutation=='classification': entry['claims'][0]['classification']='upstream_explicit'
    if mutation=='coverage': value['entries'].pop('field.dim.dim_cliente.num_cte')
    with pytest.raises(ValueError): c.validate_catalog(value)


def test_document_coverage_hashes_ids_pointers_and_artifacts(documents):
    assert documents==d.build_documents()
    assert len(documents)==82 and len({x.id for x in documents})==82
    assert max(len(x.page_content) for x in documents)<=1800
    for path,text in d.artifact_texts(documents).items():
        assert path.read_bytes()==text.encode('utf-8')
    assert d.validate_documents(documents)
    kinds=d.document_manifest(documents)['kinds']
    assert kinds['table']==5 and kinds['field']==42 and kinds['transaction']==9
    assert not any(x in '\n'.join(doc.page_content for doc in documents) for x in ('1,027','1027','44 casos'))


def test_catalog_change_changes_document_identity():
    value=d.load_catalog()
    before=d.build_documents(value)
    changed=copy.deepcopy(value)
    changed['entries']['model.overview']['title']+=' — reviewed revision'
    after=d.build_documents(changed)
    assert {x.id for x in before}.isdisjoint(x.id for x in after)


def test_embedding_identity_produces_separate_corpora(documents,prepared):
    bundle,model=prepared
    assert d.corpus_identity(documents,model)!=d.corpus_identity(documents,replace(model,digest='other'))
    assert d.corpus_identity(documents,model)!=d.corpus_identity(documents,replace(model,dimension=512))
    old_id,stored=d.storage_documents(documents,model)
    assert set(x.id for x in stored).isdisjoint(x.id for x in documents)
    assert old_id!=str(old.corpus_identity(old.build_documents(),model))
    rag.validate_bundle(bundle,documents,model)


@pytest.mark.parametrize('field',['content','metadata','embedding','embedding_sha256'])
def test_bundle_tampering_is_rejected(documents,prepared,field):
    bundle,model=prepared
    value=copy.deepcopy(bundle)
    row=value['records'][0]
    row[field]='changed' if field!='metadata' else {}
    with pytest.raises((ValueError,KeyError,TypeError)):
        rag.validate_bundle(value,documents,model)


@pytest.mark.parametrize('question',[
    '¿Cuál es la capital de Francia?', '¿Qué es dim.dim_cliente.color_favorito?',
    '¿Cuál es el saldo actual de la cuenta 100000?', '¿Qué tasa de crecimiento se aplica en 2027?'])
def test_absence_of_documentary_evidence_does_not_trigger_semantic_guess(documents,question):
    assert not rag.evidence_eligible(question,documents)


def test_supported_absence_is_documented_evidence(documents):
    for question in ('¿Qué moneda utilizan los importes?','¿Existe credit_score?','¿Qué significa fec_nac para personas morales?'):
        assert rag.evidence_eligible(question,documents)


@pytest.mark.parametrize('question,group',[
    ('Enumera los productos de captación','CAPTACION'),
    ('Lista los productos de colocación','COLOCACION'),
    ('Productos de captación y colocación',None),
    ('Productos que no son de captación',None),
    ('¿Qué tasa tiene captación?',None)])
def test_membership_facet_is_derived_from_catalog_not_test_questions(documents,question,group):
    assert rag.product_group_scope(question,documents)==group


def test_isolated_guard_rejects_active_before_any_write(documents,prepared):
    bundle,model=prepared
    bad=dict(run_id='0'*32,container=rag.runtime.ACTIVE,database=rag.runtime.ACTIVE_DB,volume=rag.runtime.ACTIVE_VOLUME)
    with pytest.raises(RuntimeError): rag.ingest(bad,bundle,documents,model)


def test_sql_scoped_to_new_storage_and_temporary_references(documents,prepared):
    bundle,model=prepared
    sql=rag.ingestion_script(bundle,documents,model,'isolated_fixture')
    ddl=rag.DDL_PATH.read_text(encoding='utf-8')
    for protected in rag.bank.design.PROTECTED: assert protected not in ddl and protected not in sql
    assert 'CREATE TABLE IF NOT EXISTS' not in ddl
    assert 'pg_temp.nbm_rag_signature' in ddl and 'Incompatible RAG table' in ddl
    assert not any(word in ddl.upper() for word in ('DROP ','TRUNCATE ','DELETE FROM '))
    assert "model_id='new_bank_2026'" in sql and 'embedding_sha256' in sql
    assert sql.startswith('BEGIN;') and sql.endswith('COMMIT;\n')


@pytest.fixture
def retriever(monkeypatch,documents,prepared):
    bundle,model=prepared
    snapshot={'manifest':bundle['manifest'],'rows':[
        {k:v for k,v in row.items() if k!='embedding'} |
        {'actual_vector_sha256':row['embedding_sha256'],'dimension':1024}
        for row in bundle['records']]}
    monkeypatch.setattr(rag.bank,'environment',lambda *a,**k:'offline_fixture')
    monkeypatch.setattr(rag,'query',lambda *a,**k:snapshot)
    monkeypatch.setattr(rag,'assert_model_current',lambda model:None)
    class Embeddings:
        calls=0
        def embed_query(self,text):
            self.calls+=1
            return [1.0]+[0.0]*1023
    value=rag.CatalogRetriever({},documents,Embeddings(),model,model_id=c.MODEL_ID,
        corpus_id=bundle['manifest']['corpus_id'],index_manifest=bundle['manifest'])
    return value,snapshot['rows'][0]


def test_retriever_scope_results_and_legacy_shape(monkeypatch,retriever):
    value,row=retriever
    statements=[]
    def read(state,sql,**kwargs):
        statements.append(sql)
        return [dict(row,distance=0.1)]
    monkeypatch.setattr(rag,'query',read)
    results=value.search('¿Qué moneda utilizan los importes?')
    assert len(results)==1 and results[0]['cosine_similarity']==0.9
    assert {'id','content','source','source_version','metadata','cosine_distance','references','assertion_origins'}<=results[0].keys()
    assert "model_id='new_bank_2026'" in statements[0]
    assert value.corpus_id in statements[0] and 'bank_knowledge_new_bank.documents' in statements[0]
    assert 'bank_knowledge.documents' not in statements[0]


def test_retriever_abstains_without_embedding_or_query(monkeypatch,retriever):
    value,row=retriever
    monkeypatch.setattr(rag,'query',lambda *a,**k:pytest.fail('Unsupported query reached PostgreSQL'))
    assert value.retrieve('¿Cuál es la capital de Francia?')['status']=='no_evidence'
    assert value.embeddings.calls==0


@pytest.mark.parametrize('mutation',['id','metadata','actual_vector_sha256','dimension','distance'])
def test_retrieved_tampering_is_rejected(monkeypatch,retriever,mutation):
    value,row=retriever
    changed=copy.deepcopy(dict(row,distance=0.1))
    changed[mutation]={'id':str(uuid.uuid4()),'metadata':{},'actual_vector_sha256':'0'*64,
                       'dimension':512,'distance':float('nan')}[mutation]
    monkeypatch.setattr(rag,'query',lambda *a,**k:[changed])
    with pytest.raises(ValueError): value.retrieve('¿Qué moneda utilizan los importes?')


def test_wrong_retriever_scope_rejected_before_connection(documents,prepared):
    bundle,model=prepared
    with pytest.raises(ValueError,match='Unauthorized'):
        rag.CatalogRetriever({},documents,None,model,model_id='legacy',
            corpus_id=bundle['manifest']['corpus_id'],index_manifest=bundle['manifest'])


def test_document_text_cannot_be_laundered_by_rehashing(documents):
    changed=copy.deepcopy(documents)
    changed[0].page_content='Unsupported invented policy'
    changed[0].metadata['chunk_sha256']=c.digest(changed[0].page_content)
    with pytest.raises(ValueError): d.validate_documents(changed)
