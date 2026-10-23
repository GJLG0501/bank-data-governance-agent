"""Offline generator contracts; no legacy fixtures or service access."""
from collections import Counter
from datetime import date
from decimal import Decimal, localcontext
import json
import re
import subprocess
import sys

import pytest

from scripts import new_bank_model as m
from scripts import new_bank_integration as d


@pytest.fixture(autouse=True)
def deny_services(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("offline generator must not access services")
    monkeypatch.setattr(m.runtime, "docker", denied)
    monkeypatch.setattr("psycopg.connect", denied)
    monkeypatch.setattr("socket.create_connection", denied)


@pytest.fixture(scope="module")
def prepared():
    return m.prepare()


@pytest.mark.parametrize("product,account,value", [
    ("CHEQUES",100000,"11203.96"), ("AHORRO",200000,"501.72"),
    ("TDC",300000,"109055.97"), ("C_PERSONAL",400000,"71644.36")])
def test_initial_reference_vectors(product, account, value):
    assert m.initial_balance(product, account, 202601) == Decimal(value)


def test_seed_contract_and_boundary_validation():
    assert m.initial_balance("AHORRO",200000,-1) == m.initial_balance("AHORRO",200000,-1)
    assert m.initial_balance("AHORRO",200000,1) != m.initial_balance("AHORRO",200000,2)
    for invalid in (True, "202601", 1.0):
        with pytest.raises(ValueError):
            m.initial_balance("AHORRO",200000,invalid)
    with pytest.raises(ValueError):
        m.initial_balance("AHORRO",100000,202601)


def test_full_volumes_and_auxiliary_separation(prepared):
    rows, manifest, timings = prepared
    assert {n:len(v) for n,v in rows.items()} == m.EXPECTED
    assert sum(len(rows[t.name]) for t in d.ORIGINAL_TABLES) == 350013
    assert len(rows[d.REF_ACCOUNT.name])+len(rows[d.REF_TXN.name]) == 20009
    assert manifest["currency"] is None


def test_full_reference_manifest_and_content_hashes(prepared):
    reference = json.loads((d.ROOT/"data/source/new_bank_model/dataset-202601.manifest.json").read_text(encoding="utf-8"))
    assert prepared[1] == reference
    assert reference["dataset_sha256"] == "a85d0c9b8818d4f5134a80f112221c57e96b1419580339f15068f4d0069b947b"


def test_client_distributions_and_preserved_anomaly(prepared):
    clients = prepared[0][d.CLIENT.name]
    assert Counter(c[3] for c in clients) == {"PF":4800,"PM":200}
    assert Counter(c[4] for c in clients) == {"HOMBRE":2496,"MUJER":2304,"NO APLICA":200}
    assert Counter(c[5] for c in clients) == {"PREMIUM":250,"PREFERENTE":1000,"MASIVO":3750}
    assert all(c[6:] == (None,)*6 for c in clients)
    assert clients[3551][1:3] == (date(2003,4,24),date(2004,10,27))


def test_all_initial_ranges_and_unique_accounts(prepared):
    rows = prepared[0]
    accounts = rows[d.REF_ACCOUNT.name]
    assert len({r[0] for r in accounts}) == 20000
    assert Counter(r[1] for r in accounts) == {n:4 for n in range(1,5001)}
    for account, client, product, opened, cohort in accounts:
        p = next(p for p in d.PRODUCT_ROWS if p[0]==product)
        assert account == p[3]+client-1
        initial = m.initial_balance(product,account,202601)
        assert Decimal(p[4]) <= initial <= Decimal(p[5])


def test_independent_full_reconciliation_and_continuity(prepared):
    rows = prepared[0]
    signs = {(p,code):sign for p,code,_,_,_,sign in d.TRANSACTION_ROWS}
    net, counts = {}, Counter()
    for account,client,p,day,month,amount,code,desc,cut,domain in rows[d.MOVEMENT.name]:
        assert isinstance(amount,Decimal) and amount > 0 and amount.as_tuple().exponent == -2
        assert day == date(2026,month%100,15) and cut//100 == month
        key = (account,p,month)
        net[key] = net.get(key,Decimal(0)) + amount*signs[p,code]
        counts[(p,month)] += 1
    previous = {}
    for account,client,p,opened,cohort,opening,closing,cut,domain in rows[d.BALANCE.name]:
        if cut == 20260131:
            assert opening == closing
            assert (account,p,202601) not in net
            assert domain == ("CAPTACION" if p in ("CHEQUES","AHORRO") else "COLOCACION")
        else:
            assert previous[account,p] == opening
            assert opening+net[account,p,cut//100] == closing
            deposit = p in ("CHEQUES","AHORRO")
            rate = Decimal("0.02" if deposit else "0.03") if cut==20260228 else Decimal("0.01" if deposit else "0.022")
            assert closing == (opening*(1+rate)).quantize(Decimal(".01"),rounding="ROUND_HALF_UP")
        previous[account,p] = closing
    assert len(net) == 100000
    assert all(n == (15000 if p=="TDC" else 10000) for (p,month),n in counts.items())


@pytest.mark.parametrize("p,month,opening,closing,expected", [
    ("CHEQUES",2,"10000.50","10200.51",{100:"700.04",200:"500.03"}),
    ("C_PERSONAL",3,"50000.50","51100.51",{300:"2500.03",450:"3600.04"}),
    ("TDC",2,"10000.50","10300.52",{300:"100.00",400:"200.01",450:"200.01"})])
def test_half_cent_financial_vectors(p,month,opening,closing,expected):
    result, amounts = m.month_amounts(p,month,Decimal(opening))
    assert result == Decimal(closing)
    assert amounts == {k:Decimal(v) for k,v in expected.items()}


def test_canonical_encoding_order_and_changes(prepared):
    rows, manifest, _ = prepared
    assert m.canonical_row((1,None,date(2026,1,1),Decimal("1.20"),True,"Crédito")) == '["1", null, "2026-01-01", "1.20", "true", "Crédito"]'
    name = d.TXN.name
    assert m.table_identity(name,rows[name]) == m.table_identity(name,tuple(reversed(rows[name])))
    with pytest.raises(ValueError,match="duplicate"):
        m.table_identity(name,rows[name]+rows[name][:1])
    for bad in (1.2, Decimal("NaN"), Decimal("1.201")):
        with pytest.raises(ValueError):
            m.canonical_row((bad,))
    identity = {k:v for k,v in manifest.items() if k!="dataset_sha256"}
    assert manifest["dataset_sha256"] == m.sha(m.compact(identity))


def test_separate_process_and_decimal_context_independence():
    code = "from scripts.new_bank_model import initial_balance; print(initial_balance('CHEQUES',100000,202601))"
    child = subprocess.run([sys.executable,"-c",code],cwd=d.ROOT,capture_output=True,text=True,check=True)
    assert Decimal(child.stdout.strip()) == m.initial_balance("CHEQUES",100000,202601)
    with localcontext() as ctx:
        ctx.prec = 6
        rows = m.generate()
    assert len(rows[d.MOVEMENT.name]) == 225000


def test_cli_requires_explicit_isolated_state():
    for command in ("inspect","load","verify"):
        with pytest.raises(SystemExit) as error:
            m.main([command])
        assert error.value.code == 2


def test_load_sql_has_no_protected_write_or_destructive_reset(prepared):
    # Pure rendering; do not execute this synthetic destination.
    sql = m.load_script({"structure_002":{}},prepared[0],prepared[1],"isolated_test")
    assert sql.startswith("BEGIN ISOLATION LEVEL READ COMMITTED;") and sql.endswith("COMMIT;\n")
    assert sql.count("\nCOMMIT;") == 1
    assert "pg_advisory_xact_lock(7262026,1)" in sql
    assert "IN SHARE ROW EXCLUSIVE MODE" in sql
    assert not any(word in sql.upper() for word in ("DROP ","TRUNCATE ","DELETE FROM ","UPDATE "))
    assert not any(name in sql for name in d.PROTECTED)
    assert "COPY pg_temp.nbm_stage_2" in sql and "INSERT INTO dim.dim_txn" in sql
    assert sql.index("COPY pg_temp.nbm_stage_6") < sql.index("\\if :do_load")
    assert "INSERT INTO bank_model_control.datasets" in sql
    assert "WHERE :'do_load'::boolean" in sql


def test_quality_sql_has_no_cent_tolerance_or_silent_missing_zero():
    sql = m.quality_sql()
    assert "closing IS DISTINCT FROM opening+net" in sql
    assert "LEFT JOIN" in sql and "generate_series(1,5000)" in sql
    assert "COALESCE" not in sql.upper()
    assert not re.search(r"\bELSE\s+0(?:\s|$)", sql, re.I)
