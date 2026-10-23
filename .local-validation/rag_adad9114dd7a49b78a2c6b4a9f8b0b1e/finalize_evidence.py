"""Read-only final verification for this isolated RAG run; no PostgreSQL writes."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts import new_bank_rag as rag
from scripts import new_bank_documents as docs
from scripts import new_bank_publication as publication

directory=Path(__file__).resolve().parent
ctx=json.loads((directory/'state.json').read_text(encoding='utf-8'))
_,state=rag.runtime.load_state(ctx['isolated_state'])
original=rag.runtime.active_guard()
rag.bank.environment(state)
_,published=publication.load_state(ctx['publication_state'])
active_bank=publication.verify(published)
isolated_bank=rag.bank.verify(state,publication.reference())
active_legacy=rag.runtime.snapshot(active=True)
isolated_legacy=rag.runtime.snapshot(state)
assert active_bank==ctx['primary_bank_before']
assert isolated_bank['manifest']==ctx['isolated_bank_before']['manifest']
assert isolated_bank['quality']==ctx['isolated_bank_before']['quality']
assert active_legacy['protected']==ctx['primary_legacy_before']['protected']
assert isolated_legacy['protected']==ctx['isolated_legacy_before']['protected']
assert publication.file_hashes(ctx['protected_files'])==ctx['protected_files']
assert rag.runtime.query(None,f"SELECT to_jsonb(to_regnamespace('{rag.SCHEMA}') IS NULL);",active=True)
historic=rag.runtime.historical_fingerprints(active=True)
assert rag.runtime.historical_fingerprints(state)==historic
documents=docs.build_documents()
bundle=json.loads((directory/'prepared_vectors.json').read_text(encoding='utf-8'))
model=rag.legacy.ModelIdentity(**bundle['manifest']['embedding_model'])
rag.assert_model_current(model)
rag.validate_bundle(bundle,documents,model)
snapshot=rag.query(state,rag.snapshot_sql(bundle['manifest']['corpus_id']))
rag.validate_stored(snapshot,bundle['manifest'],documents,model)
rag_state=rag.query(state,f"SELECT jsonb_build_object('database',current_database(),'postgres',current_setting('server_version'),"
    f"'vector',(SELECT extversion FROM pg_extension WHERE extname='vector'),'corpora',(SELECT count(*) FROM {rag.SCHEMA}.corpora),"
    f"'documents',(SELECT count(*) FROM {rag.SCHEMA}.documents),'dimensions',(SELECT jsonb_agg(DISTINCT public.vector_dims(embedding)) FROM {rag.SCHEMA}.documents))")
assert rag_state['database']==state['database'] and rag_state['corpora']==1 and rag_state['documents']==82
assert rag_state['dimensions']==[1024]
evaluation=json.loads((directory/'retrieval-evaluation.json').read_text(encoding='utf-8'))
baseline=json.loads((directory/'retrieval-cosine-baseline.json').read_text(encoding='utf-8'))
assert evaluation['passed']==evaluation['total']==30
tests={}
for name in ('rag-unit-tests','rag-postgres-tests','rag-retrieval-tests','rag-legacy-unit-tests','rag-legacy-retrieval-tests','rag-source-static-tests'):
    path=rag.runtime.LOCAL/(name+'.xml')
    root=ET.parse(path).getroot()
    suites=list(root) if root.tag=='testsuites' else [root]
    tests[name]={key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    tests[name]['junit_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    assert not any(tests[name][key] for key in ('failures','errors','skipped'))
report={
    'status':'isolated_rag_verified','verified_utc':datetime.now(timezone.utc).isoformat(),
    'run_id':ctx['run_id'],'active_target':original,
    'isolated_target':{key:state[key] for key in ('run_id','container','container_id','database','volume')},
    'isolated_storage':rag_state,'active_new_rag_schema_absent':True,'active_writes_performed':False,
    'bank_data_preserved':{'active':True,'isolated':True,'dataset_sha256':active_bank['manifest']['dataset_sha256'],
        'table_counts_before':ctx['primary_bank_before']['counts'],'table_counts_after':active_bank['counts'],
        'table_hashes_before':ctx['primary_bank_before']['manifest']['tables'],'table_hashes_after':active_bank['manifest']['tables'],
        'reconciled_account_months':active_bank['quality']['reconciled_account_months']},
    'legacy_preserved':{'active':True,'isolated':True,'before':ctx['primary_legacy_before']['protected']['rows'],
        'after':active_legacy['protected']['rows'],'historical_fingerprints':historic,'schema_signatures_equal':True},
    'protected_files_unchanged':ctx['protected_files'],
    'catalog':{'model_id':rag.MODEL_ID,'version':docs.catalog.VERSION,
        'catalog_sha256':docs.document_manifest(documents)['catalog_sha256'],
        'document_count':len(documents),'kinds':docs.document_manifest(documents)['kinds'],
        'classifications':dict(Counter(c['classification'] for e in docs.load_catalog()['entries'].values() for c in e['claims'])),
        'max_chunk_characters':max(len(d.page_content) for d in documents)},
    'index_identity':bundle['manifest'],
    'initial_ingestion':{'status':'indexado','documents':82,'evidence':'First PostgreSQL test fixture and observed ingestion-result.json before repeat runs'},
    'repeat_ingestion':json.loads((directory/'repeat-result.json').read_text(encoding='utf-8')),
    'baseline_retrieval':{'total':baseline['total'],'passed':baseline['passed'],'positive_mrr':baseline['positive_mrr'],
        'failed_case_ids':[case['id'] for case in baseline['cases'] if not case['passed']]},
    'retrieval':evaluation,'tests':tests,'total_tests':sum(value['tests'] for value in tests.values()),
    'retained_rag_case_databases':[db for db in state.get('case_databases',[]) if '_rag_' in db],
    'limits':['Finite retrieval fixture is not a proof for arbitrary questions',
        'No active ingestion or agent integration authorized at this stage',
        'Synthetic financial rules are not official banking policies']}
rag.runtime.save(directory/'final-evidence.json',report)
rag.runtime.save(rag.catalog.ROOT/'docs/new-bank-model-rag-validation.json',report)
ctx.update(status='isolated_rag_verified',corpus_id=bundle['manifest']['corpus_id'],active_preserved=True,
           isolated_banks_preserved=True,legacy_preserved=True,verified_utc=report['verified_utc'])
rag.runtime.save(directory/'state.json',ctx)
print(json.dumps({'status':report['status'],'tests':report['total_tests'],'retrieval_passed':evaluation['passed'],
    'documents':len(documents),'active_preserved':True,'active_new_rag_schema_absent':True,'legacy_preserved':True},indent=2))
