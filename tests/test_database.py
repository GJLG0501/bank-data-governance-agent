import psycopg
import pytest
from psycopg import sql

from scripts import bank_data as bank

pytestmark = pytest.mark.integration


def test_migration_is_idempotent_and_preserves_rows(isolated_database, metadata, dataset):
    conn, schema = isolated_database
    bank.migrate(conn, metadata, schema)
    bank.migrate(conn, metadata, schema)
    assert bank.fetch_data(conn, metadata, schema) == dataset


def test_counts_relations_and_reproducibility_in_postgres(isolated_database, metadata, dataset):
    conn, schema = isolated_database
    actual = bank.fetch_data(conn, metadata, schema)
    bank.validate_data(actual, metadata)
    assert actual == dataset
    report = bank.verify(conn, metadata, schema=schema)
    assert report["counts"] == bank.COUNTS
    assert report["sha256"] == bank.fingerprint(dataset)


def test_repeat_population_is_a_noop(isolated_database, metadata, dataset):
    conn, schema = isolated_database
    assert bank.populate(conn, dataset, metadata, schema) == "sin cambios"
    assert bank.populate(conn, dataset, metadata, schema) == "sin cambios"
    assert bank.fetch_data(conn, metadata, schema) == dataset


def test_different_seed_is_refused_without_changing_data(isolated_database, metadata, dataset):
    conn, schema = isolated_database
    with pytest.raises(ValueError, match="datos existentes"):
        bank.populate(conn, bank.generate(metadata, bank.SEED + 1), metadata, schema)
    assert bank.fetch_data(conn, metadata, schema) == dataset


def test_conflicting_existing_row_is_preserved(isolated_database, metadata, dataset):
    conn, schema = isolated_database
    conn.execute(sql.SQL('INSERT INTO {} VALUES (%s, %s, %s, %s)').format(sql.Identifier(schema, "CUSTOMER")),
                 ("EXISTING-ROW", "MASS", "LOW", 100000.0))
    before = bank.fetch_data(conn, metadata, schema)
    with pytest.raises(ValueError, match="datos existentes"):
        bank.populate(conn, dataset, metadata, schema)
    assert bank.fetch_data(conn, metadata, schema) == before


@pytest.mark.parametrize("table,field,value,error", [
    ("CUSTOMER", "customer_id", "SYN-C-000002", psycopg.errors.UniqueViolation),
    ("CUSTOMER", "segment", "UNKNOWN", psycopg.errors.CheckViolation),
    ("CUSTOMER", "risk_level", "UNKNOWN", psycopg.errors.CheckViolation),
    ("CUSTOMER", "annual_income", None, psycopg.errors.NotNullViolation),
    ("CUSTOMER", "annual_income", float("nan"), psycopg.errors.CheckViolation),
    ("CUSTOMER", "annual_income", float("inf"), psycopg.errors.CheckViolation),
    ("CUSTOMER", "annual_income", 0.0, psycopg.errors.CheckViolation),
    ("TRANSACTION", "customer_id", "MISSING", psycopg.errors.ForeignKeyViolation),
    ("TRANSACTION", "channel", "UNKNOWN", psycopg.errors.CheckViolation),
    ("TRANSACTION", "amount", -1.0, psycopg.errors.CheckViolation),
    ("TRANSACTION", "merchant_category", " ", psycopg.errors.CheckViolation),
    ("LOAN", "customer_id", "MISSING", psycopg.errors.ForeignKeyViolation),
    ("LOAN", "balance", 3000001.0, psycopg.errors.CheckViolation),
    ("LOAN", "interest_rate", 61.0, psycopg.errors.CheckViolation),
    ("LOAN", "dpd", -1, psycopg.errors.CheckViolation),
    ("LOAN", "dpd", 366, psycopg.errors.CheckViolation),
    ("LOAN", "dpd", "not-an-integer", psycopg.errors.InvalidTextRepresentation),
])
def test_database_enforces_constraints(isolated_database, table, field, value, error):
    conn, schema = isolated_database
    query = sql.SQL("UPDATE {} SET {} = %s WHERE {} = %s").format(
        sql.Identifier(schema, table), sql.Identifier(field), sql.Identifier(bank.KEYS[table]))
    prefix = {"CUSTOMER": "C", "TRANSACTION": "T", "LOAN": "L"}[table]
    with pytest.raises(error), conn.transaction():
        conn.execute(query, (value, f"SYN-{prefix}-000001"))


def test_partial_load_is_refused(isolated_database, metadata, dataset):
    conn, _ = isolated_database
    schema = "bank_partial_case"
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    bank.migrate(conn, metadata, schema)
    first = dataset["CUSTOMER"][0]
    conn.execute(sql.SQL('INSERT INTO {} VALUES (%s, %s, %s, %s)').format(sql.Identifier(schema, "CUSTOMER")),
                 tuple(first.values()))
    with pytest.raises(ValueError, match="carga parcial"):
        bank.populate(conn, dataset, metadata, schema)
    assert len(bank.fetch_data(conn, metadata, schema)["CUSTOMER"]) == 1


def test_schema_drift_is_refused(isolated_database, metadata):
    conn, schema = isolated_database
    # Agregar una columna solamente dentro del esquema de prueba no confirmado.
    conn.execute(sql.SQL('ALTER TABLE {} ADD COLUMN unexpected TEXT').format(sql.Identifier(schema, "CUSTOMER")))
    with pytest.raises(ValueError, match="Esquema incompatible"):
        bank.migrate(conn, metadata, schema)


def test_failed_load_rolls_back_all_insertions(isolated_database, metadata, dataset):
    conn, _ = isolated_database
    schema = "bank_atomic_case"
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    bank.migrate(conn, metadata, schema)
    # Una regla adicional obliga a fallar despues de insertar los clientes.
    # Las restricciones del modelo siguen iguales; el trigger simula un fallo de escritura.
    conn.execute(sql.SQL('CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION \'test failure\'; END $$').format(sql.Identifier(schema, "fail_insert")))
    conn.execute(sql.SQL('CREATE TRIGGER fail_insert BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION {}()').format(
        sql.Identifier(schema, "TRANSACTION"), sql.Identifier(schema, "fail_insert")))
    with pytest.raises(psycopg.Error), conn.transaction():
        bank.populate(conn, dataset, metadata, schema)
    assert bank.fetch_data(conn, metadata, schema) == {table: [] for table in bank.COUNTS}
