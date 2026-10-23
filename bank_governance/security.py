"""Minimal SYNTHETIC MVP policy enforcement, not production authentication.

Only host code issues demo sessions and operation contexts. Neither chat text,
typed wire objects, retrieved documents nor the LLM can issue a grant. Host Python
and the database adapter remain trusted; this is not a sandbox for malicious code.
"""
from collections import deque
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4
from bank_governance.errors import AgentError
from bank_governance.security_contracts import (AuthenticatedIdentity, AccessSession,
    AccessContext, Resource, PolicyDecision, AuditEvent)

POLICY_VERSION = 'synthetic-mvp-1'
PROFILES = {
    'steward_demo': ('sim-steward-01', ('steward',), 'catalog', ('catalog',)),
    'analyst_demo': ('sim-analyst-01', ('analyst',), 'aggregate_reporting', ('catalog', 'aggregates')),
    'support_demo': ('sim-support-01', ('support',), 'account_support', ('account-demo-1',)),
}
RESOURCES = {
    'catalog.legacy_metadata': Resource(resource_id='catalog.legacy_metadata', sensitivity='internal_metadata'),
    'catalog.new_bank_2026': Resource(resource_id='catalog.new_bank_2026', sensitivity='internal_metadata'),
    'docs.public': Resource(resource_id='docs.public', sensitivity='public_documentation'),
    'bank.aggregate': Resource(resource_id='bank.aggregate', sensitivity='aggregate_finance'),
    'bank.identifiers': Resource(resource_id='bank.identifiers', sensitivity='identifiers'),
    'bank.account': Resource(resource_id='bank.account', sensitivity='individual_movements'),
    'docs.restricted': Resource(resource_id='docs.restricted', sensitivity='restricted'),
}


class AuthorizationDenied(AgentError):
    def __init__(self, decision):
        self.decision = decision
        super().__init__('Acceso no autorizado por la política sintética del MVP: ' + decision.reason)


class PolicyEngine:
    """Local issuer registry: validating a dataclass/model alone does NOT establish trust."""
    def __init__(self):
        self._sessions = {}
        self._contexts = {}
        self.events = deque(maxlen=1000)  # volatile, bounded; no payloads or credentials

    def _issue(self, profile, *, account_scope=None, verified_cohort_size=None):
        pseudonym, roles, purpose, scopes = PROFILES[profile]
        session = AccessSession(session_id=uuid4(), expires_at=datetime.now(timezone.utc)+timedelta(hours=1),
            identity=AuthenticatedIdentity(pseudonym=pseudonym, issuer='local-simulation',
                simulated=True, roles=roles, attributes=(('environment', 'synthetic-mvp'),)))
        context = AccessContext(purpose=purpose, scopes=scopes, account_scope=account_scope,
            verified_cohort_size=verified_cohort_size)
        self._sessions[session.session_id] = session
        self._contexts[id(context)] = context
        return SecurityAccess(self, session, context)

    def revoke(self, session):
        self._sessions.pop(session.session_id, None)

    def evaluate(self, session, resource_id, action, context):
        def decision(value, reason, rule):
            return PolicyDecision(decision=value, reason=reason, policy_id=POLICY_VERSION+'/'+rule)
        if (session is None or self._sessions.get(session.session_id) is not session
            or session.expires_at <= datetime.now(timezone.utc)
            or self._contexts.get(id(context)) is not context):
            return decision('deny', 'trusted_identity_required', 'identity')
        resource = RESOURCES.get(resource_id)
        if resource is None:
            return decision('deny', 'unknown_resource', 'default-deny')
        if action not in ('read', 'retrieve', 'aggregate', 'export', 'write'):
            return decision('deny', 'unknown_action', 'default-deny')
        roles = session.identity.roles
        if action == 'write':
            return decision('deny', 'operation_not_permitted', 'read-only')
        if action == 'export':
            if resource_id == 'bank.aggregate' and 'analyst' in roles and 'aggregates' in context.scopes:
                return decision('requires_approval', 'human_review_required_no_approval_implemented', 'export')
            return decision('deny', 'export_not_permitted', 'export')
        if resource_id == 'docs.public' and action in ('read', 'retrieve'):
            return decision('allow', 'shared_definition', 'public-docs')
        if resource_id.startswith('catalog.') and action in ('read', 'retrieve'):
            if 'catalog' in context.scopes and set(roles) & {'steward', 'analyst'}:
                return decision('allow', 'authorized_catalog', 'catalog')
        if resource_id == 'bank.aggregate' and action == 'aggregate' and 'analyst' in roles:
            if context.purpose == 'aggregate_reporting' and 'aggregates' in context.scopes:
                if context.verified_cohort_size is not None and context.verified_cohort_size >= 10:
                    return decision('allow', 'verified_cohort_at_least_10', 'aggregate')
                return decision('deny', 'small_or_unverified_cohort', 'aggregate')
        if resource_id == 'bank.account' and action == 'read' and 'support' in roles:
            if (context.purpose == 'account_support' and context.account_scope is not None
                and context.account_scope in context.scopes):
                return decision('allow', 'account_within_host_verified_scope', 'account')
            return decision('deny', 'account_outside_scope', 'account')
        return decision('deny', 'role_resource_or_action_not_permitted', 'default-deny')


