"""Deterministic Decimal dataset and atomic loader, ONLY for a recorded isolated run.

No .env, TCP connection, upstream execution, reset, or active-database write path.
The offline design manifest is historical; each dataset has a separate identity.
"""

import argparse
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import time

from scripts import new_bank_integration as design
from scripts import new_bank_runtime_validation as runtime

ALGORITHM = "sha256-rounded-uniform-v1"
GENERATOR_VERSION = "1.0.0"
SEED = 202601
CENT = Decimal("0.01")
TABLES = design.INTEGRITY_ORDER
BY_NAME = {t.name: t for t in TABLES}
KEYS = {
    design.CLIENT.name: ("num_cte",),
    design.PRODUCT.name: ("cve_producto",),
    design.TXN.name: ("cve_producto", "cve_txn"),
    design.REF_TXN.name: ("cve_producto", "cve_txn"),
    design.REF_ACCOUNT.name: ("num_cta", "cve_producto"),
    design.BALANCE.name: ("num_cta", "cve_producto", "fec_informacion"),
    design.MOVEMENT.name: ("num_cta", "cve_producto", "cve_mes_txn", "cve_txn"),
}
EXPECTED = dict(zip((t.name for t in TABLES), (5000, 4, 9, 9, 20000, 120000, 225000)))
DESCRIPTIONS = {"CHEQUES": "Cuenta de Cheques", "AHORRO": "Cuenta de Ahorro",
                "C_PERSONAL": "Crédito Personal", "TDC": "Tarjeta de Crédito"}
CONTROL = "bank_model_control.datasets"
CONTROL_BODY = "model_id TEXT PRIMARY KEY, manifest JSONB NOT NULL"


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def initial_balance(product, account, seed):
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    p = next(p for p in design.PRODUCT_ROWS if p[0] == product)
    if type(account) is not int or not p[3] <= account <= p[3] + 4999:
        raise ValueError("account outside product range")
    message = compact(dict(algorithm=ALGORITHM, model_id=design.MODEL_ID,
                           seed=seed, product=product, account=account))
    h, denominator = int(sha(message), 16), 2**256
    lo, hi = int(Decimal(p[4]) * 100), int(Decimal(p[5]) * 100)
    cents = lo + (2 * (hi-lo) * h + denominator) // (2 * denominator)
    return Decimal(f"{cents//100}.{cents%100:02d}")


def month_amounts(product, month, opening):
    """U3 positive amounts and closing target. No binary monetary arithmetic."""
    deposits = product in ("AHORRO", "CHEQUES")
    rate = Decimal(("0.02" if deposits else "0.03") if month == 2
                   else ("0.01" if deposits else "0.022"))
    closing = money(opening * (1 + rate))
    increment = closing - opening
    if product == "TDC":
        purchase = money(opening * Decimal("0.02"))
        amounts = {400: purchase, 450: purchase, 300: purchase * 2 - increment}
    else:
        payment = money(opening * Decimal("0.05"))
        amounts = {100: payment + increment, 200: payment} if deposits else {450: payment + increment, 300: payment}
    return closing, amounts


def key_positions(table):
    names = [n for n, _ in BY_NAME[table].columns]
    return tuple(names.index(n) for n in KEYS[table])


def text_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite() or value != money(value):
            raise ValueError("non-finite or sub-cent monetary value")
        return format(value, ".2f")
    if isinstance(value, float):
        raise ValueError("float is not a dataset type")
    return str(value)


def canonical_row(row):
    # PostgreSQL jsonb_build_array(column::text,...) has this same representation.
    return json.dumps([text_value(v) for v in row], ensure_ascii=False, allow_nan=False)


def table_identity(name, rows):
    indices = key_positions(name)
    ordered = sorted(rows, key=lambda r: tuple(r[i] for i in indices))
    if len({tuple(r[i] for i in indices) for r in rows}) != len(rows):
        raise ValueError("duplicate logical key: " + name)
    return {"rows": len(rows), "sha256": sha("\n".join(canonical_row(r) for r in ordered))}


