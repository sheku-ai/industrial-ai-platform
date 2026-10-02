#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.security.context import (  # noqa: E402
    ActorContext,
    ActorScope,
    ActorType,
    AuthenticationAssurance,
    AuthenticationMethod,
    DenyAllRequestContextResolver,
    OrganizationContext,
    RequestContext,
    RequestSource,
    SecurityContextUnavailable,
    build_internal_service_context,
)


def expect_validation_error(factory) -> None:
    try:
        factory()
    except ValidationError:
        return
    raise AssertionError("expected ValidationError")


def main() -> int:
    organization_id = uuid.uuid4()
    organization = OrganizationContext(
        organization_id=organization_id,
        organization_path=(organization_id,),
        membership_source="smoke-test",
    )

    context = build_internal_service_context(
        service_identity="smoke-service",
        correlation_id="smoke-18-2",
        organization=organization,
        roles=frozenset({"test-runner"}),
        permission_claims=frozenset({"context.validate"}),
        source=RequestSource.INTERNAL,
    )

    assert context.actor.actor_type == ActorType.SERVICE
    assert context.actor.scope == ActorScope.ORGANIZATION
    assert context.organization is not None
    assert context.organization.organization_id == organization_id
    assert context.authentication_method == AuthenticationMethod.INTERNAL

    expect_validation_error(
        lambda: RequestContext(
            correlation_id="missing-org",
            actor=ActorContext(
                actor_id="actor-1",
                actor_type=ActorType.HUMAN,
                subject="subject-1",
                scope=ActorScope.ORGANIZATION,
                authentication_assurance=AuthenticationAssurance.STANDARD,
            ),
            organization=None,
            authentication_method=AuthenticationMethod.BEARER,
            source=RequestSource.API,
        )
    )

    expect_validation_error(
        lambda: ActorContext(
            actor_id="anonymous",
            actor_type=ActorType.HUMAN,
            subject="anonymous",
            roles=frozenset({"admin"}),
            scope=ActorScope.PLATFORM,
            authentication_assurance=AuthenticationAssurance.UNAUTHENTICATED,
        )
    )

    expect_validation_error(
        lambda: ActorContext(
            actor_id="service-without-identity",
            actor_type=ActorType.SERVICE,
            subject="service-without-identity",
            scope=ActorScope.PLATFORM,
            authentication_assurance=AuthenticationAssurance.STRONG,
        )
    )

    try:
        DenyAllRequestContextResolver().resolve(object())
    except SecurityContextUnavailable:
        fail_closed = True
    else:
        fail_closed = False

    assert fail_closed is True

    print(
        json.dumps(
            {
                "status": "passed",
                "contract": "RequestContext",
                "organization_scope_required": True,
                "service_identity_required": True,
                "unauthenticated_claims_rejected": True,
                "default_resolver": "deny_all",
                "provider_execution_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
