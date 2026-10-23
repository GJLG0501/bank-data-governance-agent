"""Corpus del catalogo y recuperacion vectorial local, sin un LLM generativo."""

import argparse
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import re
import sys
import uuid

import httpx
from dotenv import dotenv_values
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import DistanceStrategy
from ollama import Client, ResponseError
from pgvector.psycopg import Vector, register_vector
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from scripts.bank_data import METADATA_PATH, ROOT, settings

SOURCE = "data/source/bank_metadata.json"
SCHEMA = "bank_knowledge"
RENDERER_VERSION = "1"
CORPUS_PATH = ROOT / "data/corpus/bank_metadata.documents.jsonl"
DDL_PATH = ROOT / "sql/002-create-knowledge-corpus.sql"
CASES_PATH = ROOT / "tests/fixtures/retrieval_cases.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_documents(path=METADATA_PATH):
    raw = path.read_bytes()
    catalog = json.loads(raw.decode("utf-8-sig"))
    source_hash = hashlib.sha256(raw).hexdigest()
    base = {"source": SOURCE, "source_version": catalog["version"],
            "dataset_name": catalog["dataset_name"], "source_sha256": source_hash,
            "renderer_version": RENDERER_VERSION}
    documents = []

    def add(kind, pointer, payload, table=None, field=None):
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        identity = canonical([SOURCE, source_hash, RENDERER_VERSION, pointer])
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        documents.append(Document(id=identifier, page_content=content, metadata={
            **base, "table": table, "field": field, "kind": kind,
            "json_pointer": pointer, "chunk_sha256": sha256(content),
        }))

    add("catalog", "/", {key: catalog[key] for key in ("dataset_name", "version", "description")})
    for table, definition in catalog["tables"].items():
        add("table", f"/tables/{table}", {
            "table": table, "description": definition["description"],
            "columns": list(definition["fields"]),
        }, table)
        for field, spec in definition["fields"].items():
            pointer = f"/tables/{table}/fields/{field}"
            add("field", pointer, {"field": f"{table}.{field}", "definition": spec}, table, field)
            if "foreign_key" in spec:
                add("relationship", pointer + "/foreign_key", {
                    "relationship": f"{table}.{field} -> {spec['foreign_key']}",
                    "foreign_key": spec["foreign_key"], "business_meaning": spec["business_meaning"],
                }, table, field)
    for index, absence in enumerate(catalog["known_absences_for_exercise"]):
        references = re.findall(r"\b([A-Z]+)\.([a-z_]+)\b", absence)
        table, field = references[0] if len(references) == 1 else (None, None)
        add("explicit_absence", f"/known_absences_for_exercise/{index}",
            {"explicit_catalog_absence": absence}, table, field)
    if len({doc.id for doc in documents}) != len(documents):
        raise ValueError("Identificadores documentales duplicados.")
    return documents