def generate(seed=SEED):
    """Full fixed universe. Return immutable rows; no I/O other than source checking."""
    design.verify_sources()
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rows = {t.name: [] for t in TABLES}
    with localcontext() as ctx:
        ctx.prec = 38
        for n in range(1, 5001):
            pf = n <= 4800
            birth = date(1945 if pf else 1960, 1, 1) + timedelta(days=n * (37 if pf else 53) % (21915 if pf else 23742))
            rows[design.CLIENT.name].append((n, date(2000, 1, 1) + timedelta(days=n*97 % 7305), birth,
                "PF" if pf else "PM", ("HOMBRE" if n <= 2496 else "MUJER") if pf else "NO APLICA",
                "PREMIUM" if n % 100 < 5 else "PREFERENTE" if n % 100 < 25 else "MASIVO", *(None,)*6))
        for product, domain, group, base, low, high, types in design.PRODUCT_ROWS:
            rows[design.PRODUCT.name].append((product, domain, group, product, DESCRIPTIONS[product], True))
            catalog = [t for t in design.TRANSACTION_ROWS if t[0] == product]
            for _, code, description, _, _, sign in catalog:
                rows[design.TXN.name].append((product, domain, group, code, description))
                rows[design.REF_TXN.name].append((product, code, description, domain, group, sign, design.VERSION))
            for n in range(1, 5001):
                account = base + n - 1
                rows[design.REF_ACCOUNT.name].append((account, n, product, date(2026, 1, 1), 202601))
                previous = initial_balance(product, account, seed)
                for month, cut in enumerate(design.CUTS, 1):
                    opening = previous
                    if month > 1:
                        previous, amounts = month_amounts(product, month, opening)
                        for _, code, description, _, _, sign in catalog:
                            rows[design.MOVEMENT.name].append((account, n, product, date(2026, month, 15),
                                202600 + month, amounts[code], code, description, cut, domain))
                        if opening + sum(amounts[t[1]] * t[5] for t in catalog) != previous:
                            raise ValueError("exact financial reconciliation failed")
                    rows[design.BALANCE.name].append((account, n, product, date(2026, 1, 1), 202601,
                                                      opening, previous, cut, group if month == 1 else domain))
    return {name: tuple(values) for name, values in rows.items()}


def dataset_manifest(rows, seed):
    tables = {t.name: table_identity(t.name, rows[t.name]) for t in TABLES}
    if {n: v["rows"] for n, v in tables.items()} != EXPECTED:
        raise ValueError("incomplete dataset")
    identity = {"manifest_version": "1.0.0", "model_id": design.MODEL_ID,
                "adaptation_version": design.VERSION, "generator_version": GENERATOR_VERSION,
                "algorithm": ALGORITHM, "seed": seed, "currency": None,
                "period": [202601, 202606], "rounding": "Decimal.ROUND_HALF_UP/2",
                "canonical_format": "json-array-of-text-or-null/UTF8/LF-between-rows/no-final-LF/v1",
                "source_sha256": {p: h for _, p, h, _ in design.SOURCES},
                "migrations_sha256": {p: hashlib.sha256((design.ROOT/p).read_bytes()).hexdigest()
                                      for p in design.manifest()["migrations"]},
                "tables": tables, "sort_keys": KEYS}
    # JSON roundtrip converts tuples to arrays before comparison with server JSON.
    identity = json.loads(compact(identity))
    return dict(identity, dataset_sha256=sha(compact(identity)))


def prepare(seed=SEED):
    start = time.perf_counter()
    rows = generate(seed)
    generated = time.perf_counter()
    manifest = dataset_manifest(rows, seed)
    return rows, manifest, {"generation_seconds": generated-start,
                            "canonical_hash_seconds": time.perf_counter()-generated}


