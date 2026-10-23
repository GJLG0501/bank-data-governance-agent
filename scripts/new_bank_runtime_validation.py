"""Explicit Docker backup/restore harness. All writes are guarded to an isolated container.

No cleanup, production migration, data generator, passwords or cloud operations.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from scripts import new_bank_integration as design

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local-validation"
ACTIVE = "bank-data-governance-agent-dev-bank-postgres-1"
ACTIVE_ID = "56bf7ea7a9f9f9d8a3c03d12162d973855f6299648e54b2c79eea931977a27a2"
ACTIVE_VOLUME = "bank-data-governance-agent-dev_bank-postgres-data"
ACTIVE_DB = "bank_governance_synthetic_dev"
ROLE = "bank_governance_dev"


def docker(*args, input=None, check=True, timeout=120):
    result = subprocess.run(["docker", *args], input=input, text=True,
                            capture_output=True, encoding="utf-8", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Docker command {args[0]} failed ({result.returncode}): {result.stderr[-3500:]}")
    return result


def inspect(field, container):
    # Never inspect the whole object or Config.Env: those contain credentials.
    return json.loads(docker("inspect", "--format", "{{json ." + field + "}}", container).stdout)


def active_guard():
    if inspect("Id", ACTIVE) != ACTIVE_ID:
        raise RuntimeError("Original container identity changed")
    state = inspect("State", ACTIVE)
    if not state["Running"] or state.get("Health", {}).get("Status") != "healthy":
        raise RuntimeError("Original container is no longer healthy")
    mounts = inspect("Mounts", ACTIVE)
    data = [m for m in mounts if m["Destination"] == "/var/lib/postgresql/data"]
    if len(data) != 1 or data[0].get("Name") != ACTIVE_VOLUME:
        raise RuntimeError("Original storage changed")
    ports = inspect("HostConfig.PortBindings", ACTIVE)
    if ports != {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5434"}]}:
        raise RuntimeError("Original published port changed")
    users = docker("ps", "-a", "--filter", f"volume={ACTIVE_VOLUME}", "--format", "{{.ID}}").stdout.split()
    if users != [ACTIVE_ID[:12]]:
        raise RuntimeError("Original volume has unexpected users")
    return {"container": ACTIVE, "id": ACTIVE_ID, "volume": ACTIVE_VOLUME,
            "database": ACTIVE_DB, "image_id": inspect("Image", ACTIVE)}


def isolated_guard(state):
    run = state["run_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", run):
        raise RuntimeError("Invalid run ID")
    expected = {"container": "nbm-pg17-validation-" + run,
                "database": "nbm_validation_" + run, "volume": "nbm-validation-" + run}
    if any(state[k] != v for k, v in expected.items()):
        raise RuntimeError("Unexpected isolated resource name")
    name = state["container"]
    if name == ACTIVE or state["database"] == ACTIVE_DB or state["volume"] == ACTIVE_VOLUME:
        raise RuntimeError("Isolation target points to active resources")
    if inspect("Id", name) == ACTIVE_ID or inspect("Id", name) != state["container_id"]:
        raise RuntimeError("Isolated container identity changed")
    if inspect("Config.Labels", name).get("bank-governance.validation") != run:
        raise RuntimeError("Missing isolated-container ownership label")
    if inspect("HostConfig.NetworkMode", name) != "none" or inspect("HostConfig.PortBindings", name):
        raise RuntimeError("Isolated container exposes network access")
    mounts = inspect("Mounts", name)
    if len(mounts) != 1 or mounts[0].get("Name") != state["volume"] or mounts[0]["Destination"] != "/var/lib/postgresql/data":
        raise RuntimeError("Isolated container shares unexpected storage")
    if not inspect("State", name)["Running"]:
        raise RuntimeError("Isolated container is stopped")


def psql(container, database, sql, *, readonly=True, state=None, check=True):
    if not readonly:
        if state is None:
            raise RuntimeError("Writes require an isolated run manifest")
        isolated_guard(state)
        case_db = database in state.get("case_databases", []) and database.startswith("nbm_case_" + state["run_id"][:16] + "_")
        if container != state["container"] or (database != state["database"] and not case_db):
            raise RuntimeError("SQL write destination mismatch")
    elif container == ACTIVE and database != ACTIVE_DB:
        raise RuntimeError("Unexpected active database")
    options = "-c statement_timeout=120000 -c default_transaction_read_only=" + ("on" if readonly else "off")
    return docker("exec", "-i", "-e", "PGOPTIONS=" + options, container,
                  "psql", "-X", "--no-password", "--quiet", "--tuples-only", "--no-align",
                  "--set=ON_ERROR_STOP=1", "--set=VERBOSITY=verbose", "-U", ROLE, "-d", database,
                  input=sql, check=check)


def query(state, sql, *, active=False):
    container, database = (ACTIVE, ACTIVE_DB) if active else (state["container"], state["database"])
    return json.loads(psql(container, database, "BEGIN READ ONLY;\n" + sql + "\nCOMMIT;").stdout)


def case_database(state, label):
    """New empty database only, inside the guarded isolated container. Never removed."""
    if not re.fullmatch(r"[a-z_]{1,24}", label):
        raise RuntimeError("Invalid case label")
    isolated_guard(state)
    name = "nbm_case_" + state["run_id"][:16] + "_" + label + "_" + uuid.uuid4().hex[:8]
    docker("exec", state["container"], "createdb", "--no-password", "-U", ROLE, "--template=template0", name)
    state.setdefault("case_databases", []).append(name)
    return name


def snapshot(state=None, *, active=False):
    container, database = (ACTIVE, ACTIVE_DB) if active else (state["container"], state["database"])
    sql = (ROOT / "sql/integration/checks/legacy_snapshot.sql").read_text(encoding="utf-8")
    result = json.loads(psql(container, database, sql).stdout)
    if result["context"]["database"] != database:
        raise RuntimeError("Snapshot database mismatch")
    return result


def historical_fingerprints(state=None, *, active=False):
    sql = """
    SELECT jsonb_build_object(
      'CUSTOMER',(SELECT jsonb_agg(to_jsonb(t) ORDER BY customer_id) FROM public."CUSTOMER" t),
      'TRANSACTION',(SELECT jsonb_agg(to_jsonb(t) ORDER BY transaction_id) FROM public."TRANSACTION" t),
      'LOAN',(SELECT jsonb_agg(to_jsonb(t) ORDER BY loan_id) FROM public."LOAN" t),
      'documents',(SELECT jsonb_agg(jsonb_build_array(id::TEXT,corpus_id::TEXT,content,metadata,embedding::TEXT) ORDER BY id) FROM bank_knowledge.documents)
    );"""
    rows = query(state, sql, active=active)
    metadata = json.loads((ROOT / "data/source/bank_metadata.json").read_text(encoding="utf-8-sig"))
    data = {}
    for name, table in metadata["tables"].items():
        data[name] = rows[name]
        for row in data[name]:
            for field, spec in table["fields"].items():
                if spec["type"] == "FLOAT":
                    row[field] = float(row[field])
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = {"bank_data_sha256": digest(data), "corpus_sha256": digest(rows["documents"])}
    reference = json.loads((ROOT / "docs/agent-validation.json").read_text(encoding="utf-8"))
    if any(result[k] != reference[k] for k in result):
        raise RuntimeError("Historical content fingerprints differ")
    return result


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_state(path):
    path = Path(path).resolve()
    if not path.is_relative_to(LOCAL.resolve()) or path.name != "state.json":
        raise RuntimeError("State must be under the ignored local validation directory")
    state = json.loads(path.read_text(encoding="utf-8"))
    if path.parent.name != state["run_id"]:
        raise RuntimeError("Run directory mismatch")
    return path, state


def prepare():
    design.verify_sources()
    source = active_guard()
    before = snapshot(active=True)
    historical = historical_fingerprints(active=True)
    expected = {"public.CUSTOMER": 1000, "public.TRANSACTION": 5000, "public.LOAN": 500,
                "bank_knowledge.corpora": 1, "bank_knowledge.documents": 24}
    if {k: v["count"] for k, v in before["protected"]["rows"].items()} != expected:
        raise RuntimeError("Unexpected original counts")
    preflight = query(None, """SELECT jsonb_build_object('database',current_database(),
        'role',current_user,'version',current_setting('server_version'),
        'schemas',(SELECT COUNT(*) FROM pg_namespace WHERE nspname IN ('dim','cfg')),
        'open_transactions',(SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database()
           AND pid<>pg_backend_pid() AND backend_type='client backend' AND xact_start IS NOT NULL));""", active=True)
    if preflight["schemas"] or preflight["open_transactions"] or not preflight["version"].startswith("17."):
        raise RuntimeError("Unexpected preflight state; no backup or isolated resources created")
    run = uuid.uuid4().hex
    directory = LOCAL / run
    # Verify Git exclusion BEFORE producing a local backup or report.
    ignored = subprocess.run(["git", "check-ignore", "--quiet", str(directory / "state.json")], cwd=ROOT)
    if ignored.returncode:
        raise RuntimeError("Local artifacts directory is not ignored by Git")
    directory.mkdir(parents=True, exist_ok=False)
    state = {"run_id": run, "created_utc": datetime.now(timezone.utc).isoformat(), "source": source,
             "container": "nbm-pg17-validation-" + run, "database": "nbm_validation_" + run,
             "volume": "nbm-validation-" + run, "historical_fingerprints": historical,
             "status": "backup_pending"}
    state_file = directory / "state.json"
    save(state_file, state)
    save(directory / "legacy-before.json", before)
    save(directory / "preflight.json", preflight)
    state["source_files_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                      for _, p, _, _ in design.SOURCES}
    archive = "/tmp/nbm-" + run + ".dump"
    active_guard()
    docker("exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", ACTIVE,
           "pg_dump", "--no-password", "-U", ROLE, "-d", ACTIVE_DB, "--format=custom", "--file=" + archive)
    destination = directory / "database.dump"
    docker("cp", ACTIVE + ":" + archive, str(destination))
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Missing/empty local backup")
    archive_list = docker("exec", ACTIVE, "pg_restore", "--list", archive).stdout
    for label in ("TABLE DATA public CUSTOMER", "TABLE DATA public TRANSACTION", "TABLE DATA public LOAN",
                  "TABLE DATA bank_knowledge corpora", "TABLE DATA bank_knowledge documents", "EXTENSION - vector"):
        if label not in archive_list:
            raise RuntimeError("Missing archive object: " + label)
    (directory / "archive-list.txt").write_text(archive_list, encoding="utf-8")
    roles = docker("exec", ACTIVE, "pg_dumpall", "--no-password", "--roles-only", "--no-role-passwords", "-U", ROLE).stdout
    if re.search(r"\bPASSWORD\s+'", roles, re.I):
        raise RuntimeError("Role export unexpectedly contains a password")
    (directory / "roles-without-passwords.sql").write_text(roles, encoding="utf-8")
    state["backup"] = {"path": str(destination), "bytes": destination.stat().st_size,
                       "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "list_verified": True}
    save(directory / "backup.json", state["backup"])
    if snapshot(active=True)["protected"] != before["protected"]:
        raise RuntimeError("Original changed during backup; stopping")
    state["status"] = "backup_verified"
    save(state_file, state)
    print(json.dumps({"backup": state["backup"], "state_file": str(state_file)}), flush=True)

    if docker("ps", "-a", "--filter", "name=^/" + state["container"] + "$", "--format", "{{.ID}}").stdout.strip():
        raise RuntimeError("Isolated container name already exists")
    if state["volume"] in docker("volume", "ls", "--format", "{{.Name}}").stdout.splitlines():
        raise RuntimeError("Isolated volume already exists")
    container_id = docker("run", "--detach", "--pull=never", "--name", state["container"],
        "--label", "bank-governance.validation=" + run, "--network", "none",
        "--mount", "type=volume,source=" + state["volume"] + ",target=/var/lib/postgresql/data",
        "--env", "POSTGRES_USER=" + ROLE, "--env", "POSTGRES_DB=" + state["database"],
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--health-cmd", "pg_isready -U " + ROLE + " -d " + state["database"],
        "--health-interval=2s", "--health-timeout=3s", "--health-retries=20", source["image_id"]).stdout.strip()
    state["container_id"] = container_id
    state["status"] = "isolated_created"
    save(state_file, state)
    for _ in range(50):
        status = inspect("State", state["container"])
        if status.get("Health", {}).get("Status") == "healthy":
            break
        if not status["Running"]:
            raise RuntimeError("Isolated PostgreSQL stopped during initialization")
        time.sleep(1)
    else:
        raise RuntimeError("Isolated health timeout")
    isolated_guard(state)
    identity = query(state, "SELECT jsonb_build_object('database',current_database(),'version',current_setting('server_version')); ")
    if identity["database"] != state["database"] or not identity["version"].startswith("17."):
        raise RuntimeError("Wrong isolated PostgreSQL destination")
    if hashlib.sha256(destination.read_bytes()).hexdigest() != state["backup"]["sha256"]:
        raise RuntimeError("Local backup changed")
    docker("cp", str(destination), state["container"] + ":/tmp/database.dump")
    isolated_guard(state)
    restored = docker("exec", state["container"], "pg_restore", "--no-password", "--exit-on-error", "--single-transaction",
                      "-U", ROLE, "--dbname=" + state["database"], "/tmp/database.dump")
    (directory / "restore-stderr.txt").write_text(restored.stderr, encoding="utf-8")
    after = snapshot(state)
    save(directory / "legacy-restored.json", after)
    if after["protected"] != before["protected"] or historical_fingerprints(state) != historical:
        raise RuntimeError("Restored schema/data/embedding fingerprints differ")
    state.update(status="restored_verified", restoration_matches=True, isolated_identity=identity)
    save(state_file, state)
    print(json.dumps({"restoration": "verified", "container": state["container"], "database": state["database"],
                      "volume": state["volume"], "network": "none", "published_ports": []}), flush=True)
    return state_file


def finish(path):
    state_file, state = load_state(path)
    active_guard()
    before = json.loads((state_file.parent / "legacy-before.json").read_text(encoding="utf-8"))
    active_after = snapshot(active=True)
    isolated_after = snapshot(state)
    if active_after["protected"] != before["protected"] or isolated_after["protected"] != before["protected"]:
        raise RuntimeError("Protected data/schema/embedding content changed")
    if historical_fingerprints(active=True) != state["historical_fingerprints"]:
        raise RuntimeError("Historical fingerprints changed")
    schemas = query(None, "SELECT COALESCE(jsonb_agg(nspname),'[]'::JSONB) FROM pg_namespace WHERE nspname IN ('dim','cfg');", active=True)
    if schemas:
        raise RuntimeError("New schemas unexpectedly exist on active database")
    design.verify_sources()
    save(state_file.parent / "legacy-active-after.json", active_after)
    save(state_file.parent / "legacy-isolated-after.json", isolated_after)
    state.update(active_preserved=True, isolated_legacy_preserved=True, active_new_schemas=[],
                 verified_utc=datetime.now(timezone.utc).isoformat())
    save(state_file, state)
    print(json.dumps({"active_preserved": True, "isolated_legacy_preserved": True,
                      "active_new_schemas": [], "historical_fingerprints": state["historical_fingerprints"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finish"))
    parser.add_argument("--state")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.state:
        finish(args.state)
    else:
        parser.error("finish requires --state")


if __name__ == "__main__":
    main()
