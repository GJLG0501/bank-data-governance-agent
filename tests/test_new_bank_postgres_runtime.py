"""Real PostgreSQL tests: opt-in, separate from legacy DB fixtures.

Set BANK_VALIDATION_STATE to the ignored manifest created by the explicit harness.
No active database write, reset, cleanup or full data generation is available.
"""

import hashlib
import json
import os
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

import pytest

from scripts import new_bank_integration as design
from scripts import new_bank_runtime_validation as runtime

MODEL_SQL = """
WITH tables AS (
 SELECT c.oid,n.nspname||'.'||c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('dim','cfg') AND c.relkind='r'
)
SELECT jsonb_build_object(
 'tables',(SELECT jsonb_agg(name ORDER BY name) FROM tables),
 'columns',(SELECT jsonb_agg(jsonb_build_array(t.name,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
   pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated) ORDER BY t.name,a.attnum)
   FROM tables t JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped
   LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum),
 'constraints',(SELECT jsonb_agg(jsonb_build_array(t.name,k.conname,k.contype,pg_get_constraintdef(k.oid,FALSE),k.convalidated)
   ORDER BY t.name,k.conname) FROM tables t JOIN pg_constraint k ON k.conrelid=t.oid),
 'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))
   FROM tables t JOIN pg_index i ON i.indrelid=t.oid),
 'owners',(SELECT jsonb_agg(DISTINCT pg_get_userbyid(c.relowner)) FROM tables t JOIN pg_class c ON c.oid=t.oid)
);"""

# Small disposable fixtures only. All these inserts live inside rolled-back
# transactions; no 350,013-row dataset or seed generator is invoked.
FIXTURE = """
INSERT INTO dim.dim_cliente(num_cte) VALUES (1),(2);
INSERT INTO dim.dim_producto(cve_producto,cve_dominio,grupo_producto,cve_subproducto,descripcion)
VALUES ('CHEQUES','DEPOSITS','CAPTACION','CHEQUES','Cuenta de Cheques'),
       ('TDC','TDC','COLOCACION','TDC','Tarjeta de Crédito');
INSERT INTO cfg.ref_txn_modelo VALUES
 ('CHEQUES',100,'DEPOSITO','DEPOSITS','CAPTACION',1,'1.0.0'),
 ('CHEQUES',200,'RETIRO','DEPOSITS','CAPTACION',-1,'1.0.0'),
 ('TDC',300,'PAGOS','TDC','COLOCACION',-1,'1.0.0'),
 ('TDC',400,'COMPRAS','TDC','COLOCACION',1,'1.0.0'),
 ('TDC',450,'DISPOSICIONES','TDC','COLOCACION',1,'1.0.0');
INSERT INTO cfg.ref_cuenta_modelo VALUES
 (100000,1,'CHEQUES','2026-01-01',202601),(300000,1,'TDC','2026-01-01',202601);
INSERT INTO cfg.fact_sdos_captacoloca_m VALUES
 (100000,1,'CHEQUES','2026-01-01',202601,10000,10000,20260131,'CAPTACION'),
 (100000,1,'CHEQUES','2026-01-01',202601,10000,10200,20260228,'DEPOSITS');
INSERT INTO cfg.fact_txn_captacoloca_d VALUES
 (100000,1,'CHEQUES','2026-02-15',202602,700,100,'DEPOSITO',20260228,'DEPOSITS'),
 (100000,1,'CHEQUES','2026-02-15',202602,500,200,'RETIRO',20260228,'DEPOSITS');
"""


@pytest.fixture(scope="module")
def restored_run():
    source = os.environ.get("BANK_VALIDATION_STATE")
    if not source:
        pytest.skip("Explicit BANK_VALIDATION_STATE required; never use the legacy database fixture")
    path, state = runtime.load_state(source)
    assert state["status"] in ("restored_verified", "runtime_verified")
    runtime.isolated_guard(state)
    state["_path"] = str(path)
    return state


def persist(state):
    runtime.save(Path(state["_path"]), {k:v for k,v in state.items() if not k.startswith("_")})


def execute(state, sql, *, database=None, check=True):
    return runtime.psql(state["container"], database or state["database"], sql,
                        readonly=False, state=state, check=check)