def counts_sql():
    return "SELECT jsonb_build_object(" + ",".join(
        design.literal(t.name) + f",(SELECT COUNT(*) FROM {t.name})" for t in TABLES) + ")"


def hashes_sql():
    parts = []
    for t in TABLES:
        columns = ",".join(n + "::text" for n, _ in t.columns)
        order = ",".join(n + (' COLLATE "C"' if n == "cve_producto" else "") for n in KEYS[t.name])
        parts.extend([design.literal(t.name), f"(SELECT jsonb_build_object('rows',COUNT(*),'sha256',"
            f"encode(sha256(convert_to(COALESCE(string_agg(jsonb_build_array({columns})::text,E'\\n' ORDER BY {order}),''),'UTF8')),'hex')) FROM {t.name})"])
    return "SELECT jsonb_build_object(" + ",".join(parts) + ")"


def structure_sql():
    return (design.ROOT / "sql/integration/checks/model_structure.sql").read_text(encoding="utf-8").strip().rstrip(";")


def quality_sql():
    return (design.ROOT / "sql/integration/checks/new_bank_dataset.sql").read_text(encoding="utf-8").strip().rstrip(";")


def assertion(expression, message):
    return f"IF ({expression}) IS DISTINCT FROM TRUE THEN RAISE EXCEPTION '{message}'; END IF;\n"


def environment(state, database=None):
    """Every DB entry point checks isolation. No connection default or .env lookup."""
    runtime.isolated_guard(state)
    users = runtime.docker("ps", "-a", "--filter", "volume="+state["volume"], "--format", "{{.ID}}").stdout.split()
    if users != [state["container_id"][:12]]:
        raise RuntimeError("Isolated volume has unexpected container users")
    db = database or state["database"]
    case = db in state.get("case_databases", []) and db.startswith("nbm_case_" + state["run_id"][:16] + "_")
    if db == runtime.ACTIVE_DB or (db != state["database"] and not case):
        raise RuntimeError("Unregistered isolated destination")
    if state.get("status") != "runtime_verified" or "structure_002" not in state:
        raise RuntimeError("Previously verified migrations 001/002 required")
    design.verify_sources()
    for evidence in state["migrations"]:
        if hashlib.sha256((design.ROOT / evidence["file"]).read_bytes()).hexdigest() != evidence["sha256"]:
            raise RuntimeError("Validated migration bytes changed")
    return db


def read(state, sql, database=None):
    db = environment(state, database)
    result = runtime.psql(state["container"], db,
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL DateStyle='ISO, YMD'; "
        "SET LOCAL search_path=pg_catalog; " + sql + "; COMMIT;", state=state)
    return json.loads(result.stdout)


def inspect_target(state, database=None):
    db = environment(state, database)
    result = read(state, "SELECT jsonb_build_object('database',current_database(),'role',current_user,"
        "'postgres',current_setting('server_version'),'vector',(SELECT extversion FROM pg_extension WHERE extname='vector'),"
        "'counts',(" + counts_sql() + "),'structure',(" + structure_sql() + "))", db)
    if result["database"] != db or not result["postgres"].startswith("17.") or result["role"] != runtime.ROLE:
        raise RuntimeError("SQL destination identity mismatch")
    if result["structure"] != state["structure_002"]:
        raise RuntimeError("Migrations 001/002 structural signature differs")
    return {k: v for k, v in result.items() if k != "structure"}


