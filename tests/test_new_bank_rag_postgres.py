"""Opt-in real pgvector tests. Every write requires the registered isolated state.

Set BANK_NEW_RAG_CONTEXT to the ignored RAG preflight state, then --run-db-tests.
No use of the legacy database fixtures, active writes or destructive cleanup.
"""
import copy
import json
import os
from pathlib import Path
import uuid

import pytest

from scripts import knowledge_corpus as old
from scripts import new_bank_documents as docs
from scripts import new_bank_rag as rag

pytestmark=pytest.mark.integration


@pytest.fixture(scope='module')
def context():
    path=os.environ.get('BANK_NEW_RAG_CONTEXT')
    if not path: pytest.skip('Explicit BANK_NEW_RAG_CONTEXT required; no default database')
    path=Path(path).resolve()
    assert path.is_relative_to(rag.runtime.LOCAL.resolve()) and path.name=='state.json'
    ctx=json.loads(path.read_text(encoding='utf-8'))
    state_file,state=rag.runtime.load_state(ctx['isolated_state'])
    rag.bank.environment(state)
    documents=docs.build_documents()
    bundle=json.loads((path.parent/'prepared_vectors.json').read_text(encoding='utf-8'))
    model=old.ModelIdentity(**bundle['manifest']['embedding_model'])
    rag.validate_bundle(bundle,documents,model)
    rag.initialize(state)
    result=rag.ingest(state,bundle,documents,model)
    rag.runtime.save(path.parent/'ingestion-result.json',result)
    assert result['status'] in ('indexado','sin cambios') and result['documents']==82
    return ctx,path,state_file,state,documents,bundle,model


def new_case(context,label):
    ctx,path,state_file,state,documents,bundle,model=context
    database=rag.runtime.case_database(state,label)
    rag.runtime.save(state_file,state)
    rag.transport(state,'CREATE EXTENSION vector;',database=database,write=True)
    return database


def insert_record(row):
    literal=rag.bank.design.literal
    values=[literal(row[k])+'::jsonb' if k=='metadata' else ('NULL' if row[k] is None else literal(row[k]))
        for k in ('id','corpus_id','model_id','content','metadata','embedding','embedding_sha256')]
    # Preserve LF bytes across Windows text pipes; a multiline SQL literal could
    # acquire CRLF and test the content hash instead of the intended constraint.
    if row['content'] is not None:
        values[3]="convert_from(decode('"+row['content'].encode('utf-8').hex()+"','hex'),'UTF8')"
    return f"INSERT INTO {rag.SCHEMA}.documents VALUES("+','.join(values)+');'


def test_complete_ingestion_and_binary_vector_integrity(context):
    ctx,path,sf,state,documents,bundle,model=context
    snapshot=rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']))
    assert rag.validate_stored(snapshot,bundle['manifest'],documents,model)
    assert len(snapshot['rows'])==82


def test_repeat_is_no_change_and_ddl_is_compatible(context):
    ctx,path,sf,state,documents,bundle,model=context
    before=rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']))
    result=rag.ingest(state,bundle,documents,model)
    after=rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']))
    assert result['status']=='sin cambios' and after==before
    rag.runtime.save(path.parent/'repeat-result.json',result)


def test_failure_rolls_back_manifest_and_documents(context):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_atomic')
    rag.initialize(state,database=db)
    result=rag.transport(state,rag.ingestion_script(bundle,documents,model,db,_fail=True),
        database=db,write=True,check=False)
    assert result.returncode and 'Injected RAG rollback' in result.stderr
    assert rag.query(state,f"SELECT jsonb_build_array((SELECT count(*) FROM {rag.SCHEMA}.corpora),"
        f"(SELECT count(*) FROM {rag.SCHEMA}.documents))",database=db)==[0,0]


def test_incompatible_structure_is_rejected_without_repair(context):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_incompatible')
    rag.transport(state,f'CREATE SCHEMA {rag.SCHEMA}; CREATE TABLE {rag.SCHEMA}.corpora(wrong INTEGER);',database=db,write=True)
    result=rag.transport(state,rag.DDL_PATH.read_text(encoding='utf-8'),database=db,write=True,check=False)
    assert result.returncode and 'Incomplete or unrecognized RAG schema' in result.stderr
    assert rag.query(state,f"SELECT to_jsonb(to_regclass('{rag.SCHEMA}.documents') IS NULL)",database=db)


def test_partial_corpus_is_rejected_without_filling(context):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_partial')
    rag.initialize(state,database=db)
    literal=rag.bank.design.literal
    rag.transport(state,f"INSERT INTO {rag.SCHEMA}.corpora VALUES("
        f"{literal(bundle['manifest']['corpus_id'])},'{rag.MODEL_ID}',{literal(rag.catalog.canonical(bundle['manifest']))}::jsonb);",database=db,write=True)
    with pytest.raises(ValueError,match='content/metadata/count mismatch'):
        rag.ingest(state,bundle,documents,model,database=db)
    assert rag.query(state,f'SELECT to_jsonb(count(*)) FROM {rag.SCHEMA}.documents',database=db)==0


