from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.core import Organization


def create_integration_organization(
    session: Session,
    *,
    organization_id: UUID | None = None,
    label: str = "integration",
) -> Organization:
    identifier = organization_id or uuid4()
    organization = Organization(
        id=identifier,
        slug=f"{label}-{identifier}",
        name=f"Integration {identifier}",
        description="Ephemeral integration validation organization",
        status="active",
        config={"validation": True},
    )
    session.add(organization)
    session.flush()
    return organization


def delete_integration_organization(session: Session, organization_id: UUID) -> None:
    organization = session.get(Organization, organization_id)
    if organization is not None:
        session.delete(organization)
        session.flush()
