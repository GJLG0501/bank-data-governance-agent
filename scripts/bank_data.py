"""DDL y datos de ejercicio derivados del catalogo; nunca usar datos reales."""

import argparse
import hashlib
import json
import math
import os
import random
import sys
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "data/source/bank_metadata.json"
MIGRATION_PATH = ROOT / "sql/001-create-bank-tables.sql"
SEED = 20261020
COUNTS = {"CUSTOMER": 1000, "TRANSACTION": 5000, "LOAN": 500}
KEYS = {"CUSTOMER": "customer_id", "TRANSACTION": "transaction_id", "LOAN": "loan_id"}
FIELDS = {
    "CUSTOMER": {"customer_id": "STRING", "segment": "STRING", "risk_level": "STRING", "annual_income": "FLOAT"},
    "TRANSACTION": {"transaction_id": "STRING", "customer_id": "STRING", "amount": "FLOAT", "channel": "STRING", "merchant_category": "STRING"},
    "LOAN": {"loan_id": "STRING", "customer_id": "STRING", "balance": "FLOAT", "interest_rate": "FLOAT", "dpd": "INTEGER"},
}
SQL_TYPES = {"STRING": "TEXT", "FLOAT": "DOUBLE PRECISION", "INTEGER": "INTEGER"}
# Supuestos didacticos, no politicas bancarias. Ver docs/synthetic-data.md.
RANGES = {
    ("CUSTOMER", "annual_income"): (60000, 12000000),
    ("TRANSACTION", "amount"): (10, 250000),
    ("LOAN", "balance"): (1000, 3000000),
    ("LOAN", "interest_rate"): (5, 60),
    ("LOAN", "dpd"): (0, 365),
}
INCOME = {"MASS": (60000, 600000), "PREMIER": (600000, 3000000), "PRIVATE": (3000000, 12000000)}
RATE = {"LOW": (5, 15), "MEDIUM": (15, 30), "HIGH": (30, 60)}
DPD = {"LOW": 30, "MEDIUM": 90, "HIGH": 365}
MERCHANTS = ("SYNTHETIC_GROCERIES", "SYNTHETIC_TRANSPORT", "SYNTHETIC_UTILITIES", "SYNTHETIC_EDUCATION", "SYNTHETIC_HEALTH", "SYNTHETIC_OTHER")


def load_metadata(path=METADATA_PATH):
    metadata = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    tables = metadata.get("tables", {})
    if set(tables) != set(FIELDS):
        raise ValueError("El catalogo debe definir exactamente CUSTOMER, TRANSACTION y LOAN.")
    for table, expected in FIELDS.items():
        fields = tables[table]["fields"]
        if {name: spec["type"] for name, spec in fields.items()} != expected:
            raise ValueError(f"Campos o tipos nuevos en {table}: actualiza explicitamente el generador.")
        for name, spec in fields.items():
            allowed = spec.get("allowed_values")
            if allowed is not None and (
                not allowed or any(type(v) is not str for v in allowed) or len(set(allowed)) != len(allowed)
            ):
                raise ValueError(f"Categorias invalidas en {table}.{name}.")
            reference = spec.get("foreign_key")
            expected_fk = "CUSTOMER.customer_id" if name == "customer_id" and table != "CUSTOMER" else None
            if reference != expected_fk:
                raise ValueError(f"Relacion inesperada en {table}.{name}.")
    customer = tables["CUSTOMER"]["fields"]
    if set(customer["segment"].get("allowed_values", [])) != set(INCOME):
        raise ValueError("Actualiza los supuestos de ingreso para los segmentos del catalogo.")
    if set(customer["risk_level"].get("allowed_values", [])) != set(RATE):
        raise ValueError("Actualiza los supuestos para los niveles de riesgo del catalogo.")
    if not tables["TRANSACTION"]["fields"]["channel"].get("allowed_values"):
        raise ValueError("El catalogo debe definir los canales permitidos.")
    return metadata


