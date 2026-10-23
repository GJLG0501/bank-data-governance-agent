"""Scoped read adapters and opt-in exact/semantic reciprocal-rank fusion.

Lexical lookup uses the immutable 82-document manifest already verified by the
backend; no duplicate index, DDL, document embeddings or unscoped SQL.
"""
from contextlib import contextmanager
import json
import re

from bank_governance.context import normalize,MONTHS


def contextual_query(question,context=None):
    text=normalize(question)
    period=any(re.search(r'\b'+m+r'\b',text) for m in MONTHS)
    temporal=bool(re.search(r'\b(cierre|apertura|abre|inicia|inicio|saldo)\b',text))
    inherited_temporal=bool(context and context.pending_referent and context.period and
        any('temporal.' in concept or 'saldo_apertura' in concept for concept in context.concepts+context.identifiers))
    if (temporal and (period or (context and context.period))) or inherited_temporal:
        question+=' saldo_apertura cierre mes calendario anterior'
    if context and context.pending_referent:
        question+=' '+context.retrieval_hint()
    return question


class HybridRetriever:
    def __init__(self,backend,context=None,*,security=None):
        from bank_governance.secured_retrieval import SecuredRetriever
        self.backend=SecuredRetriever(backend,'new_bank_2026',security)
        self.context=context

    def __getattr__(self,name):
        return getattr(self.backend,name)

    def search(self,question,k=5):
        self.backend.access.run(self.backend.resource,'retrieve',tool='retrieval')
        self.last_diagnostics={'semantic_attempts':0,'lexical_candidates':0,'fusion':'rrf'}
        if type(k) is not int or not 1<=k<=20: raise ValueError('k must be 1..20')
        # Keep the backend's domain/unknown-field safeguards after reformulation.
        from scripts.new_bank_rag import evidence_eligible
        from scripts.new_bank_documents import build_documents
        query=contextual_query(question,self.context)
        if not evidence_eligible(query,build_documents()):return []
        semantic=self.backend.search(question,k=k)
        self.last_diagnostics['semantic_attempts']=1
        if not semantic and query!=question:
            semantic=self.backend.search(query,k=k)
            self.last_diagnostics['semantic_attempts']=2
        tokens=set(re.findall(r'[a-z_][a-z_0-9.]+',normalize(query)))
        stop={'que','cual','como','para','del','los','las','una','por','con','mes','anterior'}
        tokens-=stop
        scored=[]
        for identifier,doc in self.backend.expected.items():
            meta=doc.metadata
            if meta.get('model_id')!='new_bank_2026' or meta.get('corpus_id')!=self.backend.corpus_id:
                raise ValueError('Lexical candidate outside validated scope')
            names=normalize(' '.join([meta['entry_id'],*meta.get('query_terms',[])]))
            matches=sum(bool(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',names)) for t in tokens)
            if matches>=2 or any(t in names for t in tokens if '.' in t or '_' in t):
                scored.append((matches,identifier,doc))
        scored.sort(key=lambda x:(-x[0],x[1]))
        self.last_diagnostics['lexical_candidates']=min(len(scored),20)
        lexical=[]
        for _,identifier,doc in scored[:20]:
            lexical.append({'id':identifier,'content':doc.page_content,'metadata':doc.metadata,
                'source':doc.metadata['source'],'source_version':doc.metadata['source_version'],
                'cosine_similarity':None,'retrieval_strategy':'manifest_lexical_rrf'})
        ranks={};objects={}
        for group in (semantic,lexical):
            for rank,result in enumerate(group,1):
                identifier=str(result['id']);objects.setdefault(identifier,result)
                ranks[identifier]=ranks.get(identifier,0)+1/(60+rank)
        return [objects[i] for i in sorted(ranks,key=lambda i:(-ranks[i],i))[:k]]


@contextmanager
def catalog_session(model_id, *, security=None):
    from bank_governance.security import anonymous_access
    from bank_governance.secured_retrieval import SecuredRetriever
    security=security or anonymous_access()
    security.run('catalog.'+model_id,'retrieve',tool='retrieval')
    if model_id=='legacy_metadata':
        from scripts.knowledge_corpus import RetrievalSession
        with RetrievalSession() as session: yield SecuredRetriever(session,model_id,security)
    elif model_id=='new_bank_2026':
        from scripts import new_bank_rag as rag,new_bank_documents as docs
        embeddings,model=rag.probe()
        manifest=json.loads(rag.INDEX_PATH.read_text(encoding='utf-8'))
        retriever=rag.CatalogRetriever(None,docs.build_documents(),embeddings,model,
            model_id=model_id,corpus_id=manifest['corpus_id'],index_manifest=manifest,published=True)
        from bank_governance.database import read_published
        retriever.read=read_published
        yield SecuredRetriever(retriever,model_id,security)
    else:raise ValueError('Unknown catalog; no fallback')
