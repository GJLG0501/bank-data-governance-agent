"""Pinned active-development RAG publication from the isolated, validated bundle.

Only the new bank_knowledge_new_bank schema is written. A fresh, verified custom
backup is mandatory. DDL and COPY ingestion commit in one transaction.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import uuid

from scripts import new_bank_documents as docs
from scripts import new_bank_publication as bank_publication
from scripts import new_bank_rag as rag
from scripts import new_bank_runtime_validation as runtime

ROOT=rag.catalog.ROOT
LOCAL=runtime.LOCAL
REVIEWED_DDL_SHA256='9c668cd8e1cc81af2ebbe9b8c110a1596a7174d032a159149c23590b2dcebed6'


def context():
    path=Path((LOCAL/'rag-current.txt').read_text(encoding='utf-8').strip()).resolve()
    if not path.is_relative_to(LOCAL.resolve()) or path.name!='state.json':
        raise RuntimeError('Invalid isolated RAG context')
    return json.loads(path.read_text(encoding='utf-8')),path


def preflight():
    ctx,ctxpath=context()
    if hashlib.sha256(rag.DDL_PATH.read_bytes()).hexdigest()!=REVIEWED_DDL_SHA256:
        raise RuntimeError('Reviewed isolated RAG structure changed')
    active=runtime.active_guard()
    _,bank_state=bank_publication.load_state(ctx['publication_state'])
    bank=bank_publication.verify(bank_state)
    if bank!=ctx['primary_bank_before']:
        raise RuntimeError('Active bank dataset changed')
    old=runtime.snapshot(active=True)
    if old['protected']!=ctx['primary_legacy_before']['protected']:
        raise RuntimeError('Historical data or vectors changed')
    historical=runtime.historical_fingerprints(active=True)
    if bank_publication.file_hashes(ctx['protected_files'])!=ctx['protected_files']:
        raise RuntimeError('Protected source or agent file changed')
    _,isolated=runtime.load_state(ctx['isolated_state'])
    rag.bank.environment(isolated)
    documents=docs.build_documents()
    bundle=json.loads((ctxpath.parent/'prepared_vectors.json').read_text(encoding='utf-8'))
    embeddings,model=rag.probe()
    rag.validate_bundle(bundle,documents,model)
    rag.assert_model_current(model)
    if json.loads(rag.INDEX_PATH.read_text(encoding='utf-8'))!=bundle['manifest']:
        raise RuntimeError('Reviewed index manifest changed')
    rag.validate_stored(rag.query(isolated,rag.snapshot_sql(bundle['manifest']['corpus_id'])),
        bundle['manifest'],documents,model)
    existing=runtime.query(None,f"SELECT to_jsonb(to_regnamespace('{rag.SCHEMA}') IS NOT NULL)",active=True)
    if existing:
        # A compatible schema is permitted only if the same corpus is complete.
        snap=json.loads(runtime.psql(runtime.ACTIVE,runtime.ACTIVE_DB,
            'BEGIN READ ONLY; '+rag.snapshot_sql(bundle['manifest']['corpus_id'])+'; COMMIT;').stdout)
        rag.validate_stored(snap,bundle['manifest'],documents,model)
    return {'context':ctx,'active':active,'bank':bank,'legacy':old,'historic':historical,
            'isolated':isolated,'documents':documents,'bundle':bundle,'embeddings':embeddings,
            'model':model,'schema_preexisting':existing}


def backup():
    checked=preflight()
    run=uuid.uuid4().hex
    directory=LOCAL/('rag_publication_'+run)
    if directory.exists(): raise RuntimeError('Publication directory collision')
    import subprocess
    if subprocess.run(['git','check-ignore','--quiet',str(directory/'database.dump')],cwd=ROOT).returncode:
        raise RuntimeError('Backup directory is not excluded from Git')
    directory.mkdir(parents=True,exist_ok=False)
    archive='/tmp/new-bank-rag-prepublish-'+run+'.dump'
    result=runtime.docker('exec',runtime.ACTIVE,'pg_dump','--no-password','-Fc','-U',runtime.ROLE,
        '-d',runtime.ACTIVE_DB,'-f',archive,check=False,timeout=300)
    if result.returncode: raise RuntimeError('Fresh pg_dump failed; publication prohibited')
    destination=directory/'database.dump'
    copy=runtime.docker('cp',runtime.ACTIVE+':'+archive,str(destination),check=False,timeout=300)
    if copy.returncode or not destination.is_file() or destination.stat().st_size<=0:
        raise RuntimeError('Backup copy missing or empty; publication prohibited')
    listed=runtime.docker('exec',runtime.ACTIVE,'pg_restore','--list',archive,check=False)
    if listed.returncode or not all(token in listed.stdout for token in
        ('TABLE DATA public CUSTOMER','TABLE DATA public TRANSACTION','TABLE DATA public LOAN',
         'TABLE DATA bank_knowledge documents','TABLE DATA dim dim_cliente',
         'TABLE DATA cfg fact_txn_captacoloca_d','EXTENSION - vector')):
        raise RuntimeError('Backup listing incomplete; publication prohibited')
    isolated=checked['isolated']
    runtime.isolated_guard(isolated)
    copied='/tmp/rag-host-backup-'+run+'.dump'
    runtime.docker('cp',str(destination),isolated['container']+':'+copied,timeout=300)
    host_listing=runtime.docker('exec',isolated['container'],'pg_restore','--list',copied)
    if host_listing.stdout!=listed.stdout:
        raise RuntimeError('Local backup archive listing differs; publication prohibited')
    (directory/'backup-list.txt').write_text(listed.stdout,encoding='utf-8')
    state={'run_id':run,'status':'backup_verified','created_utc':datetime.now(timezone.utc).isoformat(),
        'active':checked['active'],'database':runtime.ACTIVE_DB,
        'backup':{'path':str(destination),'bytes':destination.stat().st_size,
                  'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                  'dump_exit_code':result.returncode,'list_exit_code':listed.returncode,
                  'host_archive_list_verified':True},
        'corpus_id':checked['bundle']['manifest']['corpus_id'],
        'index_sha256':hashlib.sha256(rag.INDEX_PATH.read_bytes()).hexdigest(),
        'bundle_sha256':hashlib.sha256((context()[1].parent/'prepared_vectors.json').read_bytes()).hexdigest(),
        'legacy_before':checked['legacy']['protected'],'historic_before':checked['historic'],
        'bank_before':checked['bank'],'schema_preexisting':checked['schema_preexisting']}
    runtime.save(directory/'state.json',state)
    print(json.dumps({'state':str(directory/'state.json'),'backup':state['backup']},ensure_ascii=False))
    return directory/'state.json'


def write_sql(sql):
    runtime.active_guard()
    result=runtime.docker('exec','-i','-e','PGOPTIONS=-c statement_timeout=120000 -c default_transaction_read_only=off',
        runtime.ACTIVE,'psql','-X','--no-password','--quiet','--tuples-only','--no-align',
        '--set=ON_ERROR_STOP=1','--set=VERBOSITY=verbose','-U',runtime.ROLE,'-d',runtime.ACTIVE_DB,
        input=sql,check=False,timeout=240)
    if result.returncode:
        errors=[line for line in result.stderr.splitlines() if line.startswith(('ERROR:','DETAIL:'))]
        raise RuntimeError('RAG publication transaction failed: '+'\n'.join(errors)[:2000])
    return json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))


def publish(path):
    path=Path(path).resolve()
    if not path.is_relative_to(LOCAL.resolve()) or path.name!='state.json':
        raise RuntimeError('Explicit local RAG publication state required')
    state=json.loads(path.read_text(encoding='utf-8'))
    if path.parent.name!='rag_publication_'+state['run_id'] or state['status']!='backup_verified':
        raise RuntimeError('Invalid or completed publication state')
    checked=preflight()
    destination=Path(state['backup']['path']).resolve()
    if not destination.is_relative_to(path.parent) or not destination.is_file() or destination.stat().st_size!=state['backup']['bytes'] or hashlib.sha256(destination.read_bytes()).hexdigest()!=state['backup']['sha256']:
        raise RuntimeError('Fresh backup changed or missing')
    if checked['active']!=state['active'] or checked['bank']!=state['bank_before'] or checked['legacy']['protected']!=state['legacy_before'] or checked['historic']!=state['historic_before']:
        raise RuntimeError('Active state changed after backup')
    if state['corpus_id']!=checked['bundle']['manifest']['corpus_id'] or hashlib.sha256(rag.INDEX_PATH.read_bytes()).hexdigest()!=state['index_sha256'] or hashlib.sha256((context()[1].parent/'prepared_vectors.json').read_bytes()).hexdigest()!=state['bundle_sha256']:
        raise RuntimeError('Corpus artifacts changed after backup')
    rag.assert_model_current(checked['model'])
    ddl=rag.DDL_PATH.read_text(encoding='utf-8')
    header,separator,body=ddl.partition('BEGIN;')
    if not separator or any(not line.lstrip().startswith('--') for line in header.splitlines() if line.strip()) or not ddl.rstrip().endswith('COMMIT;'):
        raise RuntimeError('Reviewed RAG DDL transaction boundaries changed')
    ddl=('BEGIN;'+body).rstrip()[:-len('COMMIT;')]
    ingest=rag.ingestion_script(checked['bundle'],checked['documents'],checked['model'],runtime.ACTIVE_DB)
    if not ingest.startswith('BEGIN;') or not ingest.endswith('COMMIT;\n'):
        raise RuntimeError('Reviewed RAG ingestion boundaries changed')
    script="DO $target$ BEGIN IF current_database()<>"+rag.bank.design.literal(runtime.ACTIVE_DB)+" OR current_user<>"+rag.bank.design.literal(runtime.ROLE)+" THEN RAISE EXCEPTION 'Active RAG target mismatch'; END IF; END $target$;\n"
    result=write_sql(script+ddl+ingest.removeprefix('BEGIN;'))
    def read_snapshot():
        return json.loads(runtime.psql(runtime.ACTIVE,runtime.ACTIVE_DB,'BEGIN READ ONLY; '+rag.snapshot_sql(state['corpus_id'])+'; COMMIT;').stdout)
    first=read_snapshot()
    rag.validate_stored(first,checked['bundle']['manifest'],checked['documents'],checked['model'])
    rag.assert_model_current(checked['model'])
    repeat=write_sql(script+ddl+ingest.removeprefix('BEGIN;'))
    after=read_snapshot()
    rag.validate_stored(after,checked['bundle']['manifest'],checked['documents'],checked['model'])
    if repeat['status']!='sin cambios' or first!=after:
        raise RuntimeError('Repeat ingestion changed RAG corpus')
    state.update(status='published_verified',first=result,repeat=repeat,verified_utc=datetime.now(timezone.utc).isoformat())
    runtime.save(path,state)
    return state


def verify(path):
    path=Path(path).resolve()
    state=json.loads(path.read_text(encoding='utf-8'))
    if (not path.is_relative_to(LOCAL.resolve()) or path.name!='state.json'
        or path.parent.name!='rag_publication_'+state['run_id'] or state['status']!='published_verified'):
        raise RuntimeError('Explicit completed publication state required')
    checked=preflight()
    manifest=checked['bundle']['manifest']
    sql=f"SELECT jsonb_build_object('database',current_database(),'corpora',(SELECT count(*) FROM {rag.SCHEMA}.corpora),"
    sql+=f"'documents',(SELECT count(*) FROM {rag.SCHEMA}.documents),"
    sql+=f"'distinct_ids',(SELECT count(DISTINCT id) FROM {rag.SCHEMA}.documents),"
    sql+=f"'dimensions',(SELECT jsonb_agg(DISTINCT public.vector_dims(embedding)) FROM {rag.SCHEMA}.documents))"
    storage=json.loads(runtime.psql(runtime.ACTIVE,runtime.ACTIVE_DB,'BEGIN READ ONLY; '+sql+'; COMMIT;').stdout)
    if storage!={'database':runtime.ACTIVE_DB,'corpora':1,'documents':82,'distinct_ids':82,'dimensions':[1024]}:
        raise RuntimeError('Published RAG count or dimension differs')
    if state['bank_before']!=checked['bank'] or state['legacy_before']!=checked['legacy']['protected'] or state['historic_before']!=checked['historic']:
        raise RuntimeError('Bank or old corpus changed after publication')
    if state['corpus_id']!=manifest['corpus_id']:
        raise RuntimeError('Published corpus identity changed')
    report={'status':'published_verified','verified_utc':datetime.now(timezone.utc).isoformat(),
        'target':checked['active'],'backup':state['backup'],'schema':rag.SCHEMA,
        'structure':['corpora','documents'],'model_id':rag.MODEL_ID,
        'catalog_version':docs.catalog.VERSION,'corpus_id':state['corpus_id'],
        'embedding_model':manifest['embedding_model'],'vectors_sha256':manifest['vectors_sha256'],
        'storage':storage,'first':state['first'],'repeat':state['repeat'],
        'dataset_sha256_before':state['bank_before']['manifest']['dataset_sha256'],
        'dataset_sha256_after':checked['bank']['manifest']['dataset_sha256'],
        'bank_counts_before':state['bank_before']['counts'],'bank_counts_after':checked['bank']['counts'],
        'bank_table_hashes_before':state['bank_before']['manifest']['tables'],
        'bank_table_hashes_after':checked['bank']['manifest']['tables'],
        'reconciled_account_months':checked['bank']['quality']['reconciled_account_months'],
        'old_rows_before':state['legacy_before']['rows'],
        'old_rows_after':checked['legacy']['protected']['rows'],
        'historic_before':state['historic_before'],'historic_after':checked['historic'],
        'isolated_identity_equal':True}
    runtime.save(path.parent/'verification.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('backup','publish','verify'))
    parser.add_argument('--state')
    args=parser.parse_args()
    if args.command=='backup': backup()
    elif not args.state: parser.error('--state required')
    elif args.command=='publish':
        result=publish(args.state)
        print(json.dumps({'status':result['status'],'first':result['first'],'repeat':result['repeat']},ensure_ascii=False))
    else:
        result=verify(args.state)
        print(json.dumps({'status':result['status'],'storage':result['storage'],'corpus_id':result['corpus_id'],
            'old_rows_preserved':result['old_rows_before']==result['old_rows_after'],
            'bank_hashes_preserved':result['bank_table_hashes_before']==result['bank_table_hashes_after']},ensure_ascii=False))


if __name__=='__main__': main()
