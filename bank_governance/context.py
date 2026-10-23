"""Bounded structured session context. Prior topics never become evidence."""
from dataclasses import dataclass,field,asdict
import re
import unicodedata

MONTHS=('enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))


@dataclass
class TurnContext:
    model_id: str
    corpus_id: str | None = None
    question: str = field(default='',repr=False)
    concepts: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    period: str | None = None
    pending_referent: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def begin(self,question):
        self.question=question;self.evidence_ids=[];self.limitations=[]
        text=normalize(question)
        identifiers=re.findall(r'\b(?:dim|cfg)\.[a-z_]+(?:\.[a-z_]+)?\b',text)
        if identifiers: self.identifiers=identifiers
        products=[p for p in ('CHEQUES','AHORRO','TDC','C_PERSONAL') if p.lower() in text]
        if products: self.products=products
        months=[month for month in MONTHS if re.search(r'\b'+month+r'\b',text)]
        if months: self.period=months[-1]
        elif 'mes siguiente' in text and self.period in MONTHS:
            self.period=MONTHS[(MONTHS.index(self.period)+1)%12]
        self.pending_referent=bool(re.search(r'\b(eso|ese|misma|mismo|y en|mes siguiente)\b',text))
        return self

    def accept(self,reply):
        self.evidence_ids=[e['document_id'] for e in reply.evidence]
        if reply.references:
            self.concepts=list(dict.fromkeys(r['json_pointer'] for r in reply.references))[-12:]
        if reply.status=='insufficient_evidence':self.limitations=['no_current_evidence']

    def retrieval_hint(self):
        # Only identifiers and topic names, never a remembered answer or old citation.
        return ' '.join([*self.identifiers,*self.products,*self.concepts,self.period or ''])

    def public_state(self):
        return {k:v for k,v in asdict(self).items() if k!='question'}
