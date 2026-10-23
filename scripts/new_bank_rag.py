"""New-bank documentary RAG: isolated Docker pgvector storage, scoped retrieval.

No generative provider, agent change, TCP DB defaults, bank-row query or active write.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlparse
import uuid

from pgvector.psycopg import Vector

from scripts import new_bank_catalog as catalog
from scripts import new_bank_documents as docs
from scripts import new_bank_model as bank
from scripts import new_bank_runtime_validation as runtime
from scripts import knowledge_corpus as legacy

SCHEMA="bank_knowledge_new_bank"
MODEL_ID=catalog.MODEL_ID
DIMENSION=1024
DDL_PATH=catalog.ROOT/"sql/rag/001_new_bank_knowledge.sql"
INDEX_PATH=catalog.ROOT/"data/corpus/new_bank_model.index-manifest.json"
CASES_PATH=catalog.ROOT/"tests/fixtures/new_bank_retrieval_cases.json"


def probe():
    base,name=legacy.embedding_config()
    if urlparse(base).hostname not in ('127.0.0.1','localhost','::1') or urlparse(base).username:
        raise ValueError("Only the local embedding service is authorized")
    if name not in ('bge-large','bge-large:latest'):
        raise ValueError("This corpus requires explicitly installed bge-large")
    embeddings,model=legacy.probe_model()
    if model.dimension!=DIMENSION:
        raise ValueError("Embedding dimension differs; no schema alteration allowed")
    return embeddings,model


def assert_model_current(model):
    base,name=legacy.embedding_config()
    if name!=model.name or legacy.model_digest(legacy.Client(host=base,timeout=120),name)!=model.digest:
        raise ValueError("Embedding identity changed; stop without publishing")


def base_manifest(documents,model):
    return {"format":"new-bank-vector-index-v1","model_id":MODEL_ID,
        "corpus_id":docs.corpus_identity(documents,model),"document_manifest":docs.document_manifest(documents),
        "embedding_model":asdict(model),"distance":"cosine","vector_encoding":"pgvector-binary-v1"}


def prepare_vectors(documents,embeddings,model):
    docs.validate_documents(documents)
    if model.name not in ('bge-large','bge-large:latest') or model.dimension!=DIMENSION:
        raise ValueError("Unsupported embedding identity")
    corpus_id,stored=docs.storage_documents(documents,model)
    vectors=[]
    for start in range(0,len(stored),8):
        batch=embeddings.embed_documents([d.page_content for d in stored[start:start+8]])
        legacy.validate_vectors(batch,len(stored[start:start+8]),DIMENSION)
        vectors.extend(batch)
    records=[]
    for document,vector in zip(stored,vectors,strict=True):
        value=Vector(vector)
        records.append({"id":document.id,"model_id":MODEL_ID,"corpus_id":corpus_id,
            "content":document.page_content,"metadata":document.metadata,"embedding":value.to_text(),
            "embedding_sha256":hashlib.sha256(value.to_binary()).hexdigest()})
    manifest=base_manifest(documents,model)
    manifest["vectors_sha256"]=catalog.digest('\n'.join(r['id']+':'+r['embedding_sha256'] for r in sorted(records,key=lambda r:r['id'])))
    manifest["vector_hashes"]={r['id']:r['embedding_sha256'] for r in sorted(records,key=lambda r:r['id'])}
    return {"manifest":manifest,"records":records}


def validate_bundle(bundle,documents,model):
    manifest=bundle["manifest"]
    base=base_manifest(documents,model)
    if {k:v for k,v in manifest.items() if k not in ('vectors_sha256','vector_hashes')}!=base:
        raise ValueError("Vector bundle identity mismatch")
    corpus_id,stored=docs.storage_documents(documents,model)
    expected={d.id:d for d in stored}
    records=bundle["records"]
    if len(records)!=len(expected) or {r['id'] for r in records}!=set(expected):
        raise ValueError("Vector bundle count/ID mismatch")
    hashes={}
    for row in records:
        document=expected[row["id"]]
        if row["model_id"]!=MODEL_ID or row["corpus_id"]!=corpus_id or row["content"]!=document.page_content or row["metadata"]!=document.metadata:
            raise ValueError("Vector bundle content/metadata mismatch")
        vector=Vector.from_text(row["embedding"])
        legacy.validate_vectors([vector.to_list()],1,DIMENSION)
        checksum=hashlib.sha256(vector.to_binary()).hexdigest()
        if row["embedding_sha256"]!=checksum:
            raise ValueError("Vector bundle hash mismatch")
        hashes[row["id"]]=checksum
    total=catalog.digest('\n'.join(key+':'+hashes[key] for key in sorted(hashes)))
    if hashes!=manifest["vector_hashes"] or total!=manifest["vectors_sha256"]:
        raise ValueError("Vector index checksum mismatch")


def transport(state,sql,*,database=None,write=False,check=True):
    database=bank.environment(state,database)
    return runtime.psql(state["container"],database,sql,readonly=not write,state=state,check=check)


def query(state,sql,*,database=None):
    return json.loads(transport(state,"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL search_path=pg_catalog; "+sql+"; COMMIT;",database=database).stdout)


def initialize(state,*,database=None):
    # The reviewed static DDL handles exact compatibility, not IF NOT EXISTS alone.
    return transport(state,DDL_PATH.read_text(encoding="utf-8"),database=database,write=True)


def snapshot_sql(corpus_id):
    identifier=bank.design.literal(corpus_id)+"::uuid"
    return f"""SELECT jsonb_build_object(
      'manifest',(SELECT manifest FROM {SCHEMA}.corpora WHERE corpus_id={identifier} AND model_id='{MODEL_ID}'),
      'rows',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',id::text,'corpus_id',corpus_id::text,
        'model_id',model_id,'content',content,'metadata',metadata,'embedding_sha256',embedding_sha256,
        'actual_vector_sha256',encode(sha256(public.vector_send(embedding)),'hex'),
        'dimension',public.vector_dims(embedding)) ORDER BY id),'[]')
        FROM {SCHEMA}.documents WHERE corpus_id={identifier} AND model_id='{MODEL_ID}'))"""


def validate_stored(snapshot,manifest,documents,model):
    corpus_id,stored=docs.storage_documents(documents,model)
    if snapshot['manifest']!=manifest:
        raise ValueError("Stored corpus manifest missing or incompatible; no overwrite")
    expected={d.id:d for d in stored}
    rows=snapshot['rows']
    if len(rows)!=len(expected) or {r['id'] for r in rows}!=set(expected):
        raise ValueError("Stored corpus partial or duplicated; no overwrite")
    for row in rows:
        doc=expected[row['id']]
        if (row['model_id']!=MODEL_ID or row['corpus_id']!=corpus_id or row['content']!=doc.page_content
            or row['metadata']!=doc.metadata or row['dimension']!=DIMENSION
            or row['embedding_sha256']!=manifest['vector_hashes'][row['id']]
            or row['actual_vector_sha256']!=row['embedding_sha256']):
            raise ValueError("Stored content, scope, reference or embedding differs; no overwrite")
    return True


def ingestion_script(bundle,documents,model,database,*,_fail=False):
    validate_bundle(bundle,documents,model)
    manifest=bundle['manifest']
    cid=bank.design.literal(manifest['corpus_id'])+"::uuid"
    literal=bank.design.literal(catalog.canonical(manifest))+"::jsonb"
    script="BEGIN; SET LOCAL search_path=pg_catalog; SET LOCAL lock_timeout='60s'; SET LOCAL statement_timeout='120s';\n"
    script+="SELECT pg_advisory_xact_lock(7262026,3);\n"
    script+=f"LOCK TABLE {SCHEMA}.corpora,{SCHEMA}.documents IN SHARE ROW EXCLUSIVE MODE;\n"
    script+="DO $target$ BEGIN "+bank.assertion(f"current_database()={bank.design.literal(database)} AND current_user='{runtime.ROLE}'","Isolated RAG SQL target mismatch")+" END $target$;\n"
    script+=f"DO $existing$ BEGIN IF EXISTS(SELECT 1 FROM {SCHEMA}.corpora WHERE corpus_id={cid}) THEN "
    script+=bank.assertion(f"(SELECT model_id='{MODEL_ID}' AND manifest={literal} FROM {SCHEMA}.corpora WHERE corpus_id={cid})","Corpus identity mismatch")
    script+=f" ELSE IF EXISTS(SELECT 1 FROM {SCHEMA}.documents WHERE corpus_id={cid}) THEN RAISE EXCEPTION 'Partial corpus without manifest'; END IF; END IF; END $existing$;\n"
    script+=f"SELECT NOT EXISTS(SELECT 1 FROM {SCHEMA}.corpora WHERE corpus_id={cid}) AS do_load \\gset\n"
    script+=f"CREATE TEMP TABLE nbm_rag_stage (LIKE {SCHEMA}.documents);\n"
    columns=('id','corpus_id','model_id','content','metadata','embedding','embedding_sha256')
    script+='COPY pg_temp.nbm_rag_stage ('+','.join(columns)+') FROM STDIN;\n'
    for row in bundle['records']:
        values=[catalog.canonical(row[k]) if k=='metadata' else row[k] for k in columns]
        script+='\t'.join(v.replace('\\','\\\\').replace('\t',r'\t').replace('\n',r'\n').replace('\r',r'\r') for v in values)+'\n'
    script+='\\.\n\\if :do_load\n'
    script+=f"INSERT INTO {SCHEMA}.corpora VALUES({cid},'{MODEL_ID}',{literal});\n"
    if _fail:
        script+="DO $fail$ BEGIN RAISE EXCEPTION 'Injected RAG rollback'; END $fail$;\n"
    script+=f"INSERT INTO {SCHEMA}.documents ({','.join(columns)}) SELECT {','.join(columns)} FROM pg_temp.nbm_rag_stage;\n\\endif\n"
    # Every stored value, including binary vector checksum, is checked before COMMIT.
    expected=[]
    for row in bundle['records']:
        expected.append({k:row[k] for k in columns if k!='embedding'})
    expected.sort(key=lambda r:r['id'])
    actual=f"SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY id),'[]') FROM (SELECT id::text,corpus_id::text,model_id,content,metadata,embedding_sha256 FROM {SCHEMA}.documents WHERE corpus_id={cid} AND model_id='{MODEL_ID}') r"
    script+="DO $verify$ BEGIN "+bank.assertion(f"({actual})={bank.design.literal(catalog.canonical(expected))}::jsonb","RAG content/metadata/count mismatch")
    script+=bank.assertion(f"NOT EXISTS(SELECT 1 FROM {SCHEMA}.documents WHERE corpus_id={cid} AND (embedding_sha256<>encode(sha256(public.vector_send(embedding)),'hex') OR public.vector_dims(embedding)<>{DIMENSION}))","RAG vector integrity mismatch")+" END $verify$;\n"
    script+="SELECT jsonb_build_object('status',CASE WHEN :'do_load'::boolean THEN 'indexado' ELSE 'sin cambios' END,'documents',"+str(len(documents))+",'corpus_id',"+bank.design.literal(manifest['corpus_id'])+");\nCOMMIT;\n"
    return script


def ingest(state,bundle,documents,model,*,database=None):
    database=bank.environment(state,database)
    validate_bundle(bundle,documents,model)
    initialize(state,database=database)
    result=transport(state,ingestion_script(bundle,documents,model,database),database=database,write=True,check=False)
    if result.returncode:
        errors=[line for line in result.stderr.splitlines() if line.startswith(('ERROR:','DETAIL:'))]
        raise ValueError('Isolated RAG ingestion failed: '+'\n'.join(errors)[:2000])
    snapshot=query(state,snapshot_sql(bundle['manifest']['corpus_id']),database=database)
    validate_stored(snapshot,bundle['manifest'],documents,model)
    return json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.lower()) if not unicodedata.combining(c))


def evidence_eligible(question,documents):
    """Conservative subject/intent guard; cosine rank alone is never proof."""
    text=normalize(question)
    if re.search(r'\b(saldo actual|saldo de la cuenta|cuantos casos|casos observados|suma de saldos|promedio de saldos)\b',text):
        return False
    known={d.metadata['entry_id'].removeprefix('field.') for d in documents if d.metadata['kind']=='field'}
    for field in re.findall(r'\b(?:dim|cfg)\.[a-z_]+\.[a-z_]+\b',text):
        if field not in known and not field.endswith('.credit_score'):
            return False
    if re.search(r'\b202[789]\b',text) and any(w in text for w in ('tasa','crecimiento','saldo')):
        return False
    terms={normalize(term) for d in documents for term in d.metadata['query_terms']}
    return any(re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text) for term in terms)


def product_group_scope(question,documents):
    """Use a catalog facet for plural product membership, without inventing facts.

    Cosine-only top-k can omit a member of a finite, explicitly documented group.
    Ambiguous groups and negations retain the ordinary semantic search.
    """
    text=normalize(question)
    if not re.search(r'\bproductos\b',text) or re.search(r'\b(no|excepto|sin)\b',text):
        return None
    groups={d.metadata['attributes']['group'] for d in documents if d.metadata['kind']=='product'}
    matches=[group for group in groups if re.search(r'\b'+re.escape(normalize(group))+r'\b',text)]
    return matches[0] if len(matches)==1 else None


class CatalogRetriever:
    """Embedding-service agnostic, fixed documentary scope. search() keeps old result keys."""
    def __init__(self,state,documents,embeddings,model,*,model_id,corpus_id,index_manifest,database=None,min_similarity=0.35,published=False):
        if model_id!=MODEL_ID or corpus_id!=docs.corpus_identity(documents,model):
            raise ValueError("Unauthorized model_id/corpus_id; no cross-model fallback")
        docs.validate_documents(documents)
        if published:
            if state is not None or database is not None:
                raise ValueError('Published retrieval has a fixed active target')
            runtime.active_guard()
            self.database=runtime.ACTIVE_DB
            def published_read(sql):
                runtime.active_guard()
                return json.loads(runtime.psql(runtime.ACTIVE,runtime.ACTIVE_DB,
                    'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL search_path=pg_catalog; '+sql+'; COMMIT;',readonly=True).stdout)
            self.read=published_read
        else:
            self.database=bank.environment(state,database)
            self.read=lambda sql:query(state,sql,database=self.database)
        if index_manifest!=dict(base_manifest(documents,model),vectors_sha256=index_manifest.get('vectors_sha256'),vector_hashes=index_manifest.get('vector_hashes')):
            raise ValueError("Retriever index manifest mismatch")
        self.state,self.documents,self.embeddings,self.model=state,documents,embeddings,model
        self.model_id,self.corpus_id,self.manifest=model_id,corpus_id,index_manifest
        self.min_similarity=min_similarity
        _,stored=docs.storage_documents(documents,model)
        self.expected={d.id:d for d in stored}
        validate_stored(self.read(snapshot_sql(corpus_id)),index_manifest,documents,model)

    def retrieve(self,question,k=5):
        if not question.strip() or type(k) is not int or not 1<=k<=20:
            raise ValueError("Nonempty question and k in 1..20 required")
        if not evidence_eligible(question,self.documents):
            return {'status':'no_evidence','model_id':self.model_id,'corpus_id':self.corpus_id,'results':[]}
        assert_model_current(self.model)
        vector=self.embeddings.embed_query(question)
        legacy.validate_vectors([vector],1,DIMENSION)
        assert_model_current(self.model)
        text=bank.design.literal(Vector(vector).to_text())+'::public.vector'
        group=product_group_scope(question,self.documents)
        priority=("CASE WHEN metadata->>'kind'='product' AND metadata->'attributes'->>'group'="
            +bank.design.literal(group)+" THEN 0 ELSE 1 END") if group else '1'
        sql=f"SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY selection_priority,distance,id),'[]') FROM (SELECT id::text,content,metadata,embedding_sha256,"
        sql+="encode(sha256(public.vector_send(embedding)),'hex') AS actual_vector_sha256,public.vector_dims(embedding) AS dimension,"
        sql+=f"{priority} AS selection_priority,(embedding OPERATOR(public.<=>) {text}) AS distance FROM {SCHEMA}.documents WHERE model_id={bank.design.literal(self.model_id)} AND corpus_id={bank.design.literal(self.corpus_id)}::uuid ORDER BY selection_priority,distance,id LIMIT {int(k)}) r"
        rows=self.read(sql)
        results=[]
        for row in rows:
            doc=self.expected.get(row['id'])
            if doc is None or row['content']!=doc.page_content or row['metadata']!=doc.metadata:
                raise ValueError("Retrieved evidence identity/content mismatch")
            if (row['dimension']!=DIMENSION or row['embedding_sha256']!=self.manifest['vector_hashes'][row['id']]
                or row['actual_vector_sha256']!=row['embedding_sha256']):
                raise ValueError("Retrieved embedding integrity mismatch")
            distance=float(row['distance'])
            if not math.isfinite(distance):
                raise ValueError("Non-finite retrieval score")
            similarity=1-distance
            if similarity<self.min_similarity:
                continue
            results.append({'id':row['id'],'content':row['content'],'source':row['metadata']['source'],
                'source_version':row['metadata']['source_version'],'metadata':row['metadata'],
                'cosine_distance':distance,'cosine_similarity':similarity,
                'selection_priority':row.get('selection_priority',1),
                'references':row['metadata']['claims'],'assertion_origins':row['metadata']['assertion_origins']})
        return {'status':'evidence' if results else 'no_evidence','model_id':self.model_id,'corpus_id':self.corpus_id,
            'retrieval_strategy':'catalog_group_then_cosine' if group else 'cosine','results':results}

    def search(self,question,k=5):
        return self.retrieve(question,k)['results']


def evaluate(retriever,cases=None):
    cases=json.loads(CASES_PATH.read_text(encoding='utf-8')) if cases is None else cases
    reports=[]
    for case in cases:
        reply=retriever.retrieve(case['question'],case.get('k',5))
        actual=[r['metadata']['entry_id'] for r in reply['results']]
        expected=set(case.get('expected_entries',[]))
        passed=(reply['status']=='no_evidence') if case.get('no_evidence') else expected.issubset(actual)
        reciprocal=1/(min(actual.index(e) for e in expected if e in actual)+1) if any(e in actual for e in expected) else 0
        reports.append({**case,'passed':passed,'status':reply['status'],'retrieved_entries':actual,
            'retrieval_strategy':reply.get('retrieval_strategy','abstention'),
            'reciprocal_rank':reciprocal,'scores':[r['cosine_similarity'] for r in reply['results']],
            'assertion_origins':[r['assertion_origins'] for r in reply['results']]})
    positives=[r for r in reports if not r.get('no_evidence')]
    return {'model_id':retriever.model_id,'corpus_id':retriever.corpus_id,'total':len(reports),
        'passed':sum(r['passed'] for r in reports),'positive_mrr':sum(r['reciprocal_rank'] for r in positives)/len(positives),
        'cases':reports,'score_is_correctness_proof':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','ingest','verify','search','evaluate'))
    parser.add_argument('--state',required=True)
    parser.add_argument('--bundle',required=True,help='prepared vector bundle inside ignored .local-validation')
    parser.add_argument('--model-id')
    parser.add_argument('--corpus-id')
    parser.add_argument('--question')
    parser.add_argument('--k',type=int,default=5)
    args=parser.parse_args(argv)
    _,state=runtime.load_state(args.state)
    bank.environment(state)
    path=Path(args.bundle).resolve()
    if not path.is_relative_to(runtime.LOCAL.resolve()):
        parser.error('Vector bundle must remain in ignored local validation directory')
    documents=docs.build_documents()
    embeddings,model=probe()
    if args.command=='prepare':
        bundle=prepare_vectors(documents,embeddings,model)
        assert_model_current(model)
        if path.exists():
            raise ValueError('Bundle path already exists; no replacement')
        runtime.save(path,bundle)
        if INDEX_PATH.exists() and json.loads(INDEX_PATH.read_text(encoding='utf-8'))!=bundle['manifest']:
            raise ValueError('Existing index reference differs; review a version change')
        runtime.save(INDEX_PATH,bundle['manifest'])
        result={'prepared':len(documents),'embedding_model':asdict(model),'corpus_id':bundle['manifest']['corpus_id']}
    else:
        bundle=json.loads(path.read_text(encoding='utf-8'))
        validate_bundle(bundle,documents,model)
        if args.command=='ingest':
            assert_model_current(model)
            result=ingest(state,bundle,documents,model)
        elif args.command=='verify':
            result={'verified':validate_stored(query(state,snapshot_sql(bundle['manifest']['corpus_id'])),bundle['manifest'],documents,model)}
        else:
            if not args.model_id or not args.corpus_id:
                parser.error('Explicit --model-id and --corpus-id required for retrieval')
            retriever=CatalogRetriever(state,documents,embeddings,model,model_id=args.model_id,
                corpus_id=args.corpus_id,index_manifest=bundle['manifest'])
            result=evaluate(retriever) if args.command=='evaluate' else retriever.retrieve(args.question or '',args.k)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
