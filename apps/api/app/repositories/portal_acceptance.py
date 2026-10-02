from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.portal_acceptance import PortalAcceptanceEvidence


class PortalAcceptanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def scope_criteria(scope: str, organization_id: uuid.UUID | None) -> tuple[object, object]:
        return (
            PortalAcceptanceEvidence.scope == scope,
            PortalAcceptanceEvidence.organization_id.is_(None)
            if organization_id is None
            else PortalAcceptanceEvidence.organization_id == organization_id,
        )

    def find_identity(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        validation_run_code: str,
        validation_type: str,
    ) -> PortalAcceptanceEvidence | None:
        return self.db.scalar(
            select(PortalAcceptanceEvidence).where(
                *self.scope_criteria(scope, organization_id),
                PortalAcceptanceEvidence.validation_run_code == validation_run_code,
                PortalAcceptanceEvidence.validation_type == validation_type,
            )
        )

    def add(self, evidence: PortalAcceptanceEvidence) -> PortalAcceptanceEvidence:
        self.db.add(evidence)
        self.db.flush()
        return evidence

    def list_evidence(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        *,
        validation_run_code: str | None = None,
        validation_type: str | None = None,
    ) -> list[PortalAcceptanceEvidence]:
        statement = select(PortalAcceptanceEvidence).where(*self.scope_criteria(scope, organization_id))
        if validation_run_code:
            statement = statement.where(PortalAcceptanceEvidence.validation_run_code == validation_run_code)
        if validation_type:
            statement = statement.where(PortalAcceptanceEvidence.validation_type == validation_type)
        return list(
            self.db.scalars(
                statement.order_by(
                    PortalAcceptanceEvidence.observed_at.desc(),
                    PortalAcceptanceEvidence.created_at.desc(),
                )
            ).all()
        )

    def latest_run_code(self, scope: str, organization_id: uuid.UUID | None) -> str | None:
        return self.db.scalar(
            select(PortalAcceptanceEvidence.validation_run_code)
            .where(*self.scope_criteria(scope, organization_id))
            .order_by(
                PortalAcceptanceEvidence.observed_at.desc(),
                PortalAcceptanceEvidence.created_at.desc(),
            )
            .limit(1)
        )