@pytest.fixture(scope="module")
def migrated(restored_run):
    state = restored_run
    state["migrations"] = []
    for index, relative in enumerate(design.manifest()["migrations"], 1):
        path = runtime.ROOT / relative
        result = execute(state, path.read_text(encoding="utf-8"), check=False)
        state["migrations"].append({"file":relative,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                                    "exit_code":result.returncode,"stderr":result.stderr})
        persist(state)
        assert result.returncode == 0, result.stderr
        # Retain the first raw-001 and strengthened-002 profiles as evidence;
        # subsequent runs exercise safe repetition on the same isolated model.
        state.setdefault(f"structure_{index:03}", runtime.query(state, MODEL_SQL))
    persist(state)
    yield state
    runtime.save(Path(state["_path"]).parent / "isolated-final-structure.json", runtime.query(state, MODEL_SQL))


def test_backup_and_real_restoration(restored_run):
    state = restored_run
    directory = Path(state["_path"]).parent
    backup = Path(state["backup"]["path"])
    assert backup.stat().st_size == state["backup"]["bytes"] > 0
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == state["backup"]["sha256"]
    before = json.loads((directory/"legacy-before.json").read_text(encoding="utf-8"))
    restored = json.loads((directory/"legacy-restored.json").read_text(encoding="utf-8"))
    assert before["protected"] == restored["protected"]
    assert runtime.historical_fingerprints(state) == state["historical_fingerprints"]


def test_container_storage_and_network_are_isolated(restored_run):
    runtime.isolated_guard(restored_run)
    assert restored_run["container_id"] != runtime.ACTIVE_ID
    assert runtime.inspect("Image", restored_run["container"]) == restored_run["source"]["image_id"]


def test_001_creates_the_five_tables_and_original_42_columns(migrated):
    signature = migrated["structure_001"]
    assert set(signature["tables"]) == {t.name for t in design.ORIGINAL_TABLES}
    assert len(signature["columns"]) == 42
    for table in design.ORIGINAL_TABLES:
        actual = [c for c in signature["columns"] if c[0] == table.name]
        assert [c[1] for c in actual] == [name for name,_ in table.columns]
        for column, (_, definition) in zip(actual,table.columns):
            expected_type = definition.split(" NOT NULL")[0].split(" DEFAULT")[0].lower().replace("varchar", "character varying")
            assert column[2] == expected_type
            assert column[3] == ("NOT NULL" in definition)
    assert len(signature["constraints"]) == 5


def test_002_adds_expected_keys_checks_indexes_and_foreign_keys(migrated):
    signature = migrated["structure_002"]
    assert set(signature["tables"]) == {t.name for t in design.INTEGRITY_ORDER}
    assert len(signature["columns"]) == 54
    counts = {kind:sum(c[2]==kind for c in signature["constraints"]) for kind in ('p','u','c','f')}
    assert counts == {'p':4,'u':5,'c':18,'f':6}
    assert len(signature["indexes"]) == 9
    assert all(c[4] for c in signature["constraints"])
    assert signature["owners"] == [runtime.ROLE]
    for t in (design.BALANCE,design.MOVEMENT):
        assert all(c[3] for c in signature["columns"] if c[0]==t.name)
    assert not [c for c in signature["constraints"] if c[0]=='dim.dim_txn']


def test_safe_repetition_preserves_structure_and_legacy(migrated):
    before = runtime.query(migrated,MODEL_SQL)
    for relative in design.manifest()["migrations"]:
        execute(migrated,(runtime.ROOT/relative).read_text(encoding="utf-8"))
    assert runtime.query(migrated,MODEL_SQL) == before
    baseline = json.loads((Path(migrated["_path"]).parent/"legacy-before.json").read_text(encoding="utf-8"))
    assert runtime.snapshot(migrated)["protected"] == baseline["protected"]


