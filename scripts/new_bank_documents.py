"""Reproducible LangChain Documents from the reviewed semantic catalog, offline."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
import uuid

from langchain_core.documents import Document

from scripts import new_bank_catalog as catalog

ROOT=catalog.ROOT
RENDERER_VERSION="1.0.0"
DOCUMENTS_PATH=ROOT/"data/corpus/new_bank_model.documents.jsonl"
MANIFEST_PATH=ROOT/"data/corpus/new_bank_model.documents.manifest.json"
CATALOG_SOURCE="data/source/new_bank_model/catalog.json"


def catalog_text(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'


def load_catalog():
    value=json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    expected=catalog.build_catalog()
    if value!=expected or catalog.CATALOG_PATH.read_bytes()!=catalog_text(value).encode("utf-8"):
        raise ValueError("Catalog artifact differs from reviewed source builder")
    return value


def pointer_key(value):
    return value.replace('~','~0').replace('/','~1')


def resolve_pointer(value,pointer):
    if pointer=="":
        return value
    if not pointer.startswith('/'):
        raise ValueError("Invalid catalog JSON pointer")
    for key in pointer[1:].split('/'):
        key=key.replace('~1','/').replace('~0','~')
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


def render_entry(entry):
    lines=[f"Modelo bancario sintético {catalog.MODEL_ID}, catálogo {catalog.VERSION}.",entry["title"]]
    lines.extend(f"[{claim['classification']}] {claim['text']}" for claim in entry["claims"])
    return '\n'.join(lines)


def build_documents(value=None):
    value=load_catalog() if value is None else value
    catalog.validate_catalog(value)
    source_hash=catalog.digest(catalog_text(value))
    documents=[]
    for key,entry in value["entries"].items():
        pointer='/entries/'+pointer_key(key)
        content=render_entry(entry)
        # No source excerpts or JSON scaffolding consume the embedding context.
        if len(content)>1800:
            raise ValueError("Semantic chunk exceeds reviewed size: "+key)
        identity=catalog.canonical([catalog.MODEL_ID,catalog.VERSION,source_hash,RENDERER_VERSION,key])
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,identity))
        metadata={"model_id":catalog.MODEL_ID,"catalog_version":catalog.VERSION,
            "source":CATALOG_SOURCE,"source_version":catalog.VERSION,"source_sha256":source_hash,
            "renderer_version":RENDERER_VERSION,"kind":entry["kind"],"entry_id":key,
            "json_pointer":pointer,"table":entry["attributes"].get("table"),
            "field":entry["attributes"].get("column"),"attributes":entry["attributes"],
            "query_terms":entry["query_terms"],"chunk_sha256":catalog.digest(content),
            "assertion_origins":sorted({c["classification"] for c in entry["claims"]}),
            "claims":[{**claim,"json_pointer":pointer+f"/claims/{index}"} for index,claim in enumerate(entry["claims"])]}
        documents.append(Document(id=identifier,page_content=content,metadata=metadata))
    validate_documents(documents,value)
    return documents


def validate_documents(documents,value=None):
    value=load_catalog() if value is None else value
    if len(documents)!=len(value["entries"]) or len({d.id for d in documents})!=len(documents):
        raise ValueError("Document count/ID coverage mismatch")
    if {d.metadata["entry_id"] for d in documents}!=set(value["entries"]):
        raise ValueError("Document semantic coverage mismatch")
    for doc in documents:
        metadata=doc.metadata
        entry=resolve_pointer(value,metadata["json_pointer"])
        identity=catalog.canonical([catalog.MODEL_ID,catalog.VERSION,catalog.digest(catalog_text(value)),RENDERER_VERSION,entry['id']])
        if doc.id!=str(uuid.uuid5(uuid.NAMESPACE_URL,identity)) or doc.page_content!=render_entry(entry):
            raise ValueError("Document content/ID differs from its cited claims")
        if metadata["model_id"]!=catalog.MODEL_ID or entry["id"]!=metadata["entry_id"]:
            raise ValueError("Document scope mismatch")
        if metadata["chunk_sha256"]!=catalog.digest(doc.page_content) or metadata["source_sha256"]!=catalog.digest(catalog_text(value)):
            raise ValueError("Document/catalog content hash mismatch")
        for claim in metadata["claims"]:
            original=resolve_pointer(value,claim["json_pointer"])
            if {k:v for k,v in claim.items() if k!="json_pointer"}!=original:
                raise ValueError("Claim/citation pointer mismatch")
    return True


def document_manifest(documents):
    return {"format":"new-bank-document-manifest-v1","model_id":catalog.MODEL_ID,
            "catalog_version":catalog.VERSION,"catalog_sha256":documents[0].metadata["source_sha256"],
            "renderer_version":RENDERER_VERSION,"document_count":len(documents),
            "kinds":dict(sorted(Counter(d.metadata["kind"] for d in documents).items())),
            "content_sha256":catalog.digest(catalog.canonical([
                [d.id,d.page_content,d.metadata] for d in sorted(documents,key=lambda d:d.id)])),
            "documents":[{"id":d.id,"entry_id":d.metadata["entry_id"],"sha256":d.metadata["chunk_sha256"]}
                         for d in documents]}


def corpus_identity(documents,model):
    signature=catalog.canonical({"document_manifest":document_manifest(documents),"embedding_model":asdict(model)})
    return str(uuid.uuid5(uuid.NAMESPACE_URL,signature))


def storage_documents(documents,model):
    corpus_id=corpus_identity(documents,model)
    return corpus_id,[Document(id=str(uuid.uuid5(uuid.UUID(corpus_id),doc.id)),page_content=doc.page_content,
        metadata={**doc.metadata,"document_id":doc.id,"corpus_id":corpus_id,"embedding_model":model.name,
                  "embedding_digest":model.digest,"embedding_dimension":model.dimension}) for doc in documents]


def artifact_texts(documents):
    jsonl=''.join(catalog.canonical({"id":doc.id,"page_content":doc.page_content,"metadata":doc.metadata})+'\n' for doc in documents)
    manifest=json.dumps(document_manifest(documents),ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    return {DOCUMENTS_PATH:jsonl,MANIFEST_PATH:manifest}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"))
    args=parser.parse_args(argv)
    documents=build_documents()
    for path,text in artifact_texts(documents).items():
        if args.command=="build":
            path.write_text(text,encoding="utf-8",newline="\n")
        elif path.read_bytes()!=text.encode("utf-8"):
            raise ValueError("Document artifact mismatch: "+str(path))
    print(json.dumps(document_manifest(documents),ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