def build_migration(metadata):
    """El SQL guardado debe coincidir con el catalogo y los supuestos actuales."""
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    statements = [
        "-- Generado por scripts.bank_data; no editar a mano.",
        f"-- SHA256 del catalogo normalizado: {digest}",
        "-- Supuestos educativos: docs/synthetic-data.md. No modifica vector.",
    ]
    for table in COUNTS:
        fields = metadata["tables"][table]["fields"]
        definitions = []
        for name, spec in fields.items():
            definitions.append(f'    "{name}" {SQL_TYPES[spec["type"]]} NOT NULL')
        definitions.append(f'    CONSTRAINT "{table.lower()}_pk" PRIMARY KEY ("{KEYS[table]}")')
        for name, spec in fields.items():
            prefix = f"{table.lower()}_{name}"
            if spec["type"] == "STRING":
                definitions.append(f'    CONSTRAINT "{prefix}_nonempty" CHECK (length(btrim("{name}")) > 0)')
            if "allowed_values" in spec:
                values = ", ".join("'" + v.replace("'", "''") + "'" for v in spec["allowed_values"])
                definitions.append(f'    CONSTRAINT "{prefix}_allowed" CHECK ("{name}" IN ({values}))')
            if (table, name) in RANGES:
                lower, upper = RANGES[table, name]
                definitions.append(f'    CONSTRAINT "{prefix}_range" CHECK ("{name}" >= {lower} AND "{name}" <= {upper})')
            if "foreign_key" in spec:
                target, column = spec["foreign_key"].split(".")
                definitions.append(f'    CONSTRAINT "{prefix}_fk" FOREIGN KEY ("{name}") REFERENCES "{target}" ("{column}") ON DELETE RESTRICT')
        statements.append(f'CREATE TABLE IF NOT EXISTS "{table}" (\n' + ",\n".join(definitions) + "\n);")
    return "\n\n".join(statements) + "\n"


def generate(metadata, seed=SEED):
    rng = random.Random(seed)
    categories = metadata["tables"]
    segments = categories["CUSTOMER"]["fields"]["segment"]["allowed_values"]
    risks = categories["CUSTOMER"]["fields"]["risk_level"]["allowed_values"]
    channels = categories["TRANSACTION"]["fields"]["channel"]["allowed_values"]
    data = {table: [] for table in COUNTS}

    def money(lower, upper):
        return rng.randint(round(lower * 100), round(upper * 100)) / 100

    for i in range(COUNTS["CUSTOMER"]):
        segment = rng.choice(segments)
        data["CUSTOMER"].append({
            "customer_id": f"SYN-C-{i + 1:06d}",
            "segment": segment,
            "risk_level": rng.choice(risks),
            "annual_income": money(*INCOME[segment]),
        })
    for i in range(COUNTS["TRANSACTION"]):
        # Cinco transacciones por cliente, sin relaciones huerfanas.
        customer = data["CUSTOMER"][i % COUNTS["CUSTOMER"]]
        data["TRANSACTION"].append({
            "transaction_id": f"SYN-T-{i + 1:06d}",
            "customer_id": customer["customer_id"],
            "amount": money(10, min(250000, int(customer["annual_income"] * 0.02))),
            "channel": rng.choice(channels),
            "merchant_category": rng.choice(MERCHANTS),
        })
    borrowers = rng.sample(data["CUSTOMER"], COUNTS["LOAN"])
    for i, customer in enumerate(borrowers):
        risk = customer["risk_level"]
        data["LOAN"].append({
            "loan_id": f"SYN-L-{i + 1:06d}",
            "customer_id": customer["customer_id"],
            "balance": money(1000, min(3000000, int(customer["annual_income"] * 2))),
            "interest_rate": money(*RATE[risk]),
            "dpd": 0 if rng.randrange(4) != 0 else rng.randint(1, DPD[risk]),
        })
    validate_data(data, metadata)
    return data


