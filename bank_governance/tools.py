"""Single documentary tool, no SQL execution tool."""
import json
import re
from dataclasses import asdict
from langchain_core.tools import tool
from bank_governance.contracts import Evidence,SearchInput
from bank_governance.errors import AgentError

def create_catalog_tool(agent, service_call):
    self=agent
    _service_call=service_call
    @tool("search_data_catalog", args_schema=SearchInput, response_format="content_and_artifact")
    def search_data_catalog(question: str):
        """Busca definiciones y ausencias en el catalogo sintetico; devuelve evidencia y fuentes. No consulta datos bancarios individuales."""
        self.security.run('catalog.'+self.data_model, 'retrieve')
        self.debug({"event": "tool_started", "tool": "search_data_catalog"})
        budget=12 if self.data_model=='new_bank_2026' and re.search(r'compara|diferencia',question,re.I) else 5
        matches = _service_call("retrieval", lambda: self.retriever.search(question, k=budget))
        batch = []
        for match in matches:
            metadata = match["metadata"]
            if self.data_model=='new_bank_2026':
                expected=self.retriever.expected.get(str(match['id']))
                if (expected is None or match['content']!=expected.page_content or metadata!=expected.metadata
                    or metadata.get('model_id')!=self.data_model or metadata.get('corpus_id')!=self.retriever.corpus_id):
                    raise AgentError('Evidencia alterada o de otro corpus; respuesta descartada.')
            identifier = str(match["id"])
            if identifier not in self._evidence:
                self._evidence[identifier] = Evidence(
                    evidence_id=f"E{len(self._evidence) + 1}", document_id=identifier,
                    content=match["content"], source=match["source"],
                    source_version=match["source_version"], table=metadata.get("table"),
                    field=metadata.get("field"), json_pointer=metadata["json_pointer"],
                    kind=metadata["kind"], similarity=match.get("cosine_similarity"),
                    model_id=self.data_model,corpus_id=str(metadata.get('corpus_id','')),
                    claims=metadata.get('claims',[]),
                )
            batch.append(self._evidence[identifier])
        self.debug({"event": "tool_finished", "tool": "search_data_catalog", "document_count": len(batch),
                        "evidence_chars":sum(len(e.content) for e in batch),
                        "retrieval":getattr(self.retriever,'last_diagnostics',None) if
                            type(getattr(self.retriever,'last_diagnostics',None)) is dict else None,
                    "document_ids": [e.document_id for e in batch],
                    "pointers": [e.json_pointer for e in batch]})
        # Full cryptographic provenance stays in the artifact/code contract.
        # Repeating it in the model context can truncate the useful chunks.
        visible=[{'evidence_id':e.evidence_id,'content':e.content} for e in batch] if self.data_model=='new_bank_2026' else [asdict(e) for e in batch]
        payload = {"scope": "synthetic_catalog_only", 'model_id':self.data_model,"evidence":visible}
        return json.dumps(payload, ensure_ascii=False), batch

    return search_data_catalog