def write_corpus(documents):
    content = "".join(canonical({"id": doc.id, "page_content": doc.page_content,
                                 "metadata": doc.metadata}) + "\n" for doc in documents)
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(content, encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str
    dimension: int


def validate_vectors(vectors, count, dimension):
    if type(dimension) is not int or not 1 <= dimension <= 16000 or len(vectors) != count:
        raise ValueError("Cantidad o dimension de embeddings incorrecta.")
    for vector in vectors:
        if len(vector) != dimension or any(not math.isfinite(v) for v in vector):
            raise ValueError("Embedding no finito o de dimension incompatible.")
        if not any(v != 0 for v in vector):
            raise ValueError("No se admite un embedding de norma cero.")


def embedding_config():
    config = {**dotenv_values(ROOT / ".env", interpolate=False), **os.environ}
    return (config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            config.get("OLLAMA_EMBEDDING_MODEL", "bge-large:latest"))


def model_digest(client, name):
    models = {model.model: model.digest for model in client.list().models}
    if name not in models:
        raise ValueError(f"Modelo de embeddings no instalado: {name}. Instala explicitamente el modelo antes de ingerir.")
    return models[name]


def probe_model():
    base_url, name = embedding_config()
    client = Client(host=base_url, timeout=120)
    digest = model_digest(client, name)
    embeddings = OllamaEmbeddings(model=name, base_url=base_url,
                                  client_kwargs={"timeout": 120})
    probe = embeddings.embed_query("Embedding dimension probe: bank metadata catalog.")
    validate_vectors([probe], 1, len(probe))
    if model_digest(client, name) != digest:
        raise ValueError("El modelo cambio durante la medicion; repite la operacion.")
    return embeddings, ModelIdentity(name, digest, len(probe))


def corpus_identity(documents, model):
    signature = canonical({"documents": [(doc.id, doc.metadata["chunk_sha256"]) for doc in documents],
                           "model": asdict(model), "renderer": RENDERER_VERSION})
    return uuid.uuid5(uuid.NAMESPACE_URL, signature)


def storage_documents(documents, model):
    corpus_id = corpus_identity(documents, model)
    return corpus_id, [Document(
        id=str(uuid.uuid5(corpus_id, doc.id)), page_content=doc.page_content,
        metadata={**doc.metadata, "document_id": doc.id, "embedding_model": model.name,
                  "embedding_digest": model.digest, "embedding_dimension": model.dimension},
    ) for doc in documents]


def initialize_storage(conn, dimension, schema=SCHEMA):
    validate_vectors([], 0, dimension)
    ddl = sql.SQL(DDL_PATH.read_text(encoding="utf-8")).format(
        schema=sql.Identifier(schema), dimension=sql.Literal(dimension))
    conn.execute(ddl)
    actual = conn.execute("""
        SELECT t.typname, tn.nspname, a.atttypmod
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_type t ON t.oid=a.atttypid
        JOIN pg_catalog.pg_namespace tn ON tn.oid=t.typnamespace
        WHERE n.nspname=%s AND c.relname='documents' AND a.attname='embedding'
          AND a.attnum > 0 AND NOT a.attisdropped
    """, (schema,)).fetchone()
    if actual != ("vector", "public", dimension):
        raise ValueError("La tabla documental tiene una dimension incompatible; no se altero ni elimino.")


def expected_manifest(documents, model):
    first = documents[0].metadata
    return (SOURCE, first["source_version"], first["source_sha256"], RENDERER_VERSION,
            model.name, model.digest, model.dimension, len(documents))


def check_indexed(conn, documents, model, schema=SCHEMA):
    corpus_id, stored = storage_documents(documents, model)
    manifest = conn.execute(sql.SQL("""
        SELECT source, source_version, source_sha256, renderer_version,
               model_name, model_digest, dimension, document_count
        FROM {}.corpora WHERE corpus_id=%s
    """).format(sql.Identifier(schema)), (corpus_id,)).fetchone()
    if manifest is None:
        return False
    if manifest != expected_manifest(documents, model):
        raise ValueError("Manifiesto documental incompatible.")
    rows = conn.execute(sql.SQL("""
        SELECT id, content, metadata, public.vector_dims(embedding)
        FROM {}.documents WHERE corpus_id=%s ORDER BY id
    """).format(sql.Identifier(schema)), (corpus_id,)).fetchall()
    expected = sorted((uuid.UUID(doc.id), doc.page_content, doc.metadata, model.dimension) for doc in stored)
    if rows != expected:
        raise ValueError("El corpus almacenado es parcial o difiere del original; no se sobrescribira.")
    return True


def ingest(conn, documents, embeddings, model, schema=SCHEMA):
    """Llamar dentro de una transaccion: DDL, manifiesto y documentos son atomicos."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.bank_metadata.ingest",))
    initialize_storage(conn, model.dimension, schema)
    corpus_id, stored = storage_documents(documents, model)
    if check_indexed(conn, documents, model, schema):
        return {"status": "sin cambios", "documents": len(stored), "corpus_id": str(corpus_id), **asdict(model)}
    vectors = []
    for start in range(0, len(stored), 8):
        batch = stored[start:start + 8]
        batch_vectors = embeddings.embed_documents([doc.page_content for doc in batch])
        validate_vectors(batch_vectors, len(batch), model.dimension)
        vectors.extend(batch_vectors)
    # El adaptador busca por search_path; public contiene la extension existente.
    previous_path = conn.execute("SHOW search_path").fetchone()[0]
    conn.execute("SELECT set_config('search_path', 'public, pg_catalog', true)")
    register_vector(conn)
    conn.execute("SELECT set_config('search_path', %s, true)", (previous_path,))
    conn.execute(sql.SQL("INSERT INTO {}.corpora VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)").format(
        sql.Identifier(schema)), (corpus_id, *expected_manifest(documents, model)))
    with conn.cursor() as cursor:
        cursor.executemany(sql.SQL("INSERT INTO {}.documents (id,corpus_id,content,metadata,embedding) VALUES (%s,%s,%s,%s,%s)").format(
            sql.Identifier(schema)), [(uuid.UUID(doc.id), corpus_id, doc.page_content, Jsonb(doc.metadata), Vector(vector))
                                     for doc, vector in zip(stored, vectors, strict=True)])
    check_indexed(conn, documents, model, schema)
    return {"status": "indexado", "documents": len(stored), "corpus_id": str(corpus_id), **asdict(model)}


def vector_engine():
    config = settings()
    # asyncpg evita la incompatibilidad de psycopg async con Proactor en Windows.
    url = URL.create("postgresql+asyncpg", username=config["user"], password=config["password"],
                     host=config["host"], port=config["port"], database=config["dbname"])
    return PGEngine.from_connection_string(url, connect_args={"timeout": 5,
        "server_settings": {"application_name": "bank-knowledge-retrieval", "statement_timeout": "30000",
                            "default_transaction_read_only":"on"}})


def create_store(engine, embeddings, schema=SCHEMA):
    return PGVectorStore.create_sync(
        engine=engine, embedding_service=embeddings, table_name="documents", schema_name=schema,
        id_column="id", content_column="content", embedding_column="embedding",
        metadata_json_column="metadata", metadata_columns=["corpus_id"],
        distance_strategy=DistanceStrategy.COSINE_DISTANCE,
    )


def search_store(store, question, corpus_id, dimension, k=5):
    if not question.strip() or not 1 <= k <= 20:
        raise ValueError("Indica una pregunta no vacia y k entre 1 y 20.")
    vector = store.embeddings.embed_query(question)
    validate_vectors([vector], 1, dimension)
    matches = store.similarity_search_with_score_by_vector(
        vector, k=k, filter={"corpus_id": {"$eq": str(corpus_id)}})
    results = []
    for doc, distance in matches:
        if not math.isfinite(float(distance)):
            raise ValueError("Distancia coseno no finita.")
        results.append({"id": doc.id, "content": doc.page_content,
                        "source": doc.metadata["source"],
                        "source_version": doc.metadata["source_version"],
                        "metadata": {**doc.metadata, "corpus_id": str(doc.metadata["corpus_id"])},
                        "cosine_distance": float(distance), "cosine_similarity": 1.0 - float(distance)})
    return results


def retrieve(question, k=5):
    """API publica: solo fragmentos, procedencia y similitud; no genera respuestas."""
    with RetrievalSession() as session:
        return session.search(question, k)


class RetrievalSession:
    def __enter__(self):
        self.documents = build_documents()
        embeddings, self.model = probe_model()
        self.corpus_id = corpus_identity(self.documents, self.model)
        with psycopg.connect(**settings(),options='-c default_transaction_read_only=on') as conn:
            exists = conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.corpora",)).fetchone()[0]
            if not exists or not check_indexed(conn, self.documents, self.model):
                raise ValueError("El catalogo o modelo actual no esta indexado. Ejecuta ingest primero.")
        self.engine = vector_engine()
        try:
            self.store = create_store(self.engine, embeddings)
        except Exception:
            asyncio.run(self.engine.close())
            raise
        return self

    def __exit__(self, *exc):
        asyncio.run(self.engine.close())

    def search(self, question, k=5):
        results = search_store(self.store, question, self.corpus_id, self.model.dimension, k)
        base_url, _ = embedding_config()
        if model_digest(Client(host=base_url, timeout=120), self.model.name) != self.model.digest:
            raise ValueError("El modelo cambio durante la consulta; se descartan los resultados.")
        return results


def evaluate(session):
    reports = []
    for case in json.loads(CASES_PATH.read_text(encoding="utf-8")):
        results = session.search(case["question"], case["k"])
        retrieved = {result["metadata"]["json_pointer"] for result in results}
        passed = set(case["expected_pointers"]).issubset(retrieved)
        reports.append({"case": case["name"], "question": case["question"], "passed": passed,
                        "k": case["k"], "results": [{"pointer": result["metadata"]["json_pointer"],
                            "similarity": result["cosine_similarity"]} for result in results]})
    return {"model": asdict(session.model), "passed": sum(report["passed"] for report in reports),
            "total": len(reports), "cases": reports}


def main(argv=None):
    # Windows puede elegir cp1252 al redirigir stdout; el corpus y la CLI son UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "probe", "ingest", "evaluate"):
        sub.add_parser(command)
    search = sub.add_parser("search")
    search.add_argument("question")
    search.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            documents = build_documents()
            write_corpus(documents)
            result = {"documents": len(documents), "path": str(CORPUS_PATH.relative_to(ROOT))}
        elif args.command == "probe":
            _, model = probe_model()
            result = asdict(model)
        elif args.command == "ingest":
            documents = build_documents()
            write_corpus(documents)
            embeddings, model = probe_model()
            with psycopg.connect(**settings()) as conn:
                conn.execute("SET LOCAL lock_timeout = '10s'")
                conn.execute("SET LOCAL statement_timeout = '120s'")
                result = ingest(conn, documents, embeddings, model)
                base_url, _ = embedding_config()
                if model_digest(Client(host=base_url, timeout=120), model.name) != model.digest:
                    raise ValueError("El modelo cambio durante la ingestion; se revierte la carga.")
        elif args.command == "search":
            result = retrieve(args.question, args.k)
        else:
            with RetrievalSession() as session:
                result = evaluate(session)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["passed"] == result["total"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except psycopg.Error as error:
        print(f"Error PostgreSQL ({error.sqlstate or 'conexion'}); revisa el servicio local.", file=sys.stderr)
    except SQLAlchemyError:
        print("Error de conexion o consulta en el almacen vectorial local.", file=sys.stderr)
    except (httpx.HTTPError, ResponseError, ConnectionError):
        print("Error Ollama: revisa el servicio local y el modelo de embeddings instalado.", file=sys.stderr)
    except (ValueError, KeyError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
