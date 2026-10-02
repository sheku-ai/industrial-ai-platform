import uuid

from app.security.authorization import AuthorizationRequest, DefaultPolicyEvaluator
from app.security.context import ActorScope, ActorType, AuthenticationAssurance, AuthenticationMethod, RequestSource
from app.security.identity import ResolvedPrincipal, build_request_context


def _context(organization_id: uuid.UUID):
    principal = ResolvedPrincipal(
        subject="actor-a",
        actor_id="actor-a",
        actor_type=ActorType.HUMAN,
        organization_id=organization_id,
        organization_path=(organization_id,),
        permission_claims=frozenset({"documents.read", "knowledge.*"}),
        scope=ActorScope.ORGANIZATION,
        method=AuthenticationMethod.BEARER,
        assurance=AuthenticationAssurance.STANDARD,
    )
    return build_request_context(principal, correlation_id="unit-test", source=RequestSource.API)


def test_exact_permission_allows() -> None:
    organization_id = uuid.uuid4()
    decision = DefaultPolicyEvaluator().evaluate(
        _context(organization_id),
        AuthorizationRequest(resource="documents", action="read", resource_organization_id=organization_id),
    )
    assert decision.allowed is True


def test_cross_organization_access_denies() -> None:
    decision = DefaultPolicyEvaluator().evaluate(
        _context(uuid.uuid4()),
        AuthorizationRequest(resource="documents", action="read", resource_organization_id=uuid.uuid4()),
    )
    assert decision.allowed is False
    assert decision.reason == "cross_organization_access_denied"
