"""Post-publication acceptance: SELECT/READ ONLY against the explicitly recorded DB.

No migration, ingestion, synthetic-data generation, reset or write fixture.
"""
import hashlib
import os
from pathlib import Path

import pytest

from scripts import new_bank_publication as p
from scripts import new_bank_model as m
from scripts import new_bank_runtime_validation as r


@pytest.fixture(scope="module")
def publication():
    path=os.environ.get("BANK_PUBLICATION_STATE")
    if not path:
        pytest.skip("Explicit BANK_PUBLICATION_STATE required for read-only acceptance")
    _,state=p.load_state(path)
    assert state["status"]=="published_verified"
    return state,p.verify(state)


@pytest.mark.parametrize("name,count",m.EXPECTED.items())
def test_confirmed_table_counts(publication,name,count):
    assert publication[1]["counts"][name]==count


def test_exact_financial_acceptance(publication):
    quality=publication[1]["quality"]
    assert quality["reconciled_account_months"]==100000
    assert quality["max_absolute_reconciliation_difference"]=="0.00"
    assert not any(quality["violations"].values())
    assert quality["january_without_movements"]


def test_approved_hash_identity_and_actual_canonical_content(publication):
    manifest=publication[1]["manifest"]
    assert manifest==p.reference()
    assert manifest["dataset_sha256"]==p.EXPECTED_HASH
    assert p.active_read(m.hashes_sql())==manifest["tables"]


def test_original_columns_and_dim_txn_definition_preserved(publication):
    structure=p.active_read(m.structure_sql())
    names={t.name for t in m.design.ORIGINAL_TABLES}
    assert sum(c[0] in names for c in structure["columns"])==42
    assert len(structure["tables"])==7
    assert not [c for c in structure["constraints"] if c[0]==m.design.TXN.name]


def test_quality_exceptions_remain_overlapping_and_explicit(publication):
    anomaly=publication[1]["quality"]["anomalies"]
    assert anomaly["pf_registration_before_birth"]==44
    assert anomaly["pf_under_18_at_registration"]==1027
    assert anomaly["pf_under_18_at_source_reference"]==0
    overlap=p.active_read("SELECT COUNT(*) FROM dim.dim_cliente WHERE tipo_persona='PF' AND fec_alta<fec_nac "
                          "AND age(fec_alta,fec_nac)<INTERVAL '18 years'")
    assert overlap==44
    assert anomaly["currency"] is None


def test_protected_counts_content_and_agent_files(publication):
    state,_=publication
    snapshot=r.snapshot(active=True)
    assert snapshot["protected"]==state["before"]["protected"]
    assert {n:t["count"] for n,t in snapshot["protected"]["rows"].items()}=={
        "public.CUSTOMER":1000,"public.TRANSACTION":5000,"public.LOAN":500,
        "bank_knowledge.corpora":1,"bank_knowledge.documents":24}
    assert r.historical_fingerprints(active=True)==state["historical_fingerprints"]
    assert p.file_hashes(p.PROTECTED_FILES)==state["protected_files"]


def test_fresh_backup_file_remains_intact(publication):
    backup=publication[0]["backup"]
    path=Path(backup["path"])
    assert path.stat().st_size==backup["bytes"]>0
    assert hashlib.sha256(path.read_bytes()).hexdigest()==backup["sha256"]
    assert backup["dump_exit_code"]==backup["list_exit_code"]==backup["restore_exit_code"]==0
    assert backup["restoration_verified"]