def validate_data(data, metadata):
    if set(data) != set(COUNTS):
        raise ValueError("Conjunto de tablas inesperado.")
    customers = {}
    for table, expected_count in COUNTS.items():
        rows = data[table]
        fields = metadata["tables"][table]["fields"]
        if len(rows) != expected_count:
            raise ValueError(f"Cantidad incorrecta en {table}: {len(rows)}; esperada {expected_count}.")
        seen = set()
        for row in rows:
            if set(row) != set(fields):
                raise ValueError(f"Columnas inesperadas en {table}.")
            for name, spec in fields.items():
                value = row[name]
                kind = spec["type"]
                valid_type = (
                    (kind == "STRING" and type(value) is str and bool(value.strip()))
                    or (kind == "INTEGER" and type(value) is int)
                    or (kind == "FLOAT" and type(value) is float and math.isfinite(value))
                )
                if not valid_type:
                    raise ValueError(f"Tipo, nulo o valor no finito en {table}.{name}.")
                if "allowed_values" in spec and value not in spec["allowed_values"]:
                    raise ValueError(f"Categoria no permitida en {table}.{name}.")
                if (table, name) in RANGES:
                    lower, upper = RANGES[table, name]
                    if not lower <= value <= upper:
                        raise ValueError(f"Fuera de rango didactico: {table}.{name}.")
            identifier = row[KEYS[table]]
            if identifier in seen:
                raise ValueError(f"Clave duplicada en {table}.")
            seen.add(identifier)
            if table == "CUSTOMER":
                customers[identifier] = row
                lower, upper = INCOME[row["segment"]]
                if not lower <= row["annual_income"] <= upper:
                    raise ValueError("Ingreso incompatible con el segmento didactico.")
            else:
                customer = customers.get(row["customer_id"])
                if customer is None:
                    raise ValueError(f"Referencia huerfana en {table}.customer_id.")
                if table == "TRANSACTION":
                    if row["amount"] > min(250000, int(customer["annual_income"] * 0.02)):
                        raise ValueError("Importe incompatible con el ingreso didactico.")
                else:
                    lower, upper = RATE[customer["risk_level"]]
                    if not lower <= row["interest_rate"] <= upper or row["dpd"] > DPD[customer["risk_level"]]:
                        raise ValueError("Tasa o mora incompatible con el riesgo didactico.")
                    if row["balance"] > min(3000000, int(customer["annual_income"] * 2)):
                        raise ValueError("Saldo incompatible con el ingreso didactico.")


def fingerprint(data):
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def settings():
    # No interpolar secretos ni imprimir la configuracion resuelta.
    values = {**dotenv_values(ROOT / ".env", interpolate=False), **os.environ}
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    if any(not values.get(key) for key in required):
        raise ValueError("Configura POSTGRES_USER, POSTGRES_PASSWORD y POSTGRES_DB en .env.")
    # El destino esta limitado al puerto local exclusivo del Compose existente.
    return {"host": "127.0.0.1", "port": 5434, "user": values["POSTGRES_USER"],
            "password": values["POSTGRES_PASSWORD"], "dbname": values["POSTGRES_DB"],
            "connect_timeout": 5, "application_name": "bank-synthetic-data"}


def set_schema(conn, schema):
    conn.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(schema)))


def schema_signature(conn, schema):
    set_schema(conn, schema)
    columns = conn.execute("""
        SELECT c.relname, c.relkind, a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull, a.attidentity, a.attgenerated, pg_get_expr(d.adbin, d.adrelid)
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = %s AND c.relname = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    """, (schema, list(COUNTS))).fetchall()
    constraints = conn.execute("""
        SELECT c.relname, k.conname, k.contype, k.convalidated, k.condeferrable,
               k.condeferred, pg_get_constraintdef(k.oid)
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid = k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = ANY(%s)
        ORDER BY c.relname, k.conname
    """, (schema, list(COUNTS))).fetchall()
    return columns, constraints


def check_schema(conn, metadata, schema="public"):
    actual = schema_signature(conn, schema)
    # PostgreSQL normaliza las expresiones CHECK. Comparar con su propio modelo
    # evita aceptar tablas preexistentes con restricciones distintas o ausentes.
    # El esquema de referencia nunca se confirma: solo vive en este savepoint.
    with conn.transaction(force_rollback=True):
        reference = "_bank_model_" + uuid.uuid4().hex
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(reference)))
        set_schema(conn, reference)
        conn.execute(build_migration(metadata))
        expected = schema_signature(conn, reference)
    if actual != expected:
        raise ValueError("Esquema incompatible con el catalogo y sus restricciones; no se modificaron datos.")


def migrate(conn, metadata, schema="public"):
    ddl = build_migration(metadata)
    if MIGRATION_PATH.read_text(encoding="utf-8") != ddl:
        raise ValueError("El SQL no coincide con el catalogo: regenera y revisa la migracion.")
    set_schema(conn, schema)
    conn.execute(ddl)
    check_schema(conn, metadata, schema)


