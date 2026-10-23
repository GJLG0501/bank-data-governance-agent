WITH tables AS (
 SELECT c.oid,n.nspname||'.'||c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('dim','cfg') AND c.relkind='r'
)
SELECT jsonb_build_object(
 'tables',(SELECT jsonb_agg(name ORDER BY name) FROM tables),
 'columns',(SELECT jsonb_agg(jsonb_build_array(t.name,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
   pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated) ORDER BY t.name,a.attnum)
   FROM tables t JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped
   LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum),
 'constraints',(SELECT jsonb_agg(jsonb_build_array(t.name,k.conname,k.contype,pg_get_constraintdef(k.oid,FALSE),k.convalidated)
   ORDER BY t.name,k.conname) FROM tables t JOIN pg_constraint k ON k.conrelid=t.oid),
 'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))
   FROM tables t JOIN pg_index i ON i.indrelid=t.oid),
 'owners',(SELECT jsonb_agg(DISTINCT pg_get_userbyid(c.relowner)) FROM tables t JOIN pg_class c ON c.oid=t.oid)
);
