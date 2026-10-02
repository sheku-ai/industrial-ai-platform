from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.core import Organization


def ephemeral_organization_config(
    *,
    test_suite: str,
    run_id: str,
    ttl_hours: int = 24,
) -> dict[str, str]:
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    return {
        "lifecycle": "ephemeral",
        "environment": "test",
        "test_suite": test_suite,
        "run_id": run_id,
        "expires_at": expires_at.isoformat(),
    }


def create_ephemeral_organization(
    session: Session,
    *,
    slug_prefix: str,
    name: str,
    test_suite: str,
    organization_id: UUID | None = None,
    run_id: str | None = None,
) -> Organization:
    identifier = organization_id or uuid4()
    resolved_run_id = run_id or identifier.hex
    organization = Organization(
        id=identifier,
        slug=f"{slug_prefix}-{identifier.hex}",
        name=name,
        status="active",
        config=ephemeral_organization_config(
            test_suite=test_suite,
            run_id=resolved_run_id,
        ),
    )
    session.add(organization)
    return organization
