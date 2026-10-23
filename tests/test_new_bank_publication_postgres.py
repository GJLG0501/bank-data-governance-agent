"""Rehearse the cfg-only publication backend in the existing isolated container.

No authorized-active transport is invoked. No cleanup or legacy fixtures.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import new_bank_model as m
from scripts import new_bank_publication as p
from scripts import new_bank_runtime_validation as r


@pytest.fixture(scope="module")
def trial():
    source=os.environ.get("BANK_PUBLICATION_TEST_STATE")
    if not source:
        pytest.skip("Explicit BANK_PUBLICATION_TEST_STATE required")
    path,state=r.load_state(source)
    r.isolated_guard(state)
    archive=Path(state["backup"]["path"])
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==state["backup"]["sha256"]
    database=r.case_database(state,"publication_rehearsal")
    r.save(path,state)
    container_archive="/tmp/publication-rehearsal-"+database.rsplit('_',1)[-1]+".dump"
    r.docker("cp",str(archive),state["container"]+":"+container_archive)
    r.isolated_guard(state)
    result=r.docker("exec",state["container"],"pg_restore","--no-password","--exit-on-error","--single-transaction",
        "-U",r.ROLE,"-d",database,container_archive)
    assert result.returncode==0
    for relative in m.design.manifest()["migrations"]:
        r.psql(state["container"],database,(p.ROOT/relative).read_text(encoding="utf-8"),readonly=False,state=state)
    rows,manifest,_=m.prepare(202601)
    return state,database,rows,manifest,path


def execute(trial,sql,check=True):
    state,database,_,_,_=trial
    return r.psql(state["container"],database,sql,readonly=False,state=state,check=check)


def read(trial,sql):
    state,database,_,_,_=trial
    return json.loads(r.psql(state["container"],database,"BEGIN READ ONLY; SET LOCAL DateStyle='ISO,YMD'; "+sql+"; COMMIT;").stdout)


def script(trial,**kwargs):
    state,database,rows,manifest,_=trial
    return m.load_script(state,rows,manifest,database,control_mode="cfg_comment",**kwargs)


def test_01_restoration_and_migrations_match_approved_signature(trial):
    state,database,_,_,_=trial
    assert read(trial,m.structure_sql())==state["structure_002"]
    original=r.snapshot(dict(state,database=database))
    assert original["protected"]==r.snapshot(active=True)["protected"]
    assert all(n==0 for n in read(trial,m.counts_sql()).values())


def test_02_injected_failure_rolls_back_rows_and_metadata(trial):
    result=execute(trial,script(trial,_fail_after=m.design.BALANCE.name),check=False)
    assert result.returncode and "Injected rollback test" in result.stderr
    assert all(n==0 for n in read(trial,m.counts_sql()).values())
    assert read(trial,"SELECT to_jsonb(obj_description('cfg'::regnamespace,'pg_namespace') IS NULL)")


def test_03_concurrent_full_loads_commit_exactly_one_dataset(trial):
    sql=script(trial)
    assert p.audit_write_scope(sql)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:execute(trial,sql),range(2)))
    statuses=[json.loads(next(line for line in x.stdout.splitlines() if line.startswith('{')))["result"] for x in results]
    assert sorted(statuses)==["cargado","sin cambios"]
    assert read(trial,m.hashes_sql())==trial[3]["tables"]
    quality=read(trial,m.quality_sql())
    assert quality["reconciled_account_months"]==100000
    assert not any(quality["violations"].values())
    assert read(trial,"SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('dim','cfg') AND c.relkind='r'")==7
    r.save(trial[4].parent/"publication-rehearsal.json",dict(database=trial[1],results=statuses,quality=quality,
        dataset_sha256=trial[3]["dataset_sha256"],restored_legacy_preserved=True))


def test_04_repeat_preserves_comment_and_all_rows(trial):
    before=read(trial,"SELECT jsonb_build_array(description,xmin::text) FROM pg_description WHERE objoid='cfg'::regnamespace AND classoid='pg_namespace'::regclass")
    assert 'sin cambios' in execute(trial,script(trial)).stdout
    assert read(trial,m.hashes_sql())==trial[3]["tables"]
    assert before==read(trial,"SELECT jsonb_build_array(description,xmin::text) FROM pg_description WHERE objoid='cfg'::regnamespace AND classoid='pg_namespace'::regclass")


@pytest.mark.parametrize("field,value",[("seed",202602),("generator_version","2.0.0")])
def test_05_other_identity_is_rejected_without_overwrite(trial,field,value):
    state,database,rows,manifest,_=trial
    changed=dict(manifest,**{field:value})
    result=execute(trial,m.load_script(state,rows,changed,database,control_mode="cfg_comment"),check=False)
    assert result.returncode and "Dataset identity mismatch" in result.stderr
    assert read(trial,m.hashes_sql())==manifest["tables"]


def test_06_no_extra_control_schema_and_legacy_unchanged(trial):
    state,database,_,manifest,_=trial
    assert read(trial,"SELECT to_jsonb(to_regnamespace('bank_model_control') IS NULL)")
    assert r.snapshot(dict(state,database=database))["protected"]==r.snapshot(active=True)["protected"]
    sql="DO $v$ DECLARE q jsonb; BEGIN "+m.schema_guard(state,database)+m.comment_identity_guard(manifest)+m.content_guard(manifest)+" END $v$; SELECT to_jsonb(true)"
    assert read(trial,sql)
