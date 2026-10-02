from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.release_operational_evidence import ReleaseOperationalEvidence


class ReleaseOperationalEvidenceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_execution(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        evidence_type: str,
        execution_key: str,
    ) -> ReleaseOperationalEvidence | None:
        return self.db.scalar(
            select(ReleaseOperationalEvidence).where(
                ReleaseOperationalEvidence.scope == scope,
                ReleaseOperationalEvidence.organization_id.is_(None)
                if organization_id is None
                else ReleaseOperationalEvidence.organization_id == organization_id,
                ReleaseOperationalEvidence.evidence_type == evidence_type,
                ReleaseOperationalEvidence.execution_key == execution_key,
            )
        )

    def get(self, evidence_id: uuid.UUID) -> ReleaseOperationalEvidence | None:
        return self.db.get(ReleaseOperationalEvidence, evidence_id)

    def latest(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        evidence_type: str,
    ) -> ReleaseOperationalEvidence | None:
        return self.db.scalar(
            select(ReleaseOperationalEvidence)
            .where(
                ReleaseOperationalEvidence.scope == scope,
                ReleaseOperationalEvidence.organization_id.is_(None)
                if organization_id is None
                else ReleaseOperationalEvidence.organization_id == organization_id,
                ReleaseOperationalEvidence.evidence_type == evidence_type,
            )
            .order_by(ReleaseOperationalEvidence.evaluated_at.desc())
            .limit(1)
        )