def fetch_data(conn, metadata, schema="public"):
    result = {}
    for table in COUNTS:
        fields = list(metadata["tables"][table]["fields"])
        query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
            sql.SQL(", ").join(map(sql.Identifier, fields)), sql.Identifier(schema, table),
            sql.Identifier(KEYS[table]),
        )
        result[table] = [dict(zip(fields, row, strict=True)) for row in conn.execute(query)]
    return result


def lock_tables(conn, schema="public"):
    tables = sql.SQL(", ").join(sql.Identifier(schema, table) for table in COUNTS)
    conn.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(tables))


def authorize_reset(reset, confirmation, database):
    if reset and confirmation != database:
        raise ValueError("Reinicializacion rechazada: requiere --reset y --confirm-reset con el nombre exacto de la base local.")
    if confirmation is not None and not reset:
        raise ValueError("--confirm-reset requiere --reset.")


def populate(conn, expected, metadata, schema="public", *, reset=False, confirmation=None):
    authorize_reset(reset, confirmation, conn.info.dbname)
    validate_data(expected, metadata)
    lock_tables(conn, schema)
    check_schema(conn, metadata, schema)
    current = fetch_data(conn, metadata, schema)
    if current == expected:
        return "sin cambios"
    if any(current.values()):
        if not reset:
            raise ValueError("Hay datos existentes distintos o una carga parcial. Se cancela sin insertar ni sobrescribir.")
        # Unicamente mediante la doble opcion explicita. Sin CASCADE, DROP ni TRUNCATE.
        for table in reversed(COUNTS):
            conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(schema, table)))
    for table, rows in expected.items():
        fields = list(metadata["tables"][table]["fields"])
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(schema, table), sql.SQL(", ").join(map(sql.Identifier, fields)),
            sql.SQL(", ").join(sql.Placeholder() for _ in fields),
        )
        with conn.cursor() as cursor:
            cursor.executemany(statement, [[row[field] for field in fields] for row in rows])
    actual = fetch_data(conn, metadata, schema)
    validate_data(actual, metadata)
    if actual != expected:
        raise ValueError("La carga no coincide con la semilla; se revierte toda la transaccion.")
    return "carga completada"


def verify(conn, metadata, seed=SEED, schema="public"):
    lock_tables(conn, schema)
    check_schema(conn, metadata, schema)
    actual = fetch_data(conn, metadata, schema)
    validate_data(actual, metadata)
    if actual != generate(metadata, seed):
        raise ValueError("Los datos no coinciden con la semilla indicada.")
    return {"counts": {t: len(rows) for t, rows in actual.items()}, "seed": seed, "sha256": fingerprint(actual)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render-sql", help="Escribe el SQL local derivado del JSON; no conecta a PostgreSQL.")
    subparsers.add_parser("migrate", help="Crea y valida las tres tablas de forma atomica e idempotente.")
    for command in ("generate", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--seed", type=int, default=SEED)
        if command == "generate":
            child.add_argument("--reset", action="store_true", help="Reemplaza solo las tres tablas; requiere confirmacion del nombre de base.")
            child.add_argument("--confirm-reset", metavar="DATABASE")
    args = parser.parse_args(argv)
    try:
        metadata = load_metadata()
        if args.command == "render-sql":
            MIGRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
            MIGRATION_PATH.write_text(build_migration(metadata), encoding="utf-8", newline="\n")
            print("SQL escrito. Revisa el cambio antes de aplicar la migracion.")
            return 0
        config = settings()
        if args.command == "generate":
            authorize_reset(args.reset, args.confirm_reset, config["dbname"])
            expected = generate(metadata, args.seed)
        # Todo cambio de tablas o datos se confirma junto; cualquier fallo revierte.
        with psycopg.connect(**config) as conn:
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SET LOCAL statement_timeout = '120s'")
            if args.command == "migrate":
                migrate(conn, metadata)
                output = {"status": "tablas creadas o verificadas; vector sin cambios"}
            elif args.command == "generate":
                status = populate(conn, expected, metadata, reset=args.reset, confirmation=args.confirm_reset)
                output = {"status": status, "counts": COUNTS, "seed": args.seed, "sha256": fingerprint(expected)}
            else:
                output = verify(conn, metadata, args.seed)
        print(json.dumps(output, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except psycopg.Error as error:
        # Evitar DSN, contrasenas o filas completas en los mensajes de error.
        print(f"Error PostgreSQL ({error.sqlstate or 'conexion'}). Revisa el servicio y la configuracion local.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
