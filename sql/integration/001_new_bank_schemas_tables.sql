-- Generated offline by scripts.new_bank_integration, adaptation 1.0.0.
-- Review only: not applied. No data loading. Use a dedicated PostgreSQL 17 session.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(7262026, 1);
DO $schemas$
DECLARE n TEXT;
BEGIN
    IF current_setting('server_version_num')::INTEGER / 10000 <> 17 THEN
        RAISE EXCEPTION 'This adaptation requires PostgreSQL 17';
    END IF;
    FOREACH n IN ARRAY ARRAY['dim','cfg'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=n) THEN
            EXECUTE format('CREATE SCHEMA %I', n);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_namespace ns JOIN pg_roles r ON r.oid=ns.nspowner
                       WHERE ns.nspname=n AND r.rolname=current_user) THEN
            RAISE EXCEPTION 'Schema % must be owned by the current migration role', n;
        END IF;
    END LOOP;
END;
$schemas$;

DO $bootstrap$
BEGIN
    EXECUTE format('CREATE TEMP TABLE %I (marker BOOLEAN)', '_nbm_boot_' || replace(gen_random_uuid()::TEXT, '-', ''));
END;
$bootstrap$;

CREATE OR REPLACE FUNCTION pg_temp.nbm_columns(p_table OID) RETURNS JSONB
LANGUAGE SQL STABLE SET search_path = pg_catalog AS $columns$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'name', a.attname, 'type', format_type(a.atttypid, a.atttypmod),
        'not_null', a.attnotnull, 'default', pg_get_expr(d.adbin, d.adrelid),
        'identity', a.attidentity, 'generated', a.attgenerated,
        'collation', a.attcollation, 'dimensions', a.attndims, 'removed', a.attisdropped
    ) ORDER BY a.attnum), '[]'::JSONB)
    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE a.attrelid=p_table AND a.attnum>0;
$columns$;

CREATE OR REPLACE FUNCTION pg_temp.nbm_constraint(p_constraint OID) RETURNS JSONB
LANGUAGE SQL STABLE SET search_path = pg_catalog AS $constraint$
    SELECT jsonb_build_object('kind', k.contype, 'deferrable', k.condeferrable,
        'deferred', k.condeferred, 'validated', k.convalidated)
    || CASE WHEN k.contype='f' THEN jsonb_build_object(
        'columns', (SELECT jsonb_agg(a.attname ORDER BY u.ord) FROM unnest(k.conkey) WITH ORDINALITY u(num,ord)
                    JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=u.num),
        'target', (SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=k.confrelid),
        'ref_columns', (SELECT jsonb_agg(a.attname ORDER BY u.ord) FROM unnest(k.confkey) WITH ORDINALITY u(num,ord)
                        JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=u.num),
        'update', k.confupdtype, 'delete', k.confdeltype, 'match', k.confmatchtype)
    ELSE jsonb_build_object('definition', pg_get_constraintdef(k.oid, FALSE), 'no_inherit', k.connoinherit) END
    FROM pg_constraint k WHERE k.oid=p_constraint;
$constraint$;

DO $integration$
DECLARE
    s JSONB; e JSONB; wanted JSONB; actual JSONB; required JSONB; allowed JSONB;
    actual_fk JSONB; allowed_fk JSONB; c JSONB; raw_columns JSONB; full_columns JSONB;
    relation OID; raw_ref OID; full_ref OID; ref_name TEXT; ref_body TEXT;
    needs_change BOOLEAN; has_rows BOOLEAN; i INTEGER;
    apply_integrity CONSTANT BOOLEAN := FALSE;
