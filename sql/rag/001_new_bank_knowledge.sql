-- New-bank documentary RAG only. Execute through the isolated transport guard.
BEGIN;
SET LOCAL search_path=pg_catalog;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(7262026,3);
DO $pre$
BEGIN
 IF current_setting('server_version_num')::int/10000<>17 OR NOT EXISTS(
    SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
    WHERE e.extname='vector' AND e.extversion='0.8.7' AND n.nspname='public')
 THEN RAISE EXCEPTION 'Requires reviewed PostgreSQL 17 and public vector 0.8.7'; END IF;
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='bank_knowledge_new_bank'
           AND pg_get_userbyid(nspowner)<>current_user)
 THEN RAISE EXCEPTION 'RAG schema owner mismatch'; END IF;
END $pre$;

-- Session-local references define the exact compatible shape, including checks.
CREATE TEMP TABLE corpora (
 corpus_id UUID PRIMARY KEY,
 model_id TEXT NOT NULL CHECK(model_id='new_bank_2026'),
 manifest JSONB NOT NULL,
 UNIQUE(corpus_id,model_id),
 CHECK(jsonb_typeof(manifest)='object' AND manifest ?& ARRAY['format','model_id','corpus_id','document_manifest','embedding_model','vectors_sha256','vector_hashes']
   AND manifest->>'model_id'=model_id AND manifest->>'corpus_id'=corpus_id::text
   AND manifest->>'format'='new-bank-vector-index-v1'
   AND manifest->'embedding_model'->>'dimension'='1024')
);
CREATE TEMP TABLE documents (
 id UUID PRIMARY KEY,
 corpus_id UUID NOT NULL,
 model_id TEXT NOT NULL CHECK(model_id='new_bank_2026'),
 content TEXT NOT NULL,
 metadata JSONB NOT NULL,
 embedding public.vector(1024) NOT NULL,
 embedding_sha256 TEXT NOT NULL,
 FOREIGN KEY(corpus_id,model_id) REFERENCES pg_temp.corpora(corpus_id,model_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CHECK(jsonb_typeof(metadata)='object' AND metadata ?& ARRAY['model_id','corpus_id','chunk_sha256','claims','embedding_dimension','entry_id']
   AND metadata->>'model_id'=model_id AND metadata->>'corpus_id'=corpus_id::text
   AND metadata->>'embedding_dimension'='1024'
   AND metadata->>'chunk_sha256'=encode(sha256(convert_to(content,'UTF8')),'hex')),
 CHECK(embedding_sha256=encode(sha256(public.vector_send(embedding)),'hex'))
);

CREATE FUNCTION pg_temp.nbm_rag_signature(relation OID) RETURNS JSONB
LANGUAGE SQL STABLE SET search_path=pg_catalog AS $signature$
 SELECT jsonb_build_object(
 'columns',(SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
    a.attidentity,a.attgenerated,a.attcollation,a.attndims,a.attisdropped,pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE a.attrelid=relation AND a.attnum>0),
 'constraints',(SELECT jsonb_agg(value ORDER BY value::text) FROM (
    SELECT jsonb_build_object('kind',k.contype,'validated',k.convalidated,'deferrable',k.condeferrable,'deferred',k.condeferred)
     ||CASE WHEN k.contype='f' THEN jsonb_build_object('columns',k.conkey::text,'target',(SELECT relname FROM pg_class WHERE oid=k.confrelid),
         'references',k.confkey::text,'update',k.confupdtype,'delete',k.confdeltype,'match',k.confmatchtype)
       ELSE jsonb_build_object('definition',pg_get_constraintdef(k.oid,false)) END value
    FROM pg_constraint k WHERE k.conrelid=relation) q),
 'indexes',(SELECT jsonb_agg(value ORDER BY value::text) FROM (
    SELECT jsonb_build_array(i.indkey::text,i.indclass::text,i.indoption::text,i.indisunique,i.indisprimary,
      i.indisvalid,i.indisready,i.indisexclusion,i.indnullsnotdistinct,c.relam,
      pg_get_expr(i.indexprs,i.indrelid),pg_get_expr(i.indpred,i.indrelid)) value
    FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE i.indrelid=relation) q))
$signature$;

DO $schema$
DECLARE new_schema BOOLEAN; name TEXT; relation OID;
BEGIN
 new_schema:=to_regnamespace('bank_knowledge_new_bank') IS NULL;
 IF new_schema THEN
  CREATE SCHEMA bank_knowledge_new_bank;
  CREATE TABLE bank_knowledge_new_bank.corpora (
   corpus_id UUID PRIMARY KEY,
   model_id TEXT NOT NULL CHECK(model_id='new_bank_2026'),
   manifest JSONB NOT NULL,
   UNIQUE(corpus_id,model_id),
   CHECK(jsonb_typeof(manifest)='object' AND manifest ?& ARRAY['format','model_id','corpus_id','document_manifest','embedding_model','vectors_sha256','vector_hashes']
     AND manifest->>'model_id'=model_id AND manifest->>'corpus_id'=corpus_id::text
     AND manifest->>'format'='new-bank-vector-index-v1'
     AND manifest->'embedding_model'->>'dimension'='1024')
  );
  CREATE TABLE bank_knowledge_new_bank.documents (
   id UUID PRIMARY KEY,
   corpus_id UUID NOT NULL,
   model_id TEXT NOT NULL CHECK(model_id='new_bank_2026'),
   content TEXT NOT NULL,
   metadata JSONB NOT NULL,
   embedding public.vector(1024) NOT NULL,
   embedding_sha256 TEXT NOT NULL,
   FOREIGN KEY(corpus_id,model_id) REFERENCES bank_knowledge_new_bank.corpora(corpus_id,model_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
   CHECK(jsonb_typeof(metadata)='object' AND metadata ?& ARRAY['model_id','corpus_id','chunk_sha256','claims','embedding_dimension','entry_id']
     AND metadata->>'model_id'=model_id AND metadata->>'corpus_id'=corpus_id::text
     AND metadata->>'embedding_dimension'='1024'
     AND metadata->>'chunk_sha256'=encode(sha256(convert_to(content,'UTF8')),'hex')),
   CHECK(embedding_sha256=encode(sha256(public.vector_send(embedding)),'hex'))
  );
 END IF;
 IF (SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname='bank_knowledge_new_bank' AND c.relkind='r')<>2
   OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname='bank_knowledge_new_bank' AND c.relkind NOT IN ('r','i'))
   OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='bank_knowledge_new_bank')
 THEN RAISE EXCEPTION 'Incomplete or unrecognized RAG schema'; END IF;
 FOREACH name IN ARRAY ARRAY['corpora','documents'] LOOP
  relation:=to_regclass('bank_knowledge_new_bank.'||name);
  IF relation IS NULL OR NOT EXISTS(SELECT 1 FROM pg_class WHERE oid=relation
      AND relkind='r' AND relpersistence='p' AND NOT relrowsecurity AND NOT relforcerowsecurity
      AND NOT relispartition AND pg_get_userbyid(relowner)=current_user)
   OR EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=relation AND NOT tgisinternal)
   OR EXISTS(SELECT 1 FROM pg_policy WHERE polrelid=relation)
   OR EXISTS(SELECT 1 FROM pg_rewrite WHERE ev_class=relation)
   OR EXISTS(SELECT 1 FROM pg_inherits WHERE inhrelid=relation OR inhparent=relation)
  THEN RAISE EXCEPTION 'Unsafe RAG table %',name; END IF;
  IF pg_temp.nbm_rag_signature(relation) IS DISTINCT FROM pg_temp.nbm_rag_signature(to_regclass('pg_temp.'||name))
   OR EXISTS(SELECT 1 FROM pg_constraint k JOIN pg_class c ON c.oid=k.confrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE k.conrelid=relation AND k.contype='f'
      AND n.nspname<>'bank_knowledge_new_bank')
  THEN RAISE EXCEPTION 'Incompatible RAG table %',name; END IF;
 END LOOP;
END $schema$;
COMMIT;