def test_valid_financial_fixture_null_dimensions_and_original_anomaly(migrated):
    sql = """
    INSERT INTO dim.dim_cliente(num_cte,fec_alta,fec_nac,tipo_persona,genero_cte)
    VALUES(3552,'2003-04-24','2004-10-27','PF','HOMBRE');
    INSERT INTO dim.dim_producto VALUES('AHORRO','DEPOSITS','CAPTACION','AHORRO','Cuenta de Ahorro',NULL);
    INSERT INTO dim.dim_txn VALUES ('CHEQUES','DEPOSITS','CAPTACION',100,'DEPOSITO'),('CHEQUES','DEPOSITS','CAPTACION',100,'DEPOSITO');
    SELECT jsonb_build_object(
      'closed_balance',(SELECT saldo_mes FROM cfg.fact_sdos_captacoloca_m WHERE fec_informacion=20260228),
      'signed_net',(SELECT SUM(t.saldo_txn*r.signo_economico) FROM cfg.fact_txn_captacoloca_d t
           JOIN cfg.ref_txn_modelo r USING(cve_producto,cve_txn)),
      'raw_duplicates',(SELECT COUNT(*) FROM dim.dim_txn),
      'client_nulls',(SELECT giro_empresa IS NULL AND cve_territorio IS NULL AND cve_dir IS NULL
            AND cve_subdir IS NULL AND cve_sucursal IS NULL AND cve_promotor IS NULL FROM dim.dim_cliente WHERE num_cte=1));
    """
    result = execute(migrated,"BEGIN;\n"+FIXTURE+sql+"\nROLLBACK;")
    assert json.loads(result.stdout) == {'closed_balance':10200,'signed_net':200,'raw_duplicates':2,'client_nulls':True}