BEGIN
    FOR s IN SELECT value FROM jsonb_array_elements($spec$[
  {
    "schema": "dim",
    "table": "dim_cliente",
    "qualified": "dim.dim_cliente",
    "auxiliary": false,
    "base_body": "num_cte INTEGER NOT NULL,\n    fec_alta DATE,\n    fec_nac DATE,\n    tipo_persona VARCHAR(10),\n    genero_cte VARCHAR(10),\n    segmento_cte VARCHAR(20),\n    giro_empresa VARCHAR(30),\n    cve_territorio VARCHAR(255),\n    cve_dir VARCHAR(255),\n    cve_subdir VARCHAR(255),\n    cve_sucursal INTEGER,\n    cve_promotor VARCHAR(10),\n    PRIMARY KEY (num_cte),\n    CHECK (tipo_persona IN ('PF','PM')),\n    CHECK (genero_cte IN ('HOMBRE','MUJER','NO APLICA'))",
    "full_body": "num_cte INTEGER NOT NULL,\n    fec_alta DATE,\n    fec_nac DATE,\n    tipo_persona VARCHAR(10),\n    genero_cte VARCHAR(10),\n    segmento_cte VARCHAR(20),\n    giro_empresa VARCHAR(30),\n    cve_territorio VARCHAR(255),\n    cve_dir VARCHAR(255),\n    cve_subdir VARCHAR(255),\n    cve_sucursal INTEGER,\n    cve_promotor VARCHAR(10),\n    PRIMARY KEY (num_cte),\n    CHECK (tipo_persona IN ('PF','PM')),\n    CHECK (genero_cte IN ('HOMBRE','MUJER','NO APLICA'))",
    "checks": [],
    "fks": [],
    "not_null": []
  },
  {
    "schema": "dim",
    "table": "dim_producto",
    "qualified": "dim.dim_producto",
    "auxiliary": false,
    "base_body": "cve_producto VARCHAR(40) NOT NULL,\n    cve_dominio VARCHAR(20) NOT NULL,\n    grupo_producto VARCHAR(20) NOT NULL,\n    cve_subproducto VARCHAR(40) NOT NULL,\n    descripcion VARCHAR(100),\n    activo BOOLEAN DEFAULT TRUE,\n    PRIMARY KEY (cve_producto),\n    CHECK (cve_dominio IN ('DEPOSITS','LENDING','TDC'))",
    "full_body": "cve_producto VARCHAR(40) NOT NULL,\n    cve_dominio VARCHAR(20) NOT NULL,\n    grupo_producto VARCHAR(20) NOT NULL,\n    cve_subproducto VARCHAR(40) NOT NULL,\n    descripcion VARCHAR(100),\n    activo BOOLEAN DEFAULT TRUE,\n    PRIMARY KEY (cve_producto),\n    CHECK (cve_dominio IN ('DEPOSITS','LENDING','TDC'))",
    "checks": [],
    "fks": [],
    "not_null": []
  },
  {
    "schema": "dim",
    "table": "dim_txn",
    "qualified": "dim.dim_txn",
    "auxiliary": false,
    "base_body": "cve_producto VARCHAR(40) NOT NULL,\n    cve_dominio VARCHAR(20) NOT NULL,\n    grupo_producto VARCHAR(20) NOT NULL,\n    cve_txn INTEGER NOT NULL,\n    desc_txn VARCHAR(40) NOT NULL",
    "full_body": "cve_producto VARCHAR(40) NOT NULL,\n    cve_dominio VARCHAR(20) NOT NULL,\n    grupo_producto VARCHAR(20) NOT NULL,\n    cve_txn INTEGER NOT NULL,\n    desc_txn VARCHAR(40) NOT NULL",
    "checks": [],
    "fks": [],
    "not_null": []
  },
  {
    "schema": "cfg",
    "table": "fact_sdos_captacoloca_m",
    "qualified": "cfg.fact_sdos_captacoloca_m",
    "auxiliary": false,
    "base_body": "num_cta INTEGER,\n    num_cte INTEGER,\n    cve_producto VARCHAR(40),\n    fec_alta DATE,\n    cve_mes_alta INTEGER,\n    saldo_apertura NUMERIC(18,2),\n    saldo_mes NUMERIC(18,2),\n    fec_informacion INTEGER,\n    dominio VARCHAR(20)",
    "full_body": "num_cta INTEGER NOT NULL,\n    num_cte INTEGER NOT NULL,\n    cve_producto VARCHAR(40) NOT NULL,\n    fec_alta DATE NOT NULL,\n    cve_mes_alta INTEGER NOT NULL,\n    saldo_apertura NUMERIC(18,2) NOT NULL,\n    saldo_mes NUMERIC(18,2) NOT NULL,\n    fec_informacion INTEGER NOT NULL,\n    dominio VARCHAR(20) NOT NULL",
    "checks": [
      {
        "name": "nbm_sdos_cuenta_corte_uq",
        "clause": "UNIQUE (num_cta, cve_producto, fec_informacion)"
      },
      {
        "name": "nbm_sdos_corte_ck",
        "clause": "CHECK (fec_informacion IN (20260131,20260228,20260331,20260430,20260531,20260630))"
      },
      {
        "name": "nbm_sdos_alta_ck",
        "clause": "CHECK (fec_alta = DATE '2026-01-01' AND cve_mes_alta = 202601)"
      },
      {
        "name": "nbm_sdos_importes_ck",
        "clause": "CHECK (saldo_apertura > 0 AND saldo_apertura < 'Infinity'::NUMERIC AND saldo_mes > 0 AND saldo_mes < 'Infinity'::NUMERIC)"
      },
      {
        "name": "nbm_sdos_dominio_origen_ck",
        "clause": "CHECK (dominio = CASE WHEN fec_informacion = 20260131 THEN CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'CAPTACION' ELSE 'COLOCACION' END ELSE CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'DEPOSITS' WHEN cve_producto = 'C_PERSONAL' THEN 'LENDING' WHEN cve_producto = 'TDC' THEN 'TDC' END END)"
      },
      {
        "name": "nbm_sdos_enero_ck",
        "clause": "CHECK (fec_informacion <> 20260131 OR (saldo_mes = saldo_apertura AND ((cve_producto = 'CHEQUES' AND saldo_apertura BETWEEN 8000.00 AND 12000.00) OR (cve_producto = 'AHORRO' AND saldo_apertura BETWEEN 5.00 AND 10000.00) OR (cve_producto = 'TDC' AND saldo_apertura BETWEEN 10000.00 AND 120000.00) OR (cve_producto = 'C_PERSONAL' AND saldo_apertura BETWEEN 50000.00 AND 85000.00))))"
      },
      {
        "name": "nbm_sdos_objetivo_ck",
        "clause": "CHECK (fec_informacion = 20260131 OR saldo_mes = ROUND(saldo_apertura * (1 + CASE WHEN fec_informacion = 20260228 THEN CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 0.02 ELSE 0.03 END ELSE CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 0.01 ELSE 0.022 END END), 2))"
      }
    ],
    "fks": [
      {
        "name": "nbm_sdos_cuenta_fk",
        "clause": "FOREIGN KEY (num_cta, cve_producto, num_cte) REFERENCES cfg.ref_cuenta_modelo (num_cta, cve_producto, num_cte) ON UPDATE RESTRICT ON DELETE RESTRICT",
        "signature": {
          "kind": "f",
          "columns": [
            "num_cta",
            "cve_producto",
            "num_cte"
          ],
          "target": "cfg.ref_cuenta_modelo",
          "ref_columns": [
            "num_cta",
            "cve_producto",
            "num_cte"
          ],
          "update": "r",
          "delete": "r",
          "match": "s",
          "deferrable": false,
          "deferred": false,
          "validated": true
        }
      }
    ],
    "not_null": [
      "num_cta",
      "num_cte",
      "cve_producto",
      "fec_alta",
      "cve_mes_alta",
      "saldo_apertura",
      "saldo_mes",
      "fec_informacion",
      "dominio"
    ]
  },
  {
    "schema": "cfg",
    "table": "fact_txn_captacoloca_d",
    "qualified": "cfg.fact_txn_captacoloca_d",
    "auxiliary": false,
    "base_body": "num_cta INTEGER,\n    num_cte INTEGER,\n    cve_producto VARCHAR(40),\n    fec_txn DATE,\n    cve_mes_txn INTEGER,\n    saldo_txn NUMERIC(18,2),\n    cve_txn INTEGER,\n    desc_txn VARCHAR(40),\n    fec_informacion INTEGER,\n    dominio VARCHAR(20)",
    "full_body": "num_cta INTEGER NOT NULL,\n    num_cte INTEGER NOT NULL,\n    cve_producto VARCHAR(40) NOT NULL,\n    fec_txn DATE NOT NULL,\n    cve_mes_txn INTEGER NOT NULL,\n    saldo_txn NUMERIC(18,2) NOT NULL,\n    cve_txn INTEGER NOT NULL,\n    desc_txn VARCHAR(40) NOT NULL,\n    fec_informacion INTEGER NOT NULL,\n    dominio VARCHAR(20) NOT NULL",
    "checks": [
      {
        "name": "nbm_txn_evento_sintetico_uq",
        "clause": "UNIQUE (num_cta, cve_producto, cve_mes_txn, cve_txn)"
      },
      {
        "name": "nbm_txn_mes_ck",
        "clause": "CHECK (cve_mes_txn IN (202602,202603,202604,202605,202606))"
      },
      {
        "name": "nbm_txn_fecha_ck",
        "clause": "CHECK (isfinite(fec_txn) AND EXTRACT(DAY FROM fec_txn) = 15 AND EXTRACT(YEAR FROM fec_txn)*100 + EXTRACT(MONTH FROM fec_txn) = cve_mes_txn)"
      },
      {
        "name": "nbm_txn_corte_ck",
        "clause": "CHECK (fec_informacion IN (20260228,20260331,20260430,20260531,20260630) AND fec_informacion / 100 = cve_mes_txn)"
      },
      {
        "name": "nbm_txn_importe_ck",
        "clause": "CHECK (saldo_txn > 0 AND saldo_txn < 'Infinity'::NUMERIC)"
      },
      {
        "name": "nbm_txn_dominio_origen_ck",
        "clause": "CHECK (dominio = CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'DEPOSITS' WHEN cve_producto = 'C_PERSONAL' THEN 'LENDING' WHEN cve_producto = 'TDC' THEN 'TDC' END)"
      }
    ],
    "fks": [
      {
        "name": "nbm_txn_cuenta_fk",
        "clause": "FOREIGN KEY (num_cta, cve_producto, num_cte) REFERENCES cfg.ref_cuenta_modelo (num_cta, cve_producto, num_cte) ON UPDATE RESTRICT ON DELETE RESTRICT",
        "signature": {
          "kind": "f",
          "columns": [
            "num_cta",
            "cve_producto",
            "num_cte"
          ],
          "target": "cfg.ref_cuenta_modelo",
          "ref_columns": [
            "num_cta",
            "cve_producto",
            "num_cte"
          ],
          "update": "r",
          "delete": "r",
          "match": "s",
          "deferrable": false,
          "deferred": false,
          "validated": true
        }
      },
      {
        "name": "nbm_txn_catalogo_fk",
        "clause": "FOREIGN KEY (cve_producto, cve_txn, desc_txn) REFERENCES cfg.ref_txn_modelo (cve_producto, cve_txn, desc_txn) ON UPDATE RESTRICT ON DELETE RESTRICT",
        "signature": {
          "kind": "f",
          "columns": [
            "cve_producto",
            "cve_txn",
            "desc_txn"
          ],
          "target": "cfg.ref_txn_modelo",
          "ref_columns": [
            "cve_producto",
            "cve_txn",
            "desc_txn"
          ],
          "update": "r",
          "delete": "r",
          "match": "s",
          "deferrable": false,
          "deferred": false,
          "validated": true
        }
      }
    ],
    "not_null": [
      "num_cta",
      "num_cte",
      "cve_producto",
      "fec_txn",
      "cve_mes_txn",
      "saldo_txn",
      "cve_txn",
      "desc_txn",
      "fec_informacion",
      "dominio"
    ]
  }
]$spec$::JSONB) LOOP
        SELECT cl.oid INTO relation FROM pg_class cl JOIN pg_namespace ns ON ns.oid=cl.relnamespace
        WHERE ns.nspname=s->>'schema' AND cl.relname=s->>'table';
        IF relation IS NULL THEN
            IF apply_integrity AND NOT (s->>'auxiliary')::BOOLEAN THEN
                RAISE EXCEPTION 'Missing base table %, apply migration 001 first', s->>'qualified';
            END IF;
            EXECUTE format('CREATE TABLE %I.%I (%s)', s->>'schema', s->>'table', s->>'base_body');
            relation := to_regclass(format('%I.%I', s->>'schema', s->>'table'));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_class cl WHERE cl.oid=relation AND cl.relkind='r'
            AND cl.relpersistence='p' AND NOT cl.relispartition AND NOT cl.relrowsecurity
            AND NOT cl.relforcerowsecurity AND cl.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))
            OR EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid=relation OR inhparent=relation)
            OR EXISTS (SELECT 1 FROM pg_policy WHERE polrelid=relation)
            OR EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid=relation AND NOT tgisinternal)
            OR EXISTS (SELECT 1 FROM pg_rewrite WHERE ev_class=relation)
            OR EXISTS (SELECT 1 FROM pg_index idx WHERE idx.indrelid=relation AND
                (NOT idx.indisvalid OR NOT idx.indisready OR NOT EXISTS
                 (SELECT 1 FROM pg_constraint k WHERE k.conrelid=relation AND k.conindid=idx.indexrelid AND k.contype IN ('p','u')))) THEN
            RAISE EXCEPTION 'Incompatible owner, table kind, policies, inheritance, triggers, rules or indexes: %', s->>'qualified';
        END IF;
        EXECUTE format('LOCK TABLE %I.%I IN SHARE ROW EXCLUSIVE MODE', s->>'schema', s->>'table');

        ref_name := '_nbm_raw_' || replace(gen_random_uuid()::TEXT, '-', '');
        EXECUTE format('CREATE TEMP TABLE %I (%s)', ref_name, s->>'base_body');
        raw_ref := to_regclass(format('pg_temp.%I', ref_name));
        ref_name := '_nbm_full_' || replace(gen_random_uuid()::TEXT, '-', '');
        ref_body := s->>'full_body';
        i := 0;
        FOR e IN SELECT value FROM jsonb_array_elements(s->'checks') LOOP
            i := i+1;
            ref_body := ref_body || format(', CONSTRAINT %I %s', ref_name || '_e' || i, e->>'clause');
        END LOOP;
        EXECUTE format('CREATE TEMP TABLE %I (%s)', ref_name, ref_body);
        full_ref := to_regclass(format('pg_temp.%I', ref_name));
        raw_columns := pg_temp.nbm_columns(raw_ref);
        full_columns := pg_temp.nbm_columns(full_ref);
        c := pg_temp.nbm_columns(relation);
        IF c <> raw_columns AND c <> full_columns THEN
            RAISE EXCEPTION 'Incompatible columns (order/type/length/null/default/identity/collation): %', s->>'qualified';
        END IF;
        SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO actual FROM
            (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=relation AND contype<>'f') q;
        SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO required FROM
            (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=raw_ref) q;
        SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO allowed FROM
            (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=full_ref) q;
        SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO actual_fk FROM
            (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=relation AND contype='f') q;
        SELECT COALESCE(jsonb_agg(value->'signature'), '[]'::JSONB) INTO allowed_fk FROM jsonb_array_elements(s->'fks');
        IF NOT (required <@ actual AND actual <@ allowed AND actual_fk <@ allowed_fk)
           OR jsonb_array_length(actual) <> (SELECT COUNT(DISTINCT value) FROM jsonb_array_elements(actual))
           OR jsonb_array_length(actual_fk) <> (SELECT COUNT(DISTINCT value) FROM jsonb_array_elements(actual_fk)) THEN
            RAISE EXCEPTION 'Incompatible, missing base, duplicate or unvalidated constraints: %', s->>'qualified';
        END IF;
        needs_change := c <> full_columns OR NOT (allowed <@ actual) OR NOT (allowed_fk <@ actual_fk);
        IF apply_integrity AND needs_change THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I)', s->>'schema', s->>'table') INTO has_rows;
            IF has_rows THEN
                RAISE EXCEPTION 'Refusing to adopt/strengthen nonempty table %. Review a separate data migration.', s->>'qualified';
            END IF;
            FOR e IN SELECT value FROM jsonb_array_elements(s->'not_null') LOOP
                EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I SET NOT NULL', s->>'schema', s->>'table', e #>> '{}');
            END LOOP;
            i := 0;
            FOR e IN SELECT value FROM jsonb_array_elements(s->'checks') LOOP
                i := i+1;
                SELECT pg_temp.nbm_constraint(oid) INTO wanted FROM pg_constraint
                    WHERE conrelid=full_ref AND conname=ref_name || '_e' || i;
                IF NOT actual @> jsonb_build_array(wanted) THEN
                    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid=relation AND conname=e->>'name') THEN
                        RAISE EXCEPTION 'Constraint name collision on %', s->>'qualified';
                    END IF;
                    EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s', s->>'schema', s->>'table', e->>'name', e->>'clause');
                END IF;
            END LOOP;
            FOR e IN SELECT value FROM jsonb_array_elements(s->'fks') LOOP
                IF NOT actual_fk @> jsonb_build_array(e->'signature') THEN
                    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid=relation AND conname=e->>'name') THEN
                        RAISE EXCEPTION 'Constraint name collision on %', s->>'qualified';
                    END IF;
                    EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s', s->>'schema', s->>'table', e->>'name', e->>'clause');
                END IF;
            END LOOP;
            SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO actual FROM
                (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=relation AND contype<>'f') q;
            SELECT COALESCE(jsonb_agg(sig ORDER BY sig::TEXT), '[]'::JSONB) INTO actual_fk FROM
                (SELECT pg_temp.nbm_constraint(oid) sig FROM pg_constraint WHERE conrelid=relation AND contype='f') q;
            IF pg_temp.nbm_columns(relation) <> full_columns OR actual <> allowed
               OR NOT (actual_fk <@ allowed_fk AND allowed_fk <@ actual_fk) THEN
                RAISE EXCEPTION 'Postcondition failed for %', s->>'qualified';
            END IF;
        END IF;
    END LOOP;
END;
$integration$;

COMMIT;
