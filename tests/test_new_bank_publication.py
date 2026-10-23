"""Publication authorization/scope contracts without PostgreSQL or network."""
import copy
import json

import pytest

from scripts import new_bank_model as m
from scripts import new_bank_publication as p


@pytest.fixture(autouse=True)
def no_docker(monkeypatch):
    def denied(*args,**kwargs):
        pytest.fail("Unit publication test attempted Docker")
    monkeypatch.setattr(p.runtime,"docker",denied)


@pytest.mark.parametrize("authorized,state",[(False,{}),(True,{}),
    (True,{"authorization":p.AUTHORIZATION,"target":dict(p.PINNED,database="other")})])
def test_rejects_missing_authorization_or_arbitrary_destination(authorized,state):
    with pytest.raises(RuntimeError,match="authorization/target"):
        p.authorization_guard(state,authorized=authorized)


def test_backup_requires_explicit_authorization():
    with pytest.raises(RuntimeError,match="Explicit"):
        p.backup("unused",authorized=False)


@pytest.mark.parametrize("sql",[
    'INSERT INTO public."CUSTOMER" VALUES(1);',
    "CREATE TABLE bank_knowledge.bad(id int);", "TRUNCATE cfg.anything;",
    "DELETE FROM cfg.anything;", "CREATE SCHEMA bank_model_control;",
    "INSERT INTO another_schema.bad VALUES(1);",
])
def test_scope_rejects_protected_destructive_or_unapproved_objects(sql):
    with pytest.raises(RuntimeError):
        p.audit_write_scope(sql)


def test_approved_migrations_have_unchanged_bytes_and_scope():
    manifest=p.reference()
    for relative,digest in manifest["migrations_sha256"].items():
        assert p.file_hashes([relative])[relative]==digest
        assert p.audit_write_scope((p.ROOT/relative).read_text(encoding="utf-8"))


def test_cfg_comment_backend_does_not_add_schema_table_or_change_dataset():
    # Scope check the real rendered full pipeline, including NULL COPY markers.
    rows,manifest,_=m.prepare(202601)
    state={"structure_002":{}}
    script=m.load_script(state,rows,manifest,p.runtime.ACTIVE_DB,control_mode="cfg_comment")
    assert p.audit_write_scope(script)
    assert "bank_model_control" not in script
    assert "COMMENT ON SCHEMA cfg IS" in script
    assert "CREATE SCHEMA" not in script and "CREATE TABLE" not in script
    assert manifest==p.reference() and manifest["dataset_sha256"]==p.EXPECTED_HASH
    assert json.loads(m.schema_comment_manifest(manifest))["manifest"]==manifest
    assert "pg_advisory_xact_lock(7262026,1)" in script
    assert script.count("\nCOMMIT;")==1


def test_original_isolated_transport_still_rejects_active_write():
    with pytest.raises(RuntimeError):
        p.runtime.psql(p.runtime.ACTIVE,p.runtime.ACTIVE_DB,"SELECT 1;",readonly=False)
    with pytest.raises(RuntimeError):
        m.environment(dict(run_id="0"*32,container=p.runtime.ACTIVE,database=p.runtime.ACTIVE_DB,volume=p.runtime.ACTIVE_VOLUME))


def test_invalid_storage_mode_rejected():
    with pytest.raises(ValueError):
        m.load_script({}, {}, {}, "arbitrary",control_mode="arbitrary")


def test_publication_state_must_be_explicit_local_file():
    with pytest.raises(RuntimeError,match="Explicit local"):
        p.load_state(p.ROOT/"publication.json")
