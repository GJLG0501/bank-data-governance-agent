import copy
import random

import pytest

from scripts import bank_data as bank


@pytest.mark.parametrize("table,count", bank.COUNTS.items())
def test_counts_and_keys(dataset, table, count):
    rows = dataset[table]
    assert len(rows) == count
    assert len({row[bank.KEYS[table]] for row in rows}) == count


def test_catalog_fields_categories_and_relations(metadata, dataset):
    bank.validate_data(dataset, metadata)
    customers = {row["customer_id"] for row in dataset["CUSTOMER"]}
    for table, rows in dataset.items():
        fields = metadata["tables"][table]["fields"]
        for row in rows:
            assert set(row) == set(fields)
            for name, spec in fields.items():
                if "allowed_values" in spec:
                    assert row[name] in spec["allowed_values"]
                if "foreign_key" in spec:
                    assert row[name] in customers
    assert all(sum(t["customer_id"] == customer for t in dataset["TRANSACTION"]) == 5 for customer in customers)
    assert len({row["customer_id"] for row in dataset["LOAN"]}) == 500


def test_reproducibility(metadata, dataset):
    assert dataset == bank.generate(metadata, bank.SEED)
    assert bank.fingerprint(dataset) == bank.fingerprint(bank.generate(metadata, bank.SEED))
    assert bank.fingerprint(dataset) != bank.fingerprint(bank.generate(metadata, bank.SEED + 1))


def test_default_dataset_regression_fingerprint(dataset):
    # Detecta cambios involuntarios de algoritmo, orden o supuestos entre equipos.
    assert bank.fingerprint(dataset) == "30fc34ef604fed893478ad4322c5b16d38cacc703b8eca592e696578f859eff5"


def test_generator_does_not_modify_global_random_state(metadata):
    before = random.getstate()
    bank.generate(metadata)
    assert random.getstate() == before


def test_sql_is_derived_from_metadata(metadata):
    assert bank.MIGRATION_PATH.read_text(encoding="utf-8") == bank.build_migration(metadata)
    ddl = bank.build_migration(metadata)
    assert "vector" not in ddl.split("CREATE TABLE", 1)[1]
    assert "DROP " not in ddl and "TRUNCATE " not in ddl and "DELETE " not in ddl.replace("ON DELETE RESTRICT", "")


@pytest.mark.parametrize("table,field,value", [
    ("CUSTOMER", "customer_id", ""),
    ("CUSTOMER", "segment", "UNKNOWN"),
    ("CUSTOMER", "risk_level", "CRITICAL"),
    ("CUSTOMER", "annual_income", None),
    ("CUSTOMER", "annual_income", float("nan")),
    ("CUSTOMER", "annual_income", float("inf")),
    ("CUSTOMER", "annual_income", 0.0),
    ("TRANSACTION", "channel", "UNKNOWN"),
    ("TRANSACTION", "customer_id", "SYN-C-MISSING"),
    ("TRANSACTION", "amount", -1.0),
    ("TRANSACTION", "amount", "100"),
    ("LOAN", "customer_id", "SYN-C-MISSING"),
    ("LOAN", "balance", 3000001.0),
    ("LOAN", "interest_rate", 61.0),
    ("LOAN", "dpd", -1),
    ("LOAN", "dpd", 366),
    ("LOAN", "dpd", True),
    ("LOAN", "dpd", 1.5),
])
def test_invalid_data_is_rejected(metadata, dataset, table, field, value):
    broken = copy.deepcopy(dataset)
    broken[table][0][field] = value
    with pytest.raises(ValueError):
        bank.validate_data(broken, metadata)


def test_duplicate_and_missing_rows_are_rejected(metadata, dataset):
    broken = copy.deepcopy(dataset)
    broken["CUSTOMER"][1]["customer_id"] = broken["CUSTOMER"][0]["customer_id"]
    with pytest.raises(ValueError, match="duplicada"):
        bank.validate_data(broken, metadata)
    broken = copy.deepcopy(dataset)
    broken["LOAN"].pop()
    with pytest.raises(ValueError, match="Cantidad"):
        bank.validate_data(broken, metadata)


@pytest.mark.parametrize("reset,confirmation", [(True, None), (True, "another_database"), (False, "local_db")])
def test_reset_requires_explicit_matching_confirmation(reset, confirmation):
    with pytest.raises(ValueError):
        bank.authorize_reset(reset, confirmation, "local_db")


def test_reset_authorization_is_scoped_to_database():
    bank.authorize_reset(False, None, "local_db")
    bank.authorize_reset(True, "local_db", "local_db")
