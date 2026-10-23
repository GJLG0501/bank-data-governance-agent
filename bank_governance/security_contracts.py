"""Security wire types are descriptions, never credentials or grants."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

Sensitivity = Literal['public_documentation', 'internal_metadata', 'aggregate_finance',
    'personal_data', 'identifiers', 'individual_movements', 'restricted']
Action = Literal['read', 'retrieve', 'aggregate', 'export', 'write']


class SecurityContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class AuthenticatedIdentity(SecurityContract):
    pseudonym: str
    issuer: str
    simulated: bool
    roles: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...] = ()


class AccessSession(SecurityContract):
    session_id: UUID = Field(repr=False)
    identity: AuthenticatedIdentity
    expires_at: datetime


class AccessContext(SecurityContract):
    purpose: Literal['catalog', 'aggregate_reporting', 'account_support']
    scopes: tuple[str, ...]
    account_scope: str | None = None
    verified_cohort_size: int | None = Field(default=None, ge=0)


class Resource(SecurityContract):
    resource_id: str
    sensitivity: Sensitivity


class PolicyDecision(SecurityContract):
    decision: Literal['allow', 'deny', 'requires_approval']
    policy_id: str
    reason: str


class AuditEvent(SecurityContract):
    request_id: UUID
    pseudonym: str
    simulated: bool
    agent: str
    tool: str
    resource: str
    action: Action | Literal['unknown']
    policy_id: str
    decision: Literal['allow', 'deny', 'requires_approval']
    timestamp: datetime
    duration_ms: float
    outcome: Literal['allowed', 'denied', 'approval_required', 'completed', 'failed']
    reason: str