def schema_guard(state, database):
    expected = design.literal(compact(state["structure_002"])) + "::jsonb"
    return assertion(f"current_database()={design.literal(database)} AND current_user={design.literal(runtime.ROLE)} "
        "AND current_setting('server_version_num')::int/10000=17", "SQL destination mismatch") + assertion(
        f"({structure_sql()})={expected}", "Migrations 001/002 structure drift") + """
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       WHERE n.nspname IN ('dim','cfg') AND c.relkind='r' AND
        (c.relrowsecurity OR c.relforcerowsecurity OR c.relispartition OR c.relpersistence<>'p'
         OR EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=c.oid AND NOT tgisinternal)
         OR EXISTS(SELECT 1 FROM pg_policy WHERE polrelid=c.oid)
         OR EXISTS(SELECT 1 FROM pg_rewrite WHERE ev_class=c.oid)
         OR EXISTS(SELECT 1 FROM pg_inherits WHERE inhrelid=c.oid OR inhparent=c.oid)
         OR EXISTS(SELECT 1 FROM pg_index WHERE indrelid=c.oid AND (NOT indisvalid OR NOT indisready))))
       OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN ('dim','cfg') AND pg_get_userbyid(nspowner)<>current_user)
    THEN RAISE EXCEPTION 'Unsafe table or schema attributes'; END IF;
    """


def control_guard():
    # Check the complete small control definition, never only IF NOT EXISTS.
    return """
    IF NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='bank_model_control'
       AND pg_get_userbyid(nspowner)=current_user) THEN RAISE EXCEPTION 'Control schema owner mismatch'; END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_class WHERE oid='bank_model_control.datasets'::regclass
       AND relkind='r' AND relpersistence='p' AND NOT relrowsecurity AND NOT relforcerowsecurity
       AND NOT relispartition AND pg_get_userbyid(relowner)=current_user)
       OR EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='bank_model_control.datasets'::regclass AND NOT tgisinternal)
       OR EXISTS(SELECT 1 FROM pg_policy WHERE polrelid='bank_model_control.datasets'::regclass)
       OR EXISTS(SELECT 1 FROM pg_rewrite WHERE ev_class='bank_model_control.datasets'::regclass)
       OR EXISTS(SELECT 1 FROM pg_inherits WHERE inhrelid='bank_model_control.datasets'::regclass OR inhparent='bank_model_control.datasets'::regclass)
    THEN RAISE EXCEPTION 'Unsafe control table'; END IF;
    """ + assertion("""(SELECT jsonb_agg(jsonb_build_array(attname,format_type(atttypid,atttypmod),attnotnull,attidentity,attgenerated,attisdropped)
       ORDER BY attnum) FROM pg_attribute WHERE attrelid='bank_model_control.datasets'::regclass AND attnum>0)
       = '[ ["model_id","text",true,"","",false], ["manifest","jsonb",true,"","",false] ]'::jsonb
       AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid
            WHERE a.attrelid='bank_model_control.datasets'::regclass AND a.attnum>0
            AND (a.attndims<>0 OR a.attcollation<>t.typcollation))
       AND NOT EXISTS(SELECT 1 FROM pg_attrdef WHERE adrelid='bank_model_control.datasets'::regclass)
       AND (SELECT COUNT(*)=1 AND bool_and(contype='p' AND conkey=ARRAY[1]::smallint[] AND convalidated AND NOT condeferrable)
            FROM pg_constraint WHERE conrelid='bank_model_control.datasets'::regclass)
       AND (SELECT COUNT(*)=1 AND bool_and(indisvalid AND indisready AND indisunique AND indisprimary)
            FROM pg_index WHERE indrelid='bank_model_control.datasets'::regclass)""", "Incompatible control definition")


def content_guard(manifest):
    return assertion(f"({hashes_sql()})={design.literal(compact(manifest['tables']))}::jsonb",
                     "Content hash/count mismatch (partial or altered dataset)") + (
        "SELECT report INTO q FROM (" + quality_sql() + ") quality(report);\n"
        "IF EXISTS(SELECT 1 FROM jsonb_each_text(q->'violations') WHERE value::bigint<>0) "
        "THEN RAISE EXCEPTION 'Dataset quality/financial failure: %',q->'violations'; END IF;\n")


