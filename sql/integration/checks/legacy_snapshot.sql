-- Canonical protected-table snapshot; future approved inspection only.
-- Hash all row columns, including stored embedding values. Do not call old verify().
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '120s';
SET LOCAL extra_float_digits = 3;
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL TIME ZONE 'UTC';
WITH protected(schema_name, table_name) AS (
    VALUES ('public','CUSTOMER'), ('public','TRANSACTION'), ('public','LOAN'),
           ('bank_knowledge','corpora'), ('bank_knowledge','documents')
), relations AS (
    SELECT p.*, c.oid FROM protected p JOIN pg_namespace n ON n.nspname=p.schema_name
    JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=p.table_name
), column_signatures AS (
    SELECT r.schema_name || '.' || r.table_name AS label,
           jsonb_agg(jsonb_build_object('column',a.attname,'position',a.attnum,
             'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,
             'default',pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,
             'generated',a.attgenerated) ORDER BY a.attnum) AS signature
    FROM relations r JOIN pg_attribute a ON a.attrelid=r.oid AND a.attnum>0 AND NOT a.attisdropped
    LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    GROUP BY r.schema_name,r.table_name
), constraint_signatures AS (
    SELECT r.schema_name || '.' || r.table_name AS label,
        COALESCE(jsonb_agg(jsonb_build_object('name',k.conname,'kind',k.contype,
          'definition',pg_get_constraintdef(k.oid,FALSE),'validated',k.convalidated)
          ORDER BY k.conname) FILTER (WHERE k.oid IS NOT NULL),'[]'::JSONB) AS signature
    FROM relations r LEFT JOIN pg_constraint k ON k.conrelid=r.oid
    GROUP BY r.schema_name,r.table_name
), index_signatures AS (
    SELECT r.schema_name || '.' || r.table_name AS label,
        COALESCE(jsonb_agg(jsonb_build_object('definition',pg_get_indexdef(i.indexrelid),
          'valid',i.indisvalid) ORDER BY pg_get_indexdef(i.indexrelid))
          FILTER (WHERE i.indexrelid IS NOT NULL),'[]'::JSONB) AS signature
    FROM relations r LEFT JOIN pg_index i ON i.indrelid=r.oid
    GROUP BY r.schema_name,r.table_name
), row_hashes AS (
    SELECT 'public.CUSTOMER' AS label, COUNT(*) AS rows,
      encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::TEXT,E'\n' ORDER BY customer_id),''),'UTF8')),'hex') AS sha256
      FROM public."CUSTOMER" t
    UNION ALL SELECT 'public.TRANSACTION', COUNT(*),
      encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::TEXT,E'\n' ORDER BY transaction_id),''),'UTF8')),'hex')
      FROM public."TRANSACTION" t
    UNION ALL SELECT 'public.LOAN', COUNT(*),
      encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::TEXT,E'\n' ORDER BY loan_id),''),'UTF8')),'hex')
      FROM public."LOAN" t
    UNION ALL SELECT 'bank_knowledge.corpora', COUNT(*),
      encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::TEXT,E'\n' ORDER BY corpus_id),''),'UTF8')),'hex')
      FROM bank_knowledge.corpora t
    UNION ALL SELECT 'bank_knowledge.documents', COUNT(*),
      encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::TEXT,E'\n' ORDER BY id),''),'UTF8')),'hex')
      FROM bank_knowledge.documents t
)
SELECT jsonb_build_object(
    'snapshot_format','legacy-protected-v1',
    'context',jsonb_build_object('database',current_database(),'role',current_user,
                               'server_version',current_setting('server_version')),
    'protected',jsonb_build_object(
        'relations_found',(SELECT COUNT(*) FROM relations),
        'rows',(SELECT jsonb_object_agg(label,jsonb_build_object('count',rows,'sha256',sha256)) FROM row_hashes),
        'columns',(SELECT jsonb_object_agg(label,signature) FROM column_signatures),
        'constraints',(SELECT jsonb_object_agg(label,signature) FROM constraint_signatures),
        'indexes',(SELECT jsonb_object_agg(label,signature) FROM index_signatures),
        'vector_extension',(SELECT extversion FROM pg_extension WHERE extname='vector'),
        'vectors',(SELECT jsonb_build_object('documents',COUNT(*),
                    'null_embeddings',COUNT(*) FILTER (WHERE embedding IS NULL),
                    'dimensions',jsonb_agg(DISTINCT public.vector_dims(embedding))) FROM bank_knowledge.documents)
    )
);
COMMIT;