@pytest.mark.parametrize('kind',['manifest','document'])
def test_incompatible_index_is_rejected_without_overwrite(context,kind):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_changed')
    rag.ingest(state,bundle,documents,model,database=db)
    if kind=='manifest':
        statement=f"UPDATE {rag.SCHEMA}.corpora SET manifest=jsonb_set(manifest,'{{vectors_sha256}}','\"incompatible\"'::jsonb);"
    else:
        statement=f"UPDATE {rag.SCHEMA}.documents SET content=content||' changed',metadata=jsonb_set(metadata,'{{chunk_sha256}}',"
        statement+="to_jsonb(encode(sha256(convert_to(content||' changed','UTF8')),'hex'))) WHERE id="
        statement+=rag.bank.design.literal(bundle['records'][0]['id'])+'::uuid;'
    rag.transport(state,statement,database=db,write=True)
    changed=rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']),database=db)
    with pytest.raises(ValueError,match='Corpus identity mismatch|content/metadata/count mismatch'):
        rag.ingest(state,bundle,documents,model,database=db)
    assert rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']),database=db)==changed
    with pytest.raises(ValueError,match='manifest|differs'):
        rag.CatalogRetriever(state,documents,None,model,model_id=rag.MODEL_ID,
            corpus_id=bundle['manifest']['corpus_id'],index_manifest=bundle['manifest'],database=db)


def test_existing_wrong_column_type_is_rejected_without_repair(context):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_wrong_type')
    rag.initialize(state,database=db)
    rag.transport(state,f'ALTER TABLE {rag.SCHEMA}.documents ALTER COLUMN content TYPE VARCHAR;',database=db,write=True)
    result=rag.transport(state,rag.DDL_PATH.read_text(encoding='utf-8'),database=db,write=True,check=False)
    assert result.returncode and 'Incompatible RAG table documents' in result.stderr
    assert rag.query(state,f"SELECT to_jsonb(format_type(atttypid,atttypmod)) FROM pg_attribute "
        f"WHERE attrelid='{rag.SCHEMA}.documents'::regclass AND attname='content'",database=db)=='character varying'


@pytest.mark.parametrize('kind',['null','unique','foreign_key','metadata','vector_hash','dimension','model'])
def test_sql_constraints_reject_invalid_rows_in_rolled_back_transactions(context,kind):
    ctx,path,sf,state,documents,bundle,model=context
    row=copy.deepcopy(bundle['records'][0])
    if kind!='unique': row['id']=str(uuid.uuid4())
    if kind=='null': row['content']=None
    if kind=='foreign_key': row['corpus_id']=str(uuid.uuid4()); row['metadata']['corpus_id']=row['corpus_id']
    if kind=='metadata': row['metadata']['chunk_sha256']='0'*64
    if kind=='vector_hash': row['embedding_sha256']='0'*64
    if kind=='dimension': row['embedding']='[1,2,3]'
    if kind=='model': row['model_id']='legacy'; row['metadata']['model_id']='legacy'
    row['metadata']=rag.catalog.canonical(row['metadata'])
    result=rag.transport(state,'BEGIN; '+insert_record(row)+' ROLLBACK;',write=True,check=False)
    assert result.returncode
    expected={'null':'23502','unique':'23505','foreign_key':'23503','metadata':'23514',
              'vector_hash':'23514','dimension':'22000','model':'23514'}[kind]
    assert expected in result.stderr


def test_retriever_excludes_another_corpus_even_with_identical_vector(context,monkeypatch):
    ctx,path,sf,state,documents,bundle,model=context
    db=new_case(context,'rag_scope')
    rag.ingest(state,bundle,documents,model,database=db)
    literal=rag.bank.design.literal
    decoy_manifest=copy.deepcopy(bundle['manifest'])
    decoy_manifest['corpus_id']=str(uuid.uuid4())
    decoy=copy.deepcopy(bundle['records'][0])
    decoy['id']=str(uuid.uuid4())
    decoy['corpus_id']=decoy_manifest['corpus_id']
    decoy['metadata']['corpus_id']=decoy['corpus_id']
    decoy['metadata']=rag.catalog.canonical(decoy['metadata'])
    rag.transport(state,f"INSERT INTO {rag.SCHEMA}.corpora VALUES("
        f"{literal(decoy['corpus_id'])},'{rag.MODEL_ID}',{literal(rag.catalog.canonical(decoy_manifest))}::jsonb);"
        +insert_record(decoy),database=db,write=True)
    class ExactQueryEmbedding:
        def embed_query(self,text): return rag.Vector.from_text(decoy['embedding']).to_list()
    monkeypatch.setattr(rag,'assert_model_current',lambda model:None)
    retriever=rag.CatalogRetriever(state,documents,ExactQueryEmbedding(),model,model_id=rag.MODEL_ID,
        corpus_id=bundle['manifest']['corpus_id'],index_manifest=bundle['manifest'],database=db)
    result=retriever.retrieve('¿Qué moneda utilizan los importes?',k=20)
    assert result['results'] and decoy['id'] not in {r['id'] for r in result['results']}
    assert all(r['metadata']['corpus_id']==retriever.corpus_id for r in result['results'])


def test_both_banking_datasets_and_legacy_embeddings_are_preserved(context):
    from scripts import new_bank_publication as publication
    ctx,path,sf,state,documents,bundle,model=context
    rag.runtime.active_guard()
    _,published=publication.load_state(ctx['publication_state'])
    assert publication.verify(published)==ctx['primary_bank_before']
    isolated=rag.bank.verify(state,publication.reference())
    assert isolated['manifest']==ctx['isolated_bank_before']['manifest']
    assert isolated['quality']==ctx['isolated_bank_before']['quality']
    assert rag.runtime.snapshot(active=True)['protected']==ctx['primary_legacy_before']['protected']
    assert rag.runtime.snapshot(state)['protected']==ctx['isolated_legacy_before']['protected']
    assert publication.file_hashes(ctx['protected_files'])==ctx['protected_files']
    assert rag.runtime.query(None,f"SELECT to_jsonb(to_regnamespace('{rag.SCHEMA}') IS NULL);",active=True)