@pytest.mark.parametrize('product,initial', [('CHEQUES','10000'),('AHORRO','100'),('C_PERSONAL','60000'),('TDC','10000')])
def test_four_product_fixtures_reconcile_february_and_march(migrated,product,initial):
    p=next(p for p in design.PRODUCT_ROWS if p[0]==product)
    account=p[3]
    q=lambda value: str(Decimal(value).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
    statements=["INSERT INTO dim.dim_cliente(num_cte) VALUES(1);",
        f"INSERT INTO dim.dim_producto VALUES('{product}','{p[1]}','{p[2]}','{product}','TEST',TRUE);",
        f"INSERT INTO cfg.ref_cuenta_modelo VALUES({account},1,'{product}','2026-01-01',202601);"]
    for row in design.TRANSACTION_ROWS:
        if row[0]==product:
            statements.append('INSERT INTO cfg.ref_txn_modelo VALUES('+','.join(map(design.literal,row))+",'1.0.0');")
    previous=Decimal(initial)
    statements.append(f"INSERT INTO cfg.fact_sdos_captacoloca_m VALUES({account},1,'{product}','2026-01-01',202601,{previous},{previous},20260131,'{p[2]}');")
    for month,cut in ((202602,20260228),(202603,20260331)):
        deposits=product in ('CHEQUES','AHORRO')
        rate=Decimal('0.02' if deposits else '0.03') if month==202602 else Decimal('0.01' if deposits else '0.022')
        close=Decimal(q(previous*(1+rate)))
        increment=close-previous
        if product=='TDC':
            purchases=Decimal(q(previous*Decimal('0.02')))
            amounts={400:purchases,450:purchases,300:purchases*2-increment}
        else:
            payment=Decimal(q(previous*Decimal('0.05')))
            amounts={100:payment+increment,200:payment} if deposits else {450:payment+increment,300:payment}
        for code,amount in amounts.items():
            description=next(r[2] for r in design.TRANSACTION_ROWS if r[0]==product and r[1]==code)
            date=f'{month//100}-{month%100:02}-15'
            statements.append(f"INSERT INTO cfg.fact_txn_captacoloca_d VALUES({account},1,'{product}','{date}',{month},{q(amount)},{code},'{description}',{cut},'{p[1]}');")
        statements.append(f"INSERT INTO cfg.fact_sdos_captacoloca_m VALUES({account},1,'{product}','2026-01-01',202601,{previous},{close},{cut},'{p[1]}');")
        previous=close
    verification="""SELECT jsonb_build_object('months',COUNT(*),'differences',COUNT(*) FILTER (
       WHERE s.saldo_mes <> s.saldo_apertura + m.net)) FROM cfg.fact_sdos_captacoloca_m s JOIN
       (SELECT t.cve_mes_txn,SUM(t.saldo_txn*r.signo_economico) AS net FROM cfg.fact_txn_captacoloca_d t
        JOIN cfg.ref_txn_modelo r USING(cve_producto,cve_txn) GROUP BY t.cve_mes_txn) m
       ON m.cve_mes_txn=s.fec_informacion/100;"""
    result=execute(migrated,'BEGIN;\n'+'\n'.join(statements)+verification+'\nROLLBACK;')
    assert json.loads(result.stdout)=={'months':2,'differences':0}


@pytest.mark.parametrize("table,column", [(t.name,n) for t in (design.BALANCE,design.MOVEMENT) for n,_ in t.columns])
def test_not_null_in_all_19_fact_columns(migrated,table,column):
    result = execute(migrated,"BEGIN;\n"+FIXTURE+f"UPDATE {table} SET {column}=NULL;\nROLLBACK;",check=False)
    assert result.returncode != 0 and '23502' in result.stderr, result.stderr


@pytest.mark.parametrize("statement", [
    "INSERT INTO dim.dim_cliente(num_cte) VALUES(1)",
    "INSERT INTO dim.dim_producto SELECT * FROM dim.dim_producto WHERE cve_producto='CHEQUES'",
    "INSERT INTO cfg.ref_txn_modelo SELECT * FROM cfg.ref_txn_modelo WHERE cve_producto='CHEQUES' AND cve_txn=100",
    "INSERT INTO cfg.ref_cuenta_modelo SELECT * FROM cfg.ref_cuenta_modelo WHERE num_cta=100000",
    "INSERT INTO cfg.ref_cuenta_modelo VALUES(100001,1,'CHEQUES','2026-01-01',202601)",
    "INSERT INTO cfg.fact_sdos_captacoloca_m SELECT * FROM cfg.fact_sdos_captacoloca_m WHERE fec_informacion=20260131",
    "INSERT INTO cfg.fact_txn_captacoloca_d SELECT * FROM cfg.fact_txn_captacoloca_d WHERE cve_txn=100",
])
def test_duplicate_keys_are_rejected(migrated,statement):
    result=execute(migrated,"BEGIN;\n"+FIXTURE+statement+";\nROLLBACK;",check=False)
    assert result.returncode != 0 and '23505' in result.stderr, result.stderr


@pytest.mark.parametrize("statement", [
    "INSERT INTO cfg.ref_txn_modelo VALUES('AHORRO',100,'DEPOSITO','DEPOSITS','CAPTACION',1,'1.0.0')",
    "INSERT INTO cfg.ref_cuenta_modelo VALUES(100001,999,'CHEQUES','2026-01-01',202601)",
    "INSERT INTO cfg.ref_cuenta_modelo VALUES(200000,2,'AHORRO','2026-01-01',202601)",
    "UPDATE cfg.fact_sdos_captacoloca_m SET num_cte=2",
    "UPDATE cfg.fact_txn_captacoloca_d SET num_cte=2",
    "UPDATE cfg.fact_txn_captacoloca_d SET cve_txn=777,desc_txn='UNKNOWN' WHERE cve_txn=100",
])
def test_foreign_keys_reject_orphans_and_wrong_owners(migrated,statement):
    result=execute(migrated,"BEGIN;\n"+FIXTURE+statement+";\nROLLBACK;",check=False)
    assert result.returncode != 0 and '23503' in result.stderr, result.stderr


@pytest.mark.parametrize("statement", [
    "UPDATE cfg.fact_txn_captacoloca_d SET fec_txn='2026-02-14'",
    "UPDATE cfg.fact_txn_captacoloca_d SET fec_txn='2026-03-15'",
    "UPDATE cfg.fact_txn_captacoloca_d SET fec_informacion=20260230",
    "UPDATE cfg.fact_txn_captacoloca_d SET saldo_txn=0",
    "UPDATE cfg.fact_txn_captacoloca_d SET saldo_txn=-1",
    "UPDATE cfg.fact_txn_captacoloca_d SET saldo_txn='NaN'::NUMERIC",
    "UPDATE cfg.fact_sdos_captacoloca_m SET saldo_apertura=7000,saldo_mes=7000 WHERE fec_informacion=20260131",
    "UPDATE cfg.fact_sdos_captacoloca_m SET saldo_mes=10200.01 WHERE fec_informacion=20260228",
    "UPDATE cfg.fact_sdos_captacoloca_m SET dominio='DEPOSITS' WHERE fec_informacion=20260131",
    "UPDATE cfg.fact_sdos_captacoloca_m SET dominio='CAPTACION' WHERE fec_informacion=20260228",
    "UPDATE cfg.fact_sdos_captacoloca_m SET cve_mes_alta=202602",
    "UPDATE cfg.fact_sdos_captacoloca_m SET saldo_apertura='NaN'::NUMERIC",
    "UPDATE cfg.ref_txn_modelo SET signo_economico=-1 WHERE cve_producto='CHEQUES' AND cve_txn=100",
    "INSERT INTO cfg.ref_cuenta_modelo VALUES(200001,2,'CHEQUES','2026-01-01',202601)",
])
def test_financial_temporal_domain_and_catalog_checks(migrated,statement):
    result=execute(migrated,"BEGIN;\n"+FIXTURE+statement+";\nROLLBACK;",check=False)
    assert result.returncode != 0 and '23514' in result.stderr, result.stderr


@pytest.mark.parametrize("label,setup,stage,error", [
    ('wrong_type',"CREATE SCHEMA dim; CREATE TABLE dim.dim_cliente(num_cte TEXT PRIMARY KEY);",1,'Incompatible columns'),
    ('missing_pk',"CREATE SCHEMA dim; CREATE TABLE dim.dim_cliente("+design.table_body(design.CLIENT).replace(',\n    PRIMARY KEY (num_cte)','')+");",1,'constraints'),
    ('rogue_index',"CREATE UNIQUE INDEX unexpected ON dim.dim_txn(cve_producto,cve_txn);",1,'indexes'),
    ('unvalidated',"ALTER TABLE dim.dim_cliente ADD CONSTRAINT unexpected CHECK(num_cte>0) NOT VALID;",1,'constraints'),
    ('nonempty_base',"INSERT INTO cfg.fact_sdos_captacoloca_m(num_cta) VALUES(100000);",2,'nonempty table'),
    ('wrong_owner',"ALTER SCHEMA dim OWNER TO pg_database_owner;",1,'owned'),
    ('missing_base','',2,'Missing schema'),
])
def test_migrations_refuse_incompatible_objects_atomically(migrated,label,setup,stage,error):
    database=runtime.case_database(migrated,label)
    persist(migrated)
    def q(sql):
        return json.loads(runtime.psql(migrated['container'],database,'BEGIN READ ONLY;\n'+sql+'\nCOMMIT;').stdout)
    first=(runtime.ROOT/design.manifest()['migrations'][0]).read_text(encoding='utf-8')
    if label not in ('wrong_type','missing_pk','missing_base'):
        execute(migrated,first,database=database)
    if setup:
        execute(migrated,setup,database=database)
    before=q(MODEL_SQL)
    script=(runtime.ROOT/design.manifest()['migrations'][stage-1]).read_text(encoding='utf-8')
    result=execute(migrated,script,database=database,check=False)
    assert result.returncode != 0 and 'P0001' in result.stderr and error in result.stderr,result.stderr
    assert q(MODEL_SQL)==before
    if label=='nonempty_base':
        assert q('SELECT COUNT(*) FROM cfg.fact_sdos_captacoloca_m;')==1
        assert q("SELECT to_jsonb(to_regclass('cfg.ref_txn_modelo') IS NULL);") is True


def test_guard_refuses_any_write_target_on_active_database(migrated):
    with pytest.raises(RuntimeError,match='destination mismatch'):
        runtime.psql(runtime.ACTIVE,runtime.ACTIVE_DB,'SELECT 1;',readonly=False,state=migrated)


def test_final_empty_model_legacy_and_active_preservation(migrated):
    counts=runtime.query(migrated,'SELECT jsonb_build_object('+','.join(
        f"'{t.name}',(SELECT COUNT(*) FROM {t.name})" for t in design.INTEGRITY_ORDER)+');')
    assert all(v==0 for v in counts.values())
    runtime.finish(migrated['_path'])
    migrated.update(runtime.load_state(migrated['_path'])[1])
    migrated['status']='runtime_verified'
    migrated['new_model_rows']=counts
    persist(migrated)