def copy_text(table, rows, target=None):
    def escaped(value):
        value = text_value(value)
        return r"\N" if value is None else value.replace("\\", "\\\\").replace("\t", r"\t").replace("\n", r"\n").replace("\r", r"\r")
    return f"COPY {target or table.name} ({','.join(n for n,_ in table.columns)}) FROM STDIN;\n" + "".join(
        "\t".join(escaped(v) for v in row) + "\n" for row in rows) + "\\.\n"


def schema_comment_manifest(manifest):
    """Operational storage for the explicitly authorized dim/cfg publication only."""
    return compact({"format": "bank-model-dataset-comment-v1", "manifest": manifest})


def comment_identity_guard(manifest):
    expected = design.literal(schema_comment_manifest(manifest)) + "::jsonb"
    return assertion("obj_description('cfg'::regnamespace,'pg_namespace')::jsonb=" + expected,
                     "Dataset identity mismatch (cfg manifest)")


def load_script(state, rows, manifest, database, *, _fail_after=None, control_mode="isolated_table"):
    """Render only; transport guards authorize execution. Default remains isolated.

    Private fault injection and cfg metadata mode have no route in the isolated CLI.
    The publication adapter separately pins and authorizes the original destination.
    """
    if control_mode not in ("isolated_table", "cfg_comment"):
        raise ValueError("Unknown manifest storage mode")
    empty = " AND ".join(f"NOT EXISTS(SELECT 1 FROM {t.name})" for t in TABLES)
    expected = design.literal(compact(manifest)) + "::jsonb"
    script = "BEGIN ISOLATION LEVEL READ COMMITTED; SET LOCAL search_path=pg_catalog; SET LOCAL DateStyle='ISO, YMD';\n"
    script += "SET LOCAL lock_timeout='60s'; SET LOCAL statement_timeout='120s'; SELECT pg_advisory_xact_lock(7262026,1);\n"
    script += "LOCK TABLE " + ",".join(t.name for t in TABLES) + " IN SHARE ROW EXCLUSIVE MODE;\n"
    if control_mode == "isolated_table":
        script += "DO $pre$ BEGIN " + schema_guard(state, database) + """
    IF to_regnamespace('bank_model_control') IS NULL THEN
    """ + assertion(empty, "Partial dataset without control manifest") + """
        CREATE SCHEMA bank_model_control;
        CREATE TABLE bank_model_control.datasets (model_id TEXT PRIMARY KEY, manifest JSONB NOT NULL);
    ELSIF to_regclass('bank_model_control.datasets') IS NULL THEN
        RAISE EXCEPTION 'Preexisting incomplete control schema';
    END IF;
    """ + control_guard() + " END $pre$;\n"
        script += "LOCK TABLE bank_model_control.datasets IN SHARE ROW EXCLUSIVE MODE;\n"
        script += "DO $identity$ BEGIN IF EXISTS(SELECT 1 FROM bank_model_control.datasets) THEN " + assertion(
            f"(SELECT COUNT(*)=1 AND bool_and(model_id='new_bank_2026' AND manifest={expected}) FROM {CONTROL})",
            "Dataset identity mismatch (seed/version/manifest)") + " ELSE " + assertion(empty, "Partial dataset") + " END IF; END $identity$;\n"
        script += "SELECT NOT EXISTS(SELECT 1 FROM bank_model_control.datasets) AS do_load \\gset\n"
    else:
        script += "DO $pre$ BEGIN " + schema_guard(state, database)
        script += "IF obj_description('cfg'::regnamespace,'pg_namespace') IS NULL THEN "
        script += assertion(empty, "Partial dataset without cfg manifest")
        script += "ELSE " + comment_identity_guard(manifest) + " END IF; END $pre$;\n"
        script += "SELECT obj_description('cfg'::regnamespace,'pg_namespace') IS NULL AS do_load \\gset\n"
    # psql still parses backslash commands inside skipped SQL: raw COPY data
    # (notably NULL \\N) cannot live in an inactive \\if branch. Stage unconditionally
    # in session-local tables; only the persistent INSERTs are conditional.
    for index, table in enumerate(TABLES):
        target = f"pg_temp.nbm_stage_{index}"
        script += f"CREATE TEMP TABLE nbm_stage_{index} (LIKE {table.name});\n"
        script += copy_text(table, rows[table.name], target)
    script += "\\if :do_load\n"
    for index, table in enumerate(TABLES):
        columns = ','.join(n for n,_ in table.columns)
        script += f"INSERT INTO {table.name} ({columns}) SELECT {columns} FROM pg_temp.nbm_stage_{index};\n"
        if _fail_after == table.name:
            script += "DO $fault$ BEGIN RAISE EXCEPTION 'Injected rollback test'; END $fault$;\n"
    script += "\\endif\nDO $content$ DECLARE q jsonb; BEGIN " + content_guard(manifest) + " END $content$;\n"
    if control_mode == "isolated_table":
        script += f"INSERT INTO {CONTROL} SELECT 'new_bank_2026',{expected} WHERE :'do_load'::boolean;\n"
    else:
        script += "\\if :do_load\nCOMMENT ON SCHEMA cfg IS " + design.literal(schema_comment_manifest(manifest)) + ";\n\\endif\n"
    script += "SELECT jsonb_build_object('result',CASE WHEN :'do_load'::boolean THEN 'cargado' ELSE 'sin cambios' END,'dataset_sha256',"
    script += design.literal(manifest["dataset_sha256"]) + ");\nCOMMIT;\n"
    return script


