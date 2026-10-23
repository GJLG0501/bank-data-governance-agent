"""Render/check integration artifacts OFFLINE. No database driver or apply command."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
MODEL_ID = "new_bank_2026"
SOURCES = (
    ("U1", "sql/upstream/001_dimensiones_cliente_producto_txn.sql",
     "eee849f1bfbdc138291a81682a0ed836ac5dbd37b9c499c2a00a273377e7696a", []),
    ("U2", "sql/upstream/002_generar_cuentas_y_saldos_enero_2026.sql",
     "6dfc90c1e55b2092584499c05a74b55309aeda004d8ce135e0bc7e6f765ecd2b", ["U1", "cfg schema"]),
    ("U3", "sql/upstream/003_generar_transacciones_y_saldos_feb_jun_2026.sql",
     "d28d22b90e9882fa3780c23d1107df79ce72f9556ba8351d505eb108b0756fa3", ["U2", "January close"]),
)
PROTECTED = ('public."CUSTOMER"', 'public."TRANSACTION"', 'public."LOAN"',
             "bank_knowledge.corpora", "bank_knowledge.documents")


@dataclass(frozen=True)
class Table:
    name: str
    source: str | None
    columns: tuple[tuple[str, str], ...]
    base_constraints: tuple[str, ...] = ()
    checks: tuple[tuple[str, str], ...] = ()
    not_null: bool = False
    foreign_keys: tuple[tuple[str, tuple[str, ...], str, tuple[str, ...]], ...] = ()


def cols(text):
    return tuple(tuple(line.split(" ", 1)) for line in text.strip().splitlines())


CLIENT = Table("dim.dim_cliente", "U1", cols("""
num_cte INTEGER NOT NULL
fec_alta DATE
fec_nac DATE
tipo_persona VARCHAR(10)
genero_cte VARCHAR(10)
segmento_cte VARCHAR(20)
giro_empresa VARCHAR(30)
cve_territorio VARCHAR(255)
cve_dir VARCHAR(255)
cve_subdir VARCHAR(255)
cve_sucursal INTEGER
cve_promotor VARCHAR(10)
"""), ("PRIMARY KEY (num_cte)", "CHECK (tipo_persona IN ('PF','PM'))",
       "CHECK (genero_cte IN ('HOMBRE','MUJER','NO APLICA'))"))
PRODUCT = Table("dim.dim_producto", "U1", cols("""
cve_producto VARCHAR(40) NOT NULL
cve_dominio VARCHAR(20) NOT NULL
grupo_producto VARCHAR(20) NOT NULL
cve_subproducto VARCHAR(40) NOT NULL
descripcion VARCHAR(100)
activo BOOLEAN DEFAULT TRUE
"""), ("PRIMARY KEY (cve_producto)", "CHECK (cve_dominio IN ('DEPOSITS','LENDING','TDC'))"))
TXN = Table("dim.dim_txn", "U1", cols("""
cve_producto VARCHAR(40) NOT NULL
cve_dominio VARCHAR(20) NOT NULL
grupo_producto VARCHAR(20) NOT NULL
cve_txn INTEGER NOT NULL
desc_txn VARCHAR(40) NOT NULL
"""))

PRODUCT_ROWS = (
    ("CHEQUES", "DEPOSITS", "CAPTACION", 100000, "8000.00", "12000.00", 2),
    ("AHORRO", "DEPOSITS", "CAPTACION", 200000, "5.00", "10000.00", 2),
    ("TDC", "TDC", "COLOCACION", 300000, "10000.00", "120000.00", 3),
    ("C_PERSONAL", "LENDING", "COLOCACION", 400000, "50000.00", "85000.00", 2),
)
TRANSACTION_ROWS = (
    ("CHEQUES", 100, "DEPOSITO", "DEPOSITS", "CAPTACION", 1),
    ("CHEQUES", 200, "RETIRO", "DEPOSITS", "CAPTACION", -1),
    ("AHORRO", 100, "DEPOSITO", "DEPOSITS", "CAPTACION", 1),
    ("AHORRO", 200, "RETIRO", "DEPOSITS", "CAPTACION", -1),
    ("C_PERSONAL", 300, "PAGOS", "LENDING", "COLOCACION", -1),
    ("C_PERSONAL", 450, "DISPOSICIONES", "LENDING", "COLOCACION", 1),
    ("TDC", 300, "PAGOS", "TDC", "COLOCACION", -1),
    ("TDC", 400, "COMPRAS", "TDC", "COLOCACION", 1),
    ("TDC", 450, "DISPOSICIONES", "TDC", "COLOCACION", 1),
)
CUTS = (20260131, 20260228, 20260331, 20260430, 20260531, 20260630)


def literal(value):
    if isinstance(value, int):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def row_check(names, rows):
    return "CHECK ((" + ", ".join(names) + ") IN (\n" + ",\n".join(
        "    (" + ", ".join(map(literal, row)) + ")" for row in rows) + "\n))"


ACCOUNT_RANGE = "CHECK (" + " OR ".join(
    f"(cve_producto = '{p[0]}' AND num_cta BETWEEN {p[3]} AND {p[3]+4999})"
    for p in PRODUCT_ROWS) + ")"
REF_TXN = Table("cfg.ref_txn_modelo", None, cols("""
cve_producto VARCHAR(40) NOT NULL
cve_txn INTEGER NOT NULL
desc_txn VARCHAR(40) NOT NULL
cve_dominio VARCHAR(20) NOT NULL
grupo_producto VARCHAR(20) NOT NULL
signo_economico SMALLINT NOT NULL
regla_version VARCHAR(20) NOT NULL
"""), ("PRIMARY KEY (cve_producto, cve_txn)",
       "UNIQUE (cve_producto, cve_txn, desc_txn)",
       row_check(("cve_producto", "cve_txn", "desc_txn", "cve_dominio", "grupo_producto", "signo_economico"), TRANSACTION_ROWS),
       f"CHECK (regla_version = '{VERSION}')"), foreign_keys=(
           ("nbm_ref_txn_producto_fk", ("cve_producto",), PRODUCT.name, ("cve_producto",)),))
REF_ACCOUNT = Table("cfg.ref_cuenta_modelo", None, cols("""
num_cta INTEGER NOT NULL
num_cte INTEGER NOT NULL
cve_producto VARCHAR(40) NOT NULL
fec_alta DATE NOT NULL
cve_mes_alta INTEGER NOT NULL
"""), ("PRIMARY KEY (num_cta, cve_producto)",
       "UNIQUE (num_cta, cve_producto, num_cte)", "UNIQUE (num_cte, cve_producto)",
       ACCOUNT_RANGE, "CHECK (fec_alta = DATE '2026-01-01' AND cve_mes_alta = 202601)"),
       foreign_keys=(
           ("nbm_ref_cuenta_cliente_fk", ("num_cte",), CLIENT.name, ("num_cte",)),
           ("nbm_ref_cuenta_producto_fk", ("cve_producto",), PRODUCT.name, ("cve_producto",)),))
ACCOUNT_FK = ("num_cta", "cve_producto", "num_cte")
BALANCE = Table("cfg.fact_sdos_captacoloca_m", "U2", cols("""
num_cta INTEGER
num_cte INTEGER
cve_producto VARCHAR(40)
fec_alta DATE
cve_mes_alta INTEGER
saldo_apertura NUMERIC(18,2)
saldo_mes NUMERIC(18,2)
fec_informacion INTEGER
dominio VARCHAR(20)
"""), checks=(
    ("nbm_sdos_cuenta_corte_uq", "UNIQUE (num_cta, cve_producto, fec_informacion)"),
    ("nbm_sdos_corte_ck", f"CHECK (fec_informacion IN ({','.join(map(str,CUTS))}))"),
    ("nbm_sdos_alta_ck", "CHECK (fec_alta = DATE '2026-01-01' AND cve_mes_alta = 202601)"),
    ("nbm_sdos_importes_ck", "CHECK (saldo_apertura > 0 AND saldo_apertura < 'Infinity'::NUMERIC AND saldo_mes > 0 AND saldo_mes < 'Infinity'::NUMERIC)"),
    ("nbm_sdos_dominio_origen_ck", "CHECK (dominio = CASE WHEN fec_informacion = 20260131 THEN CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'CAPTACION' ELSE 'COLOCACION' END ELSE CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'DEPOSITS' WHEN cve_producto = 'C_PERSONAL' THEN 'LENDING' WHEN cve_producto = 'TDC' THEN 'TDC' END END)"),
    ("nbm_sdos_enero_ck", "CHECK (fec_informacion <> 20260131 OR (saldo_mes = saldo_apertura AND (" + " OR ".join(
        f"(cve_producto = '{p[0]}' AND saldo_apertura BETWEEN {p[4]} AND {p[5]})" for p in PRODUCT_ROWS) + ")))"),
    ("nbm_sdos_objetivo_ck", "CHECK (fec_informacion = 20260131 OR saldo_mes = ROUND(saldo_apertura * (1 + CASE WHEN fec_informacion = 20260228 THEN CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 0.02 ELSE 0.03 END ELSE CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 0.01 ELSE 0.022 END END), 2))"),
), not_null=True, foreign_keys=(
    ("nbm_sdos_cuenta_fk", ACCOUNT_FK, REF_ACCOUNT.name, ACCOUNT_FK),))
MOVEMENT = Table("cfg.fact_txn_captacoloca_d", "U3", cols("""
num_cta INTEGER
num_cte INTEGER
cve_producto VARCHAR(40)
fec_txn DATE
cve_mes_txn INTEGER
saldo_txn NUMERIC(18,2)
cve_txn INTEGER
desc_txn VARCHAR(40)
fec_informacion INTEGER
dominio VARCHAR(20)
"""), checks=(
    ("nbm_txn_evento_sintetico_uq", "UNIQUE (num_cta, cve_producto, cve_mes_txn, cve_txn)"),
    ("nbm_txn_mes_ck", "CHECK (cve_mes_txn IN (202602,202603,202604,202605,202606))"),
    ("nbm_txn_fecha_ck", "CHECK (isfinite(fec_txn) AND EXTRACT(DAY FROM fec_txn) = 15 AND EXTRACT(YEAR FROM fec_txn)*100 + EXTRACT(MONTH FROM fec_txn) = cve_mes_txn)"),
    ("nbm_txn_corte_ck", f"CHECK (fec_informacion IN ({','.join(map(str,CUTS[1:]))}) AND fec_informacion / 100 = cve_mes_txn)"),
    ("nbm_txn_importe_ck", "CHECK (saldo_txn > 0 AND saldo_txn < 'Infinity'::NUMERIC)"),
    ("nbm_txn_dominio_origen_ck", "CHECK (dominio = CASE WHEN cve_producto IN ('CHEQUES','AHORRO') THEN 'DEPOSITS' WHEN cve_producto = 'C_PERSONAL' THEN 'LENDING' WHEN cve_producto = 'TDC' THEN 'TDC' END)"),
), not_null=True, foreign_keys=(
    ("nbm_txn_cuenta_fk", ACCOUNT_FK, REF_ACCOUNT.name, ACCOUNT_FK),
    ("nbm_txn_catalogo_fk", ("cve_producto", "cve_txn", "desc_txn"), REF_TXN.name,
     ("cve_producto", "cve_txn", "desc_txn")),))
ORIGINAL_TABLES = (CLIENT, PRODUCT, TXN, BALANCE, MOVEMENT)
INTEGRITY_ORDER = (CLIENT, PRODUCT, TXN, REF_TXN, REF_ACCOUNT, BALANCE, MOVEMENT)


def table_body(table, full=False):
    return ",\n    ".join(
        [f"{name} {definition}" + (" NOT NULL" if full and table.not_null and "NOT NULL" not in definition else "")
         for name, definition in table.columns] + list(table.base_constraints))


def table_spec(table):
    schema, name = table.name.split(".")
    fks = []
    for constraint, columns, target, ref_columns in table.foreign_keys:
        fks.append({"name": constraint,
                    "clause": f"FOREIGN KEY ({', '.join(columns)}) REFERENCES {target} ({', '.join(ref_columns)}) ON UPDATE RESTRICT ON DELETE RESTRICT",
                    "signature": {"kind": "f", "columns": list(columns), "target": target,
                                  "ref_columns": list(ref_columns), "update": "r", "delete": "r", "match": "s",
                                  "deferrable": False, "deferred": False, "validated": True}})
    return {"schema": schema, "table": name, "qualified": table.name, "auxiliary": table.source is None,
            "base_body": table_body(table), "full_body": table_body(table, True),
            "checks": [{"name": name, "clause": clause} for name, clause in table.checks], "fks": fks,
            "not_null": [name for name, _ in table.columns] if table.not_null else []}


# Only session-local helpers. References are empty temporary tables so PostgreSQL
# itself normalizes defaults/CHECK expressions. No permanent reference schema.
HELPERS = r"""
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
"""

GUARD = r"""
DO $integration$
DECLARE
    s JSONB; e JSONB; wanted JSONB; actual JSONB; required JSONB; allowed JSONB;
    actual_fk JSONB; allowed_fk JSONB; c JSONB; raw_columns JSONB; full_columns JSONB;
    relation OID; raw_ref OID; full_ref OID; ref_name TEXT; ref_body TEXT;
    needs_change BOOLEAN; has_rows BOOLEAN; i INTEGER;
    apply_integrity CONSTANT BOOLEAN := @APPLY@;