class SecurityAccess:
    def __init__(self, engine, session=None, context=None):
        self.engine, self.session, self.context = engine, session, context
        self.request_id = uuid4()

    def begin_request(self):
        self.request_id = uuid4()

    def run(self, resource, action, operation=None, *, agent='data_steward', tool='search_data_catalog'):
        start = monotonic()
        decision = self.engine.evaluate(self.session, resource, action, self.context)
        identity = self.session.identity if self.session and self.engine._sessions.get(self.session.session_id) is self.session else None
        def record(outcome):
            self.engine.events.append(AuditEvent(request_id=self.request_id,
                pseudonym=identity.pseudonym if identity else 'anonymous', simulated=True,
                # Caller labels and unknown resources can contain sensitive text.
                agent=agent if agent in ('data_steward', 'data_analyst', 'data_quality', 'data_governance') else 'unknown',
                tool=tool if tool in ('search_data_catalog', 'agent_entry', 'retrieval', 'sql_operation') else 'unknown',
                resource=resource if resource in RESOURCES else 'unknown',
                action=action if action in ('read', 'retrieve', 'aggregate', 'export', 'write') else 'unknown',
                policy_id=decision.policy_id, decision=decision.decision, reason=decision.reason,
                timestamp=datetime.now(timezone.utc), duration_ms=(monotonic()-start)*1000, outcome=outcome))
        if decision.decision != 'allow':
            record('approval_required' if decision.decision == 'requires_approval' else 'denied')
            raise AuthorizationDenied(decision)
        if operation is None:
            record('allowed')
            return decision
        try:
            result = operation()
        except Exception:
            record('failed')
            raise
        record('completed')
        return result


def anonymous_access():
    return SecurityAccess(PolicyEngine())


def simulated_access(profile='steward_demo', *, account_scope=None, verified_cohort_size=None):
    """HOST-ONLY test issuer. Never expose profile/context issuance as an LLM tool.

    Cohort and account arguments represent verified host inputs in tests, not
    estimates or identifiers accepted from generated SQL/chat. No real auth exists.
    """
    if profile not in PROFILES:
        raise ValueError('Unknown simulated profile')
    return PolicyEngine()._issue(profile, account_scope=account_scope,
        verified_cohort_size=verified_cohort_size)


class SecuredOperation:
    """Future SQL adapter seam: fixed host resource/action/context, no SQL engine."""
    def __init__(self, access, resource, action, operation):
        self._access = access or anonymous_access()
        self._resource, self._action, self._operation = resource, action, operation

    def invoke(self):
        return self._access.run(self._resource, self._action, self._operation,
            agent='data_analyst', tool='sql_operation')
