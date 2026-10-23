"""Opt-in loader tests. All writes target new cases inside the recorded isolated server.

Never uses legacy DB/dataset fixtures; leaves case databases for review, no cleanup.
"""
from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from scripts import new_bank_model as m
from scripts import new_bank_runtime_validation as r
from scripts import new_bank_integration as d


@pytest.fixture(scope="module")
def run():
    path = os.environ.get("BANK_MODEL_LOAD_TEST_STATE")
    if not path:
        pytest.skip("Explicit BANK_MODEL_LOAD_TEST_STATE required for isolated loader tests")
    state_file, state = r.load_state(path)
    m.environment(state)
    state["_file"] = state_file
    return state


def case(state, label):
    database = r.case_database(state,label)
    r.save(state["_file"],{k:v for k,v in state.items() if not k.startswith("_")})
    for path in d.manifest()["migrations"]:
        r.psql(state["container"],database,(d.ROOT/path).read_text(encoding="utf-8"),readonly=False,state=state)
    return database


@pytest.fixture(scope="module")
def prepared():
    return m.prepare()


@pytest.fixture(scope="module")
def trial(run):
    return case(run,"loader_atomic")


def counts(run, database):
    return m.read(run,m.counts_sql(),database)


def test_01_original_and_isolated_identities(run):
    r.active_guard()
    assert run["container"] != r.ACTIVE and run["volume"] != r.ACTIVE_VOLUME
    assert r.historical_fingerprints(active=True)==run["historical_fingerprints"]
    assert r.historical_fingerprints(run)==run["historical_fingerprints"]


def test_02_sql_identity_rejects_wrong_database_inside_transaction(run,prepared,trial):
    rows,manifest,_ = prepared
    script = m.load_script(run,rows,manifest,"wrong_destination")
    result = r.psql(run["container"],trial,script,readonly=False,state=run,check=False)
    assert result.returncode and "SQL destination mismatch" in result.stderr
    assert all(n==0 for n in counts(run,trial).values())


def test_03_partial_load_rolls_back_data_and_control_schema(run,prepared,trial):
    rows,manifest,_ = prepared
    with pytest.raises(RuntimeError,match="Injected rollback test"):
        m.load(run,rows,manifest,database=trial,_fail_after=d.BALANCE.name)
    assert all(n==0 for n in counts(run,trial).values())
    assert m.read(run,"SELECT to_jsonb(to_regnamespace('bank_model_control') IS NULL)",trial)


def test_04_one_cent_error_rejected_before_commit(run,prepared,trial):
    rows,manifest,_ = prepared
    altered = dict(rows)
    events = list(rows[d.MOVEMENT.name])
    row = list(events[0])
    row[5] += m.CENT
    events[0] = tuple(row)
    altered[d.MOVEMENT.name] = tuple(events)
    bad_manifest = m.dataset_manifest(altered,manifest["seed"])
    with pytest.raises(RuntimeError,match="Dataset quality/financial failure"):
        m.load(run,altered,bad_manifest,database=trial)
    assert all(n==0 for n in counts(run,trial).values())


def test_05_concurrent_identical_loads_publish_once(run,prepared,trial):
    rows,manifest,_ = prepared
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:m.load(run,rows,manifest,database=trial),range(2)))
    assert sorted(x["result"] for x in results)==["cargado","sin cambios"]
    result = m.verify(run,manifest,trial)
    assert result["quality"]["reconciled_account_months"]==100000
    assert not any(result["quality"]["violations"].values())
    assert counts(run,trial)==m.EXPECTED
    r.save(run["_file"].parent/"loader-concurrency.json",dict(database=trial,results=results,verification=result))


def test_06_repeat_has_no_row_or_manifest_changes(run,prepared,trial):
    rows,manifest,_ = prepared
    before = m.read(run,m.hashes_sql(),trial)
    # xmin catches an accidental UPDATE that preserved identical content.
    metadata_before = m.read(run,"SELECT jsonb_build_array(xmin::text,manifest) FROM bank_model_control.datasets",trial)
    result = m.load(run,rows,manifest,database=trial)
    assert result["result"]=="sin cambios"
    assert m.read(run,m.hashes_sql(),trial)==before
    assert m.read(run,"SELECT jsonb_build_array(xmin::text,manifest) FROM bank_model_control.datasets",trial)==metadata_before


@pytest.mark.parametrize("field,value",[("seed",202602),("generator_version","999.0.0")])
def test_07_incompatible_identity_rejected(run,prepared,trial,field,value,monkeypatch):
    rows,manifest,_ = prepared
    if field=="seed":
        other_rows,other_manifest,_ = m.prepare(value)
    else:
        monkeypatch.setattr(m,"GENERATOR_VERSION",value)
        other_rows,other_manifest = rows,m.dataset_manifest(rows,manifest["seed"])
    with pytest.raises(RuntimeError,match="Dataset identity mismatch"):
        m.load(run,other_rows,other_manifest,database=trial)
    assert m.read(run,m.hashes_sql(),trial)==manifest["tables"]


def test_08_partial_existing_dataset_not_adopted(run,prepared):
    database = case(run,"loader_partial")
    r.psql(run["container"],database,"INSERT INTO dim.dim_cliente(num_cte) VALUES(1);",readonly=False,state=run)
    with pytest.raises(RuntimeError,match="Partial dataset"):
        m.load(run,*prepared[:2],database=database)
    assert counts(run,database)[d.CLIENT.name]==1
    assert sum(counts(run,database).values())==1


def test_09_incompatible_control_schema_not_adopted(run,prepared):
    database = case(run,"loader_control")
    r.psql(run["container"],database,"CREATE SCHEMA bank_model_control; CREATE TABLE bank_model_control.datasets(wrong int);",readonly=False,state=run)
    with pytest.raises(RuntimeError,match="Incompatible control definition"):
        m.load(run,*prepared[:2],database=database)
    assert all(n==0 for n in counts(run,database).values())


def test_10_structure_drift_rejected_without_data(run,prepared):
    database = case(run,"loader_drift")
    r.psql(run["container"],database,"CREATE INDEX foreign_index ON dim.dim_cliente(fec_nac);",readonly=False,state=run)
    with pytest.raises(RuntimeError,match="structural signature differs"):
        m.load(run,*prepared[:2],database=database)
    assert all(n==0 for n in counts(run,database).values())


def test_11_active_destination_denied_before_any_docker_operation(run,monkeypatch):
    altered = dict(run,container=r.ACTIVE,database=r.ACTIVE_DB,volume=r.ACTIVE_VOLUME)
    def forbidden(*args,**kwargs):
        pytest.fail("active target must be rejected without touching Docker")
    monkeypatch.setattr(r,"docker",forbidden)
    with pytest.raises(RuntimeError):
        m.environment(altered)


def test_12_final_legacy_preservation(run):
    r.finish(run["_file"])