BEGIN
    FOR s IN SELECT value FROM jsonb_array_elements($spec$@SPEC@$spec$::JSONB) LOOP
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
"""


def migration(integrity=False):
    specs = [table_spec(t) for t in (INTEGRITY_ORDER if integrity else ORIGINAL_TABLES)]
    header = f"""-- Generated offline by scripts.new_bank_integration, adaptation {VERSION}.
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
            {'RAISE EXCEPTION \'Missing schema %, apply migration 001 first\', n;' if integrity else "EXECUTE format('CREATE SCHEMA %I', n);"}
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_namespace ns JOIN pg_roles r ON r.oid=ns.nspowner
                       WHERE ns.nspname=n AND r.rolname=current_user) THEN
            RAISE EXCEPTION 'Schema % must be owned by the current migration role', n;
        END IF;
    END LOOP;
END;
$schemas$;
"""
    body = GUARD.replace("@APPLY@", "TRUE" if integrity else "FALSE").replace(
        "@SPEC@", json.dumps(specs, ensure_ascii=False, indent=2))
    return header + HELPERS + body + "\nCOMMIT;\n"


def manifest():
    return {
        "manifest_version": "1.0.0", "model_id": MODEL_ID, "adaptation_version": VERSION,
        "status": "prepared_not_applied", "design": "docs/new-bank-model-integration-plan.md",
        "provenance": {"kind": "provided_synthetic_educational_sql", "official_bank_policy": False,
                       "source_release": None, "source_release_note": "No upstream version or delivery provenance beyond the provided files was specified.", "currency": None},
        "sources": [{"id": key, "path": path, "sha256": digest, "depends_on": deps}
                    for key, path, digest, deps in SOURCES],
        "tables": [{"name": t.name, "source_id": t.source, "columns": len(t.columns)} for t in ORIGINAL_TABLES],
        "auxiliary_tables": [{"name": t.name, "origin": "mvp_adaptation", "initial_rows": 0}
                             for t in (REF_TXN, REF_ACCOUNT)],
        "protected_tables": list(PROTECTED),
        "expected_loaded_volumes": {"dim.dim_cliente": 5000, "dim.dim_producto": 4, "dim.dim_txn": 9,
                                    "cfg.fact_sdos_captacoloca_m": 120000, "cfg.fact_txn_captacoloca_d": 225000,
                                    "distinct_accounts": 20000, "original_five_tables_total": 350013,
                                    "balances_per_cut": 20000, "movements_per_month": 45000,
                                    "auxiliary_transaction_rows": 9, "auxiliary_account_rows": 20000},
        "calendar": {"account_open_date": "2026-01-01", "cohort": 202601, "cuts": list(CUTS),
                     "transaction_months": [202602,202603,202604,202605,202606], "transaction_day": 15},
        "distributions": {"PF":4800, "PM":200, "PF_HOMBRE":2496, "PF_MUJER":2304,
                          "PM_NO_APLICA":200, "PREMIUM":250, "PREFERENTE":1000, "MASIVO":3750},
        "products": [{"code": p[0], "domain": p[1], "group": p[2], "account_min": p[3], "account_max": p[3]+4999,
                      "initial_balance_min": p[4], "initial_balance_max": p[5], "accounts":5000, "txn_types":p[6]}
                     for p in PRODUCT_ROWS],
        "transaction_catalog": [{"product":r[0], "code":r[1], "description":r[2], "domain":r[3], "group":r[4], "sign":r[5],
                                 "definition_source":"U1", "economic_sign_source":"U3"} for r in TRANSACTION_ROWS],
        "financial_rules": {"growth_february":{"CAPTACION":"0.02", "COLOCACION":"0.03"},
                            "growth_march_june":{"CAPTACION":"0.01", "COLOCACION":"0.022"},
                            "rounding":"decimal_round_half_up_2_places_per_account_per_month",
                            "growth_is_interest":False, "reconciliation_tolerance":"0.00"},
        "decisions": {"upstream_immutable":True, "separate_legacy_model_and_rag":True,
                      "preserve_raw_dominio":True, "preserve_saldo_apertura":True,
                      "dim_txn_has_pk_or_unique":False, "auxiliary_composite_catalog":True,
                      "anomalies":"report_without_silent_correction", "infer_currency":False},
        "future_generator": {"status":"implemented_in_separate_loader", "algorithm_version":"sha256-rounded-uniform-v1",
                             "implementation":"scripts/new_bank_model.py", "generator_version":"1.0.0",
                             "default_seed":202601, "contract":"docs/new-bank-model-governance.md#algoritmo-futuro",
                             "difference_from_upstream":"SHA-256 per account replaces session RANDOM(); no bit-for-bit equivalence. Deterministic rounded-uniform sampling keeps inclusive ranges and endpoint half-bin weighting; assignments, financial formulas and categorical counts remain as upstream."},
        "migrations": ["sql/integration/001_new_bank_schemas_tables.sql", "sql/integration/002_new_bank_integrity.sql"],
        "apply_order": ["backup_and_isolated_restore_verified", "001", "002", "future_separate_validated_load"],
        "known_anomalies": ["January dominio contains product group; subsequent months contain technical domain.",
                            "saldo_apertura means initial account balance in January and opening monthly balance thereafter.",
                            "Client 3552: fec_alta 2003-04-24 precedes fec_nac 2004-10-27 under U1 formulas."]}


def artifacts():
    return {
        "data/source/new_bank_model/manifest.json": json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n",
        "sql/integration/001_new_bank_schemas_tables.sql": migration(),
        "sql/integration/002_new_bank_integrity.sql": migration(True),
    }


def verify_sources(root=ROOT):
    for _, path, digest, _ in SOURCES:
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Upstream checksum mismatch: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("render", "check"))
    args = parser.parse_args(argv)
    verify_sources()
    for relative, content in artifacts().items():
        path = ROOT / relative
        if args.command == "render":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_bytes() != content.encode("utf-8"):
            raise ValueError(f"Artifact differs from reviewed renderer: {relative}")
        print(f"{args.command}: {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
