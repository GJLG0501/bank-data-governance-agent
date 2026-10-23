-- Read-only inspection for a FUTURE approved run; no schema validation by DDL.
BEGIN TRANSACTION READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '30s';
SELECT current_database() AS database_name, current_user AS role_name,
       current_setting('server_version') AS server_version,
       current_setting('transaction_read_only') AS transaction_read_only;
SELECT extname, extversion FROM pg_extension WHERE extname='vector';
SELECT n.nspname AS schema_name, r.rolname AS owner
FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
WHERE n.nspname IN ('public','bank_knowledge','dim','cfg') ORDER BY n.nspname;
SELECT n.nspname, c.relname, c.relkind, c.relpersistence, r.rolname AS owner,
       c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_roles r ON r.oid=c.relowner
WHERE n.nspname IN ('dim','cfg','bank_knowledge') OR
      (n.nspname='public' AND c.relname IN ('CUSTOMER','TRANSACTION','LOAN'))
ORDER BY n.nspname,c.relname;
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin
FROM pg_roles WHERE rolname=current_user;
COMMIT;
