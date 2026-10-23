"""Explicit, backed-up publication to ONE pinned development PostgreSQL destination.

The isolated loader/transport remain isolated-only. No arbitrary DSN, SQL, reset,
role change, old-table write, upstream execution or corpus ingestion is exposed.
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

from scripts import new_bank_model as model
from scripts import new_bank_runtime_validation as runtime

ROOT = model.design.ROOT
EXPECTED_HASH = "a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b"
REFERENCE = ROOT / "data/source/new_bank_model/dataset-202601.manifest.json"
AUTHORIZATION = "publish-new-bank-2026-to-original-development-only-v1"
PINNED = {"container": runtime.ACTIVE, "id": runtime.ACTIVE_ID,
          "database": runtime.ACTIVE_DB, "volume": runtime.ACTIVE_VOLUME,
          "host": "127.0.0.1", "port": 5434}
PROTECTED_FILES = ("scripts/bank_data.py", "scripts/knowledge_corpus.py", "scripts/data_steward_agent.py",
                   "data/source/bank_metadata.json", "data/corpus/bank_metadata.documents.jsonl")
CODE_FILES = ("scripts/new_bank_model.py", "scripts/new_bank_publication.py",
              "scripts/new_bank_integration.py", "scripts/new_bank_runtime_validation.py",
              "sql/integration/checks/model_structure.sql", "sql/integration/checks/new_bank_dataset.sql",
              "sql/integration/checks/legacy_snapshot.sql", "data/source/new_bank_model/dataset-202601.manifest.json")
IDENTITY_SQL = """SELECT jsonb_build_object('database',current_database(),'role',current_user,
 'version',current_setting('server_version'),'vector',(SELECT extversion FROM pg_extension WHERE extname='vector'),
 'database_owner',(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
 'connect',has_database_privilege(current_user,current_database(),'CONNECT'),
 'create',has_database_privilege(current_user,current_database(),'CREATE'),
 'temp',has_database_privilege(current_user,current_database(),'TEMP'),
 'schemas',(SELECT COALESCE(jsonb_agg(nspname ORDER BY nspname),'[]') FROM pg_namespace WHERE nspname IN ('dim','cfg')),
 'open_transactions',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
    AND pid<>pg_backend_pid() AND backend_type='client backend' AND xact_start IS NOT NULL),
 'prepared_transactions',(SELECT count(*) FROM pg_prepared_xacts WHERE database=current_database()),
 'event_triggers',(SELECT count(*) FROM pg_event_trigger WHERE evtenabled<>'D'))"""


def file_hashes(names):
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def reference():
    value = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if value["dataset_sha256"] != EXPECTED_HASH or (model.GENERATOR_VERSION, model.ALGORITHM, model.SEED) != (
            "1.0.0", "sha256-rounded-uniform-v1", 202601):
        raise RuntimeError("Unexpected reference or generator version")
    return value


def active_read(sql):
    result = runtime.psql(runtime.ACTIVE, runtime.ACTIVE_DB,
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL search_path=pg_catalog; "
        "SET LOCAL DateStyle='ISO, YMD'; " + sql + "; COMMIT;")
    return json.loads(result.stdout)


def identity_guard_sql():
    return model.assertion(f"current_database()='{runtime.ACTIVE_DB}' AND current_user='{runtime.ROLE}' "
        "AND current_setting('server_version_num')::int/10000=17", "Authorized publication SQL destination mismatch")


def audit_write_scope(sql):
    """Deny protected or destructive SQL; COPY contents are data, not SQL commands."""
    lines, copying = [], False
    for line in sql.splitlines():
        if copying:
            if line == r"\.":
                copying = False
            continue
        lines.append(line)
        if re.match(r"COPY\s+pg_temp\.nbm_stage_\d+\s", line):
            copying = True
    text = "\n".join(lines)
    if copying or any(name in text for name in model.design.PROTECTED):
        raise RuntimeError("Protected-object reference or incomplete COPY in publication SQL")
    if re.search(r"\b(?:DROP|TRUNCATE|DELETE\s+FROM|UPDATE\s+\w+\s+SET|CREATE\s+ROLE|GRANT|REVOKE)\b", text, re.I):
        raise RuntimeError("Forbidden operation in publication SQL")
    # ON DELETE RESTRICT in approved constraints is not a DELETE statement.
    schemas = re.findall(r"\b(?:INSERT\s+INTO|COPY|LOCK\s+TABLE|CREATE\s+TABLE|ALTER\s+TABLE)\s+([\w.]+)", text, re.I)
    if any(not name.startswith(("dim.", "cfg.", "pg_temp.")) for name in schemas):
        raise RuntimeError("Publication write outside dim/cfg/temporary staging")
    if "bank_model_control" in text:
        raise RuntimeError("Publication must not create an additional control schema")
    return True


def preflight(isolated_path):
    runtime.docker("info", "--format", "{{json .ServerVersion}}")
    source = runtime.active_guard()
    _, isolated = runtime.load_state(isolated_path)
    info = active_read(IDENTITY_SQL)
    if info["database"] != runtime.ACTIVE_DB or info["role"] != runtime.ROLE or info["database_owner"] != runtime.ROLE:
        raise RuntimeError("Original database identity/owner mismatch")
    if not info["version"].startswith("17.") or info["vector"] != "0.8.7" or info["schemas"]:
        raise RuntimeError("Unexpected version/vector or preexisting dim/cfg")
    if not all(info[k] for k in ("connect", "create", "temp")) or any(info[k] for k in (
            "open_transactions", "prepared_transactions", "event_triggers")):
        raise RuntimeError("Unexpected permissions or concurrent transaction/event trigger")
    before = runtime.snapshot(active=True)
    previous = json.loads((Path(isolated_path).parent/"legacy-before.json").read_text(encoding="utf-8"))
    if before["protected"] != previous["protected"]:
        raise RuntimeError("Original data/schema/vector snapshot differs")
    historical = runtime.historical_fingerprints(active=True)
    rows, manifest, timings = model.prepare(202601)
    if manifest != reference():
        raise RuntimeError("Generated content differs from the approved reference")
    verified = model.verify(isolated, manifest)
    if any(verified["quality"]["violations"].values()):
        raise RuntimeError("Isolated dataset is not valid")
    script = model.load_script(isolated, rows, manifest, runtime.ACTIVE_DB, control_mode="cfg_comment")
    audit_write_scope(script)
    model.design.verify_sources()
    return {"target": PINNED, "source": source, "identity": info, "before": before,
            "historical_fingerprints": historical, "protected_files": file_hashes(PROTECTED_FILES),
            "code_files": file_hashes(CODE_FILES), "manifest": manifest,
            "isolated_state": str(Path(isolated_path).resolve()), "structure_002": isolated["structure_002"],
            "isolated_dataset_verified": True, "generation_timings": timings}


def backup(isolated_path, *, authorized=False):
    if not authorized:
        raise RuntimeError("Explicit original-development publication authorization required")
    state = preflight(isolated_path)
    run = uuid.uuid4().hex
    directory = runtime.LOCAL / ("publication_"+run)
    if subprocess.run(["git", "check-ignore", "--quiet", str(directory/"database.dump")], cwd=ROOT).returncode:
        raise RuntimeError("Backup directory is not excluded from Git")
    directory.mkdir(exist_ok=False)
    archive = "/tmp/nbm-publication-"+run+".dump"
    runtime.active_guard()
    result = runtime.docker("exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", runtime.ACTIVE,
        "pg_dump", "--no-password", "-U", runtime.ROLE, "-d", runtime.ACTIVE_DB,
        "--format=custom", "--file="+archive)
    destination = directory/"database.dump"
    runtime.docker("cp", runtime.ACTIVE+":"+archive, str(destination))
    if not destination.is_file() or destination.stat().st_size<=0 or destination.read_bytes()[:5]!=b"PGDMP":
        raise RuntimeError("Missing, empty or non-custom backup")
    listing = runtime.docker("exec", runtime.ACTIVE, "pg_restore", "--list", archive)
    for label in ("TABLE DATA public CUSTOMER", "TABLE DATA public TRANSACTION", "TABLE DATA public LOAN",
                  "TABLE DATA bank_knowledge corpora", "TABLE DATA bank_knowledge documents", "EXTENSION - vector"):
        if label not in listing.stdout:
            raise RuntimeError("Missing backup object: "+label)
    (directory/"archive-list.txt").write_text(listing.stdout, encoding="utf-8")
    roles = runtime.docker("exec", runtime.ACTIVE, "pg_dumpall", "--no-password", "-U", runtime.ROLE,
                           "--roles-only", "--no-role-passwords").stdout
    if re.search(r"\bPASSWORD\s+'", roles, re.I):
        raise RuntimeError("Unexpected secret in role export")
    (directory/"roles-without-passwords.sql").write_text(roles, encoding="utf-8")
    # Validate the file actually copied to the host, not only the container archive.
    isolated_file,isolated=runtime.load_state(isolated_path)
    restore_db=runtime.case_database(isolated,"publication_fresh_backup")
    runtime.save(isolated_file,isolated)
    restored_archive="/tmp/publication-fresh-"+run+".dump"
    runtime.docker("cp",str(destination),isolated["container"]+":"+restored_archive)
    runtime.isolated_guard(isolated)
    local_listing=runtime.docker("exec",isolated["container"],"pg_restore","--list",restored_archive)
    if local_listing.stdout!=listing.stdout:
        raise RuntimeError("Host backup archive listing differs")
    if restore_db==runtime.ACTIVE_DB or not restore_db.startswith("nbm_case_"+isolated["run_id"][:16]+"_"):
        raise RuntimeError("Fresh backup restore destination mismatch")
    restored=runtime.docker("exec",isolated["container"],"pg_restore","--no-password","--exit-on-error",
        "--single-transaction","-U",runtime.ROLE,"-d",restore_db,restored_archive)
    recovered=runtime.snapshot(dict(isolated,database=restore_db))
    if recovered["protected"]!=state["before"]["protected"]:
        raise RuntimeError("Fresh backup restoration data/schema/embedding mismatch")
    runtime.save(directory/"fresh-backup-restored.json",recovered)
    if runtime.snapshot(active=True)["protected"] != state["before"]["protected"]:
        raise RuntimeError("Original changed during backup; no publication allowed")
    state.update(run_id=run, authorization=AUTHORIZATION, status="backup_verified",
        backup={"path": str(destination), "bytes": destination.stat().st_size,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "dump_exit_code":result.returncode,
                "list_exit_code":listing.returncode, "container_archive":archive,
                "restoration_verified":True,"restore_exit_code":restored.returncode,
                "restore_container":isolated["container"],"restore_database":restore_db},
        created_utc=datetime.now(timezone.utc).isoformat(), migrations=[])
    path = directory/"publication.json"
    runtime.save(path,state)
    runtime.save(directory/"legacy-before.json",state["before"])
    return path,state


def load_state(path):
    path = Path(path).resolve()
    if not path.is_relative_to(runtime.LOCAL.resolve()) or path.name!="publication.json":
        raise RuntimeError("Explicit local publication.json required")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-f0-9]{32}",state["run_id"]) or path.parent.name!="publication_"+state["run_id"]:
        raise RuntimeError("Invalid publication directory")
    return path,state


def authorization_guard(state, *, authorized=False):
    if not authorized or state.get("authorization")!=AUTHORIZATION or state.get("target")!=PINNED:
        raise RuntimeError("Publication authorization/target mismatch")
    if state.get("status") not in ("backup_verified", "001_applied", "002_applied", "published_verified"):
        raise RuntimeError("Publication state is not writable")
    if not state.get("backup",{}).get("restoration_verified"):
        raise RuntimeError("Fresh backup restoration must be verified first")
    runtime.active_guard()
    if state["protected_files"]!=file_hashes(PROTECTED_FILES) or state["code_files"]!=file_hashes(CODE_FILES):
        raise RuntimeError("Reviewed code or protected files changed after backup")
    path = Path(state["backup"]["path"]).resolve()
    if not path.is_relative_to(runtime.LOCAL.resolve()) or path.parent.name!="publication_"+state["run_id"]:
        raise RuntimeError("Backup location mismatch")
    if not path.is_file() or path.stat().st_size!=state["backup"]["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=state["backup"]["sha256"]:
        raise RuntimeError("Fresh backup is no longer valid")
    if state["manifest"]!=reference():
        raise RuntimeError("Publication reference manifest mismatch")
    model.design.verify_sources()


def _write(state, sql, *, authorized):
    authorization_guard(state,authorized=authorized)
    audit_write_scope(sql)
    # SQL comes exclusively from the two pinned files or the shared loader below.
    result = runtime.docker("exec", "-i", "-e", "PGOPTIONS=-c statement_timeout=120000 -c default_transaction_read_only=off",
        runtime.ACTIVE, "psql", "-X", "--no-password", "--quiet", "--tuples-only", "--no-align",
        "--set=ON_ERROR_STOP=1", "--set=VERBOSITY=verbose", "-U", runtime.ROLE, "-d", runtime.ACTIVE_DB,
        input=sql,check=False)
    if result.returncode:
        messages=[line for line in result.stderr.splitlines() if line.startswith(("ERROR:","DETAIL:","HINT:"))]
        raise RuntimeError("Publication transaction failed; stop for review: "+("\n".join(messages) or result.stderr[:1200]))
    return result


def verify(state):
    runtime.active_guard()
    if state.get("target")!=PINNED:
        raise RuntimeError("Unexpected verification target")
    manifest=reference()
    sql="DO $v$ DECLARE q jsonb; BEGIN "+model.schema_guard(state,runtime.ACTIVE_DB)
    sql+=model.comment_identity_guard(manifest)+model.content_guard(manifest)+" END $v$;\n"
    sql+="SELECT jsonb_build_object('manifest',obj_description('cfg'::regnamespace,'pg_namespace')::jsonb->'manifest',"
    sql+="'counts',("+model.counts_sql()+"),'quality',("+model.quality_sql()+"))"
    result=active_read(sql)
    if runtime.snapshot(active=True)["protected"]!=state["before"]["protected"]:
        raise RuntimeError("Protected before/after snapshot mismatch; stop")
    if runtime.historical_fingerprints(active=True)!=state["historical_fingerprints"]:
        raise RuntimeError("Historical fingerprints changed; stop")
    if file_hashes(PROTECTED_FILES)!=state["protected_files"]:
        raise RuntimeError("Protected source files changed")
    return result


def publish(path, *, authorized=False):
    path,state=load_state(path)
    authorization_guard(state,authorized=authorized)
    rows,manifest,timings=model.prepare(202601)
    if manifest!=state["manifest"]:
        raise RuntimeError("Generated manifest mismatch; no SQL applied")
    if state["status"]=="backup_verified":
        # Recheck all live assumptions immediately before the first DB write.
        current=preflight(state["isolated_state"])
        if current["before"]["protected"]!=state["before"]["protected"]:
            raise RuntimeError("Preflight changed after fresh backup")
    elif state["status"]!="published_verified":
        raise RuntimeError("Incomplete previous attempt; inspect before resuming")
    if state["status"]=="backup_verified":
        for index,relative in enumerate(model.design.manifest()["migrations"],1):
            sql=(ROOT/relative).read_text(encoding="utf-8")
            digest=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
            if digest!=manifest["migrations_sha256"][relative]:
                raise RuntimeError("Unapproved migration bytes")
            result=_write(state,"DO $id$ BEGIN "+identity_guard_sql()+" END $id$;\n"+sql,authorized=authorized)
            state["migrations"].append({"file":relative,"sha256":digest,"exit_code":result.returncode})
            state["status"]=f"{index:03}_applied"
            runtime.save(path,state)
        if active_read(model.structure_sql())!=state["structure_002"] or any(active_read(model.counts_sql()).values()):
            raise RuntimeError("Unexpected migrated structure or nonempty new tables")
    script=model.load_script(state,rows,manifest,runtime.ACTIVE_DB,control_mode="cfg_comment")
    start=time.perf_counter()
    result=_write(state,script,authorized=authorized)
    loaded=json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    elapsed=time.perf_counter()-start
    validated=verify(state)
    before_repeat=active_read("SELECT to_jsonb(obj_description('cfg'::regnamespace,'pg_namespace'))")
    repeated=_write(state,script,authorized=authorized)
    repeat=json.loads(next(line for line in repeated.stdout.splitlines() if line.startswith("{")))
    if repeat["result"]!="sin cambios":
        raise RuntimeError("Second load was not a no-op")
    after=verify(state)
    if validated!=after or before_repeat!=active_read("SELECT to_jsonb(obj_description('cfg'::regnamespace,'pg_namespace'))"):
        raise RuntimeError("Repeated publication changed data or manifest")
    state.update(status="published_verified",verified_utc=datetime.now(timezone.utc).isoformat(),
        result=loaded,repeat=repeat,validation=after,generation_timings=timings,load_seconds=elapsed,
        active_preserved=True)
    runtime.save(path,state)
    runtime.save(path.parent/"legacy-after.json",runtime.snapshot(active=True))
    return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("preflight","backup","publish","verify"))
    parser.add_argument("--isolated-state")
    parser.add_argument("--publication-state")
    parser.add_argument("--authorize-active-development",action="store_true")
    args=parser.parse_args(argv)
    if args.command in ("preflight","backup"):
        if not args.isolated_state:
            parser.error("--isolated-state is required")
        if args.command=="preflight":
            result=preflight(args.isolated_state)
        else:
            path,state=backup(args.isolated_state,authorized=args.authorize_active_development)
            result={"publication_state":str(path),"backup":state["backup"]}
    else:
        if not args.publication_state:
            parser.error("--publication-state is required")
        if args.command=="publish":
            result=publish(args.publication_state,authorized=args.authorize_active_development)
        else:
            result=verify(load_state(args.publication_state)[1])
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
