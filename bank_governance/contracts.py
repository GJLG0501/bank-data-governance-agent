"""Shared documentary contracts; operations never contain executable SQL."""
from dataclasses import asdict,dataclass,field
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from bank_governance.security_contracts import (AuthenticatedIdentity, AccessSession,
    AccessContext, Resource, PolicyDecision, AuditEvent)

class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000,
                          description="Pregunta contextualizada sobre el catalogo sintetico.")

class AnswerDraft(BaseModel):
    status: Literal["grounded", "explicit_absence", "insufficient_evidence"]
    answer: str = Field(max_length=2000, description="Respuesta breve en espanol, sin referencias libres.")
    evidence_ids: list[str] = Field(description="Etiquetas E1, E2, etc. de evidencia del turno actual.")

class EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_ids: list[str] = Field(max_length=12,description='Etiquetas de fichas pertinentes del turno, sin inventarlas.')

class GroundedStatement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)

class GroundedExplanation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['grounded','explicit_absence','insufficient_evidence']
    statements: list[GroundedStatement] = Field(max_length=6)

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    document_id: str
    content: str
    source: str
    source_version: str
    table: str | None
    field: str | None
    json_pointer: str
    kind: str
    similarity: float | None
    model_id: str = 'legacy_metadata'
    corpus_id: str | None = None
    claims: list = field(default_factory=list)

@dataclass
class AgentReply:
    status: str
    answer: str
    references: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    tool_calls: int = 0
    diagnostic: str | None = None
    validation_results: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {**asdict(self), "retrieved_document_count": len(self.evidence),
                "used_document_count": len(self.references)}


class VerificationOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['calendar_previous','transaction_sign','formula_identity','physical_nullability']
    period: str | None = None
    product: str | None = None
    code: int | None = None
    expression: str | None = None
    identifier: str | None = None
    expected: str


class AtomicClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=600)
    evidence_ids: list[str] = Field(min_length=1,max_length=6)
    claim_type: Literal['literal','inference','limitation']
    operation: VerificationOperation | None = None


class AtomicExplanation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['answer','documented_absence','insufficient_evidence']
    claims: list[AtomicClaim] = Field(max_length=6)


class SpecialistRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1,max_length=2000)
    model_id: Literal['new_bank_2026','legacy_metadata'] = 'legacy_metadata'
    capability: Literal['catalog','analytics','quality','governance'] = 'catalog'


class SpecialistResult(BaseModel):
    specialist: str
    status: str
    answer: str
    references: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
