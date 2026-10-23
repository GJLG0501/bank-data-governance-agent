"""File/contract checks only: no PostgreSQL, Ollama, old fixtures or datasets."""

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import new_bank_integration as integration

ROOT = Path(__file__).resolve().parents[1]
PINNED = {
    "001_dimensiones_cliente_producto_txn.sql": "eee849f1bfbdc138291a81682a0ed836ac5dbd37b9c499c2a00a273377e7696a",
    "002_generar_cuentas_y_saldos_enero_2026.sql": "6dfc90c1e55b2092584499c05a74b55309aeda004d8ce135e0bc7e6f765ecd2b",
    "003_generar_transacciones_y_saldos_feb_jun_2026.sql": "d28d22b90e9882fa3780c23d1107df79ce72f9556ba8351d505eb108b0756fa3",
}
MIGRATIONS = [ROOT / p for p in integration.manifest()["migrations"]]


@pytest.fixture(autouse=True)
def no_connections_or_legacy_generation(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("This static suite must not connect or generate the legacy dataset")

    monkeypatch.setattr("psycopg.connect", denied)
    monkeypatch.setattr("socket.create_connection", denied)
    monkeypatch.setattr("scripts.bank_data.generate", denied)


def without_comments(text):
    # The received DDL has no comment delimiters inside literals.
    return re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def split_top_level(body):
    """Split a small DDL grammar without splitting NUMERIC, CHECK or IN lists."""
    result, start, level, quoted, i = [], 0, 0, False, 0
    while i < len(body):
        char = body[i]
        if char == "'":
            if quoted and i + 1 < len(body) and body[i + 1] == "'":
                i += 2
                continue
            quoted = not quoted
        elif not quoted:
            if char == "(":
                level += 1
            elif char == ")":
                level -= 1
            elif char == "," and level == 0:
                result.append(body[start:i].strip())
                start = i + 1
        i += 1
    assert not quoted and level == 0
    result.append(body[start:].strip())
    return result


def canonical_sql(expression):
    tokens = re.findall(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[^\s]", expression)
    return " ".join(t if t.startswith("'") else t.upper() for t in tokens)


def ddl_signature(body):
    columns, constraints = [], []
    for item in split_top_level(body):
        if re.match(r"(?:CHECK|PRIMARY KEY|UNIQUE)\b", item, re.I):
            constraints.append(canonical_sql(item))
            continue
        name, definition = item.split(None, 1)
        match = re.match(
            r"(INTEGER|INT4|DATE|VARCHAR\s*\(\s*\d+\s*\)|NUMERIC\s*\(\s*\d+\s*,\s*\d+\s*\)|BOOLEAN)", definition, re.I)
        assert match, item
        kind = re.sub(r"\s+", "", match[1].upper()).replace("INT4", "INTEGER")
        pk = bool(re.search(r"\bPRIMARY\s+KEY\b", definition, re.I))
        default = re.search(r"\bDEFAULT\s+(TRUE|FALSE)\b", definition, re.I)
        columns.append((name, kind, pk or bool(re.search(r"\bNOT\s+NULL\b", definition, re.I)),
                        default[1].upper() if default else None))
        if pk:
            constraints.append(canonical_sql(f"PRIMARY KEY ({name})"))
    pk_columns = set()
    for item in constraints:
        if item.startswith("PRIMARY KEY"):
            pk_columns.update(t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", item)[2:])
    columns = [(n, t, nn or n in pk_columns, d) for n, t, nn, d in columns]
    return columns, sorted(constraints)


def original_ddls():
    result = {}
    for name in PINNED:
        text = without_comments((ROOT / "sql/upstream" / name).read_text(encoding="utf-8"))
        for match in re.finditer(r"CREATE TABLE\s+([a-z_]+\.[a-z_]+)\s*\((.*?)\n\);", text, re.S | re.I):
            result[match[1]] = ddl_signature(match[2])
    return result


def sql_specs(path):
    return json.loads(path.read_text(encoding="utf-8").split("$spec$", 2)[1])


@pytest.mark.parametrize("name,digest", PINNED.items())
def test_upstream_bytes_preserved(name, digest):
    assert hashlib.sha256((ROOT / "sql/upstream" / name).read_bytes()).hexdigest() == digest


def test_checksum_change_is_rejected(monkeypatch):
    original_read = Path.read_bytes
    altered = ROOT / "sql/upstream" / next(iter(PINNED))

    def simulated_edit(path):
        raw = original_read(path)
        return raw + b"\n-- simulated edit\n" if path == altered else raw

    monkeypatch.setattr(Path, "read_bytes", simulated_edit)
    with pytest.raises(ValueError, match="checksum mismatch"):
        integration.verify_sources()


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_all_five_base_schemas_match_original_ddl(path):
    upstream = original_ddls()
    assert len(upstream) == 5
    assert sum(len(sig[0]) for sig in upstream.values()) == 42
    specs = {s["qualified"]: s for s in sql_specs(path)}
    for name, expected in upstream.items():
        assert ddl_signature(specs[name]["base_body"]) == expected, name


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_no_destructive_operations_or_data_loads(path):
    sql = without_comments(path.read_text(encoding="utf-8"))
    assert not re.search(r"\b(?:DROP|TRUNCATE|CASCADE|GRANT|REVOKE)\b", sql, re.I)
    assert not re.search(r"\b(?:DELETE\s+FROM|INSERT\s+INTO|MERGE\s+INTO|UPDATE\s+\w+(?:\.\w+)?\s+SET|COPY\s+.+?\s+FROM)\b", sql, re.I | re.S)
    assert "CREATE VIEW" not in sql.upper()
    assert "CREATE ROLE" not in sql.upper()


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_write_scope_excludes_all_protected_schemas_and_tables(path):
    sql = path.read_text(encoding="utf-8")
    for protected in integration.PROTECTED:
        assert protected not in sql
    assert not re.search(r"\b(?:public|bank_knowledge)\s*\.", sql, re.I)
    assert "ARRAY['dim','cfg']" in sql
    specs = sql_specs(path)
    expected = {t.name for t in (integration.INTEGRITY_ORDER if path.name.startswith("002") else integration.ORIGINAL_TABLES)}
    assert {s["qualified"] for s in specs} == expected
    assert all(s["schema"] in {"dim", "cfg"} for s in specs)
    assert all(fk["signature"]["target"] in expected or fk["signature"]["target"] in {t.name for t in integration.INTEGRITY_ORDER}
               for s in specs for fk in s["fks"])
    assert "format('CREATE TABLE %I.%I (%s)', s->>'schema', s->>'table'" in sql
    assert "format('ALTER TABLE %I.%I" in sql
    assert "CREATE OR REPLACE FUNCTION pg_temp." in sql


def test_dim_txn_keeps_exact_definition_in_both_stages():
    for path in MIGRATIONS:
        spec = next(s for s in sql_specs(path) if s["qualified"] == "dim.dim_txn")
        assert spec["base_body"] == spec["full_body"]
        assert spec["checks"] == spec["fks"] == spec["not_null"] == []
        assert not re.search(r"\b(?:PRIMARY KEY|UNIQUE)\b", spec["base_body"], re.I)


def test_original_dimension_nullable_fields_and_default_are_unchanged():
    specs = {s["qualified"]: s for s in sql_specs(MIGRATIONS[1])}
    for name in ("dim.dim_cliente", "dim.dim_producto"):
        s = specs[name]
        assert s["base_body"] == s["full_body"]
        assert not s["not_null"] and not s["checks"] and not s["fks"]
    assert "activo BOOLEAN DEFAULT TRUE" in specs["dim.dim_producto"]["base_body"]


def test_integrity_keys_are_composite_and_auxiliary_tables_are_empty():
    specs = {s["qualified"]: s for s in sql_specs(MIGRATIONS[1])}
    ref = specs["cfg.ref_txn_modelo"]
    assert "PRIMARY KEY (cve_producto, cve_txn)" in ref["base_body"]
    assert "UNIQUE (cve_producto, cve_txn, desc_txn)" in ref["base_body"]
    assert len(specs["cfg.fact_sdos_captacoloca_m"]["not_null"]) == 9
    assert len(specs["cfg.fact_txn_captacoloca_d"]["not_null"]) == 10
    assert specs["cfg.fact_sdos_captacoloca_m"]["fks"][0]["signature"]["columns"] == ["num_cta", "cve_producto", "num_cte"]
    assert specs["cfg.fact_txn_captacoloca_d"]["fks"][1]["signature"]["columns"] == ["cve_producto", "cve_txn", "desc_txn"]
    assert all(f["signature"]["update"] == f["signature"]["delete"] == "r"
               for s in specs.values() for f in s["fks"])
    assert all(item["initial_rows"] == 0 for item in integration.manifest()["auxiliary_tables"])


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_migrations_have_atomicity_drift_and_adoption_guards(path):
    sql = without_comments(path.read_text(encoding="utf-8"))
    assert sql.strip().startswith("BEGIN;") and sql.strip().endswith("COMMIT;")
    assert sql.count("\nCOMMIT;") == 1
    assert "pg_advisory_xact_lock(7262026, 1)" in sql
    assert "SET LOCAL search_path = pg_catalog;" in sql
    assert "pg_get_constraintdef(k.oid, FALSE)" in sql
    assert "c <> raw_columns AND c <> full_columns" in sql
    assert "required <@ actual AND actual <@ allowed AND actual_fk <@ allowed_fk" in sql
    assert "pg_policy WHERE polrelid=relation" in sql
    assert "NOT cl.relrowsecurity" in sql and "NOT tgisinternal" in sql
    assert "Incompatible columns" in sql and "Postcondition failed" in sql
    assert "Refusing to adopt/strengthen nonempty table" in sql
    assert "CREATE TABLE IF NOT EXISTS" not in sql
    assert "convalidated" in sql and "attidentity" in sql and "attgenerated" in sql


def test_manifest_is_consistent_with_original_catalog_and_volumes():
    m = json.loads((ROOT / "data/source/new_bank_model/manifest.json").read_text(encoding="utf-8"))
    assert m == integration.manifest()
    assert len(m["sources"]) == 3
    assert {Path(s["path"]).name: s["sha256"] for s in m["sources"]} == PINNED
    assert m["sources"][1]["depends_on"] == ["U1", "cfg schema"]
    assert m["sources"][2]["depends_on"] == ["U2", "January close"]
    assert {t["name"] for t in m["tables"]} == set(original_ddls())
    assert sum(t["columns"] for t in m["tables"]) == 42
    assert m["provenance"]["currency"] is None and not m["provenance"]["official_bank_policy"]
    products = m["products"]
    accounts = sum(p["accounts"] for p in products)
    monthly_txn = sum(p["accounts"] * p["txn_types"] for p in products)
    counts = m["expected_loaded_volumes"]
    assert accounts == counts["distinct_accounts"] == 20000
    assert accounts * len(m["calendar"]["cuts"]) == counts["cfg.fact_sdos_captacoloca_m"] == 120000
    assert monthly_txn * len(m["calendar"]["transaction_months"]) == counts["cfg.fact_txn_captacoloca_d"] == 225000
    assert sum(counts[t["name"]] for t in m["tables"]) == counts["original_five_tables_total"] == 350013
    assert sum(m["distributions"][k] for k in ("PF", "PM")) == 5000
    assert sum(m["distributions"][k] for k in ("PREMIUM", "PREFERENTE", "MASIVO")) == 5000
    source = (ROOT / "sql/upstream/001_dimensiones_cliente_producto_txn.sql").read_text(encoding="utf-8")
    values = source.split("INSERT INTO dim.dim_txn", 1)[1].split("VALUES", 1)[1].split(";", 1)[0]
    received = [ast.literal_eval("(" + row + ")") for row in re.findall(r"\(([^()]*)\)", values)]
    assert [(r["product"], r["domain"], r["group"], r["code"], r["description"]) for r in m["transaction_catalog"]] == received
    assert len({(r["product"], r["code"]) for r in m["transaction_catalog"]}) == 9


def test_raw_domain_and_opening_balance_are_preserved_without_currency():
    m = integration.manifest()
    specs = {s["qualified"]: s for s in sql_specs(MIGRATIONS[1])}
    checks = {c["name"]: c["clause"] for c in specs["cfg.fact_sdos_captacoloca_m"]["checks"]}
    domain = checks["nbm_sdos_dominio_origen_ck"]
    assert all(v in domain for v in ("20260131", "CAPTACION", "COLOCACION", "DEPOSITS", "LENDING", "TDC"))
    assert "saldo_apertura NUMERIC(18,2) NOT NULL" in specs["cfg.fact_sdos_captacoloca_m"]["full_body"]
    assert m["decisions"]["preserve_raw_dominio"] and m["decisions"]["preserve_saldo_apertura"]
    assert not m["decisions"]["infer_currency"]
    assert not re.search(r"fec_alta\s*>=\s*fec_nac", integration.migration(True))


def test_generator_contract_is_implemented_outside_offline_renderer():
    m = integration.manifest()
    assert m["future_generator"]["status"] == "implemented_in_separate_loader"
    assert m["future_generator"]["implementation"] == "scripts/new_bank_model.py"
    assert m["future_generator"]["algorithm_version"] == "sha256-rounded-uniform-v1"
    assert m["future_generator"]["default_seed"] == 202601
    assert "RANDOM()" in m["future_generator"]["difference_from_upstream"]
    assert not hasattr(integration, "generate")
    tree = ast.parse(Path(integration.__file__).read_text(encoding="utf-8"))
    imports = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imports |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"argparse", "dataclasses", "hashlib", "json", "pathlib"}


def test_artifacts_are_reproducible_without_access_to_services():
    assert integration.artifacts() == integration.artifacts()
    for name, expected in integration.artifacts().items():
        assert (ROOT / name).read_bytes() == expected.encode("utf-8")
    assert integration.main(["check"]) == 0


def test_cli_has_no_apply_or_load_command():
    result = subprocess.run([sys.executable, "-m", "scripts.new_bank_integration", "apply"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


@pytest.mark.parametrize("filename", ("preflight.sql", "legacy_snapshot.sql"))
def test_inspection_sql_is_read_only_and_does_not_create_reference_objects(filename):
    sql = without_comments((ROOT / "sql/integration/checks" / filename).read_text(encoding="utf-8"))
    assert "READ ONLY" in sql
    assert not re.search(r"\b(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|DO|CALL|COPY)\b", sql, re.I)
    assert "COMMIT;" in sql
    if filename == "legacy_snapshot.sql":
        assert "to_jsonb(t)" in sql and "sha256(convert_to" in sql
        assert all(name in sql for name in ('public."CUSTOMER"', 'public."TRANSACTION"', 'public."LOAN"',
                                           "bank_knowledge.corpora", "bank_knowledge.documents"))
        assert "public.vector_dims(embedding)" in sql


def test_runbook_uses_explicit_isolated_destination_and_nonsecret_credentials():
    doc = (ROOT / "docs/new-bank-model-backup-recovery.md").read_text(encoding="utf-8")
    assert "--format=custom --file=" in doc
    assert "--roles-only --no-role-passwords" in doc
    assert "--dbname=\"$1\"" in doc
    assert "--exit-on-error --single-transaction" in doc
    assert "'nbm_restore_'" in doc
    assert "$RestoreDb" in doc and "$ActiveDb" in doc
    assert "--clean" not in doc and "--create" not in doc
    assert "POSTGRES_PASSWORD" not in doc and "PGPASSWORD=" not in doc
    assert "docker compose down" not in doc
    assert "$ExpectedProtected -cne $RestoredProtected" in doc
    assert "bank-postgres:$RestoreArchive" in doc


def test_document_links_and_prepared_file_inventory():
    for name in ("new-bank-model-governance.md", "new-bank-model-backup-recovery.md"):
        path = ROOT / "docs" / name
        text = path.read_text(encoding="utf-8")
        assert "no aplicado" in text or "no ejecutado" in text
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if not link.startswith("https://"):
                assert (path.parent / link.split("#", 1)[0]).resolve().is_file(), link
