#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.security.authorization import AuthorizationRequest, DefaultPolicyEvaluator
from app.security.context import ActorScope, ActorType, AuthenticationAssurance, AuthenticationMethod, RequestSource
from app.security.identity import ResolvedPrincipal, build_request_context


def main() -> int:
    organization_id = uuid.uuid4()
    principal = ResolvedPrincipal(
        subject="smoke-actor",
        actor_id="smoke-actor",
        actor_type=ActorType.HUMAN,
        organization_id=organization_id,
        organization_path=(organization_id,),
        permission_claims=frozenset({"documents.read", "knowledge.*"}),
        scope=ActorScope.ORGANIZATION,
        method=AuthenticationMethod.BEARER,
        assurance=AuthenticationAssurance.STANDARD,
    )
    context = build_request_context(principal, correlation_id="smoke-18-4", source=RequestSource.API)
    evaluator = DefaultPolicyEvaluator()

    exact = evaluator.evaluate(context, AuthorizationRequest(resource="documents", action="read", resource_organization_id=organization_id))
    missing = evaluator.evaluate(context, AuthorizationRequest(resource="documents", action="delete", resource_organization_id=organization_id))
    wildcard = evaluator.evaluate(context, AuthorizationRequest(resource="knowledge", action="search", resource_organization_id=organization_id))

    assert exact.allowed is True
    assert missing.allowed is False
    assert wildcard.allowed is True

    print(json.dumps({
        "status": "passed",
        "contract": "PolicyEvaluator",
        "exact_claim": True,
        "missing_claim_denied": True,
        "resource_wildcard": True,
        "provider_execution_enabled": False
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
