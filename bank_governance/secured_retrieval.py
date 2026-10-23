"""Document authorization BEFORE returning evidence, including manifest lexical access."""
from copy import deepcopy
from bank_governance.errors import AgentError
from bank_governance.security import anonymous_access, AuthorizationDenied


class SecuredRetriever:
    def __init__(self, backend, model_id, access=None, *, classifications=None):
        self._backend = backend
        self.access = access or anonymous_access()
        self.resource = 'catalog.'+model_id
        # Backend manifests are validated by the operational adapters. Snapshot
        # trusted documents; incoming metadata cannot downgrade their policy.
        expected = getattr(backend, 'expected', None)
        if (not isinstance(expected, dict) and model_id == 'legacy_metadata'
            and isinstance(getattr(backend, 'documents', None), list)):
            from scripts.knowledge_corpus import storage_documents
            _, stored = storage_documents(backend.documents, backend.model)
            expected = {doc.id: doc for doc in stored}
        self._expected = deepcopy(expected) if isinstance(expected, dict) else {}
        self._classifications = {key: 'internal_metadata' for key in self._expected}
        for key, value in (classifications or {}).items():
            if key in self._expected:
                self._classifications[key] = value
        self.corpus_id = getattr(backend, 'corpus_id', None)

    def _document_allowed(self, identifier):
        classification = self._classifications.get(identifier)
        resource = ('docs.public' if classification == 'public_documentation' else
            self.resource if classification == 'internal_metadata' else 'docs.restricted')
        try:
            self.access.run(resource, 'retrieve', tool='retrieval')
        except AuthorizationDenied:
            return False
        return classification in ('public_documentation', 'internal_metadata')

    @property
    def expected(self):
        self.access.run(self.resource, 'retrieve', tool='retrieval')
        return deepcopy({key: doc for key, doc in self._expected.items() if self._document_allowed(key)})

    def search(self, question, k=5):
        self.access.run(self.resource, 'retrieve', tool='retrieval')
        if type(k) is not int or not 1 <= k <= 20:
            raise ValueError('k must be 1..20')
        matches = self._backend.search(question, k=k)
        permitted = []
        for match in matches:
            identifier = str(match['id'])
            if identifier not in self._expected:
                raise AgentError('Evidencia alterada o de otro corpus; respuesta descartada.')
            if not self._document_allowed(identifier):
                continue
            doc = self._expected[identifier]
            if match['content'] != doc.page_content or match['metadata'] != doc.metadata:
                raise AgentError('Evidencia alterada o de otro corpus; respuesta descartada.')
            permitted.append(match)
        return permitted
