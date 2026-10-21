import uuid

import psycopg
import pytest
from psycopg import sql

from scripts import bank_data as bank


def pytest_addoption(parser):
    parser.addoption("--run-db-tests", action="store_true", help="Ejecuta tambien las pruebas PostgreSQL aisladas.")
    parser.addoption("--run-retrieval-tests", action="store_true", help="Prueba recuperacion real con Ollama y corpus indexado.")
    parser.addoption("--run-agent-tests", action="store_true", help="Prueba el agente con llama3.1 y el corpus existente.")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "agent" in item.keywords and not config.getoption("--run-agent-tests"):
            item.add_marker(pytest.mark.skip(reason="Usa --run-agent-tests con llama3.1, PostgreSQL y corpus preparado."))
        if "retrieval" in item.keywords and not config.getoption("--run-retrieval-tests"):
            item.add_marker(pytest.mark.skip(reason="Usa --run-retrieval-tests con Ollama y corpus indexado."))
    if not config.getoption("--run-db-tests"):
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Usa --run-db-tests para probar PostgreSQL."))


@pytest.fixture(scope="session")
def metadata():
    return bank.load_metadata()


@pytest.fixture(scope="session")
def dataset(metadata):
    return bank.generate(metadata)


@pytest.fixture(scope="module")
def database(metadata, dataset):
    """No toca public: todo el esquema y sus filas desaparecen por ROLLBACK."""
    schema = "bank_test_" + uuid.uuid4().hex
    with psycopg.connect(**bank.settings()) as conn:
        try:
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SET LOCAL statement_timeout = '120s'")
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            bank.migrate(conn, metadata, schema)
            bank.populate(conn, dataset, metadata, schema)
            yield conn, schema
        finally:
            conn.rollback()


@pytest.fixture
def isolated_database(database):
    conn, schema = database
    with conn.transaction(force_rollback=True):
        yield conn, schema