def load(state, rows, manifest, *, database=None, _fail_after=None):
    db = environment(state, database)
    inspect_target(state, db)
    if manifest != dataset_manifest(rows, manifest["seed"]):
        raise ValueError("Input rows/manifest mismatch")
    start = time.perf_counter()
    script = load_script(state, rows, manifest, db, _fail_after=_fail_after)
    serialized = time.perf_counter()
    result = runtime.psql(state["container"], db, script, readonly=False, state=state, check=False)
    if result.returncode:
        # Preserve the actual diagnostic instead of the tail of a large SQL context.
        messages = [line for line in result.stderr.splitlines() if line.startswith(("ERROR:", "DETAIL:", "HINT:"))]
        raise RuntimeError("Isolated load rolled back: " + ("\n".join(messages) or result.stderr[:1200])[:2500])
    output = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    output["timings"] = {"copy_serialization_seconds": serialized-start,
                         "transaction_including_validation_seconds": time.perf_counter()-serialized}
    return output


def verify(state, manifest, database=None):
    db = environment(state, database)
    inspect_target(state, db)
    start = time.perf_counter()
    sql = "DO $verify$ DECLARE q jsonb; BEGIN " + schema_guard(state, db) + control_guard() + assertion(
        f"(SELECT COUNT(*)=1 AND bool_and(model_id='new_bank_2026' AND manifest={design.literal(compact(manifest))}::jsonb) FROM {CONTROL})",
        "Dataset identity mismatch") + content_guard(manifest) + " END $verify$;\n"
    sql += "SELECT jsonb_build_object('manifest',(SELECT manifest FROM bank_model_control.datasets),'quality',(" + quality_sql() + "))"
    result = read(state, sql, db)
    result["verification_seconds"] = time.perf_counter()-start
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "prepare", "load", "verify", "manifest"))
    parser.add_argument("--state", help="explicit ignored state.json of the previous isolated validation")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    if args.command in ("inspect", "load", "verify") and not args.state:
        parser.error("--state is mandatory for every database operation")
    state = runtime.load_state(args.state)[1] if args.state else None
    if args.command == "inspect":
        result = inspect_target(state)
    else:
        rows, manifest, timings = prepare(args.seed)
        result = {"manifest": manifest, "timings": timings}
        if args.command == "load":
            result["load"] = load(state, rows, manifest)
        elif args.command == "verify":
            result["verification"] = verify(state, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
