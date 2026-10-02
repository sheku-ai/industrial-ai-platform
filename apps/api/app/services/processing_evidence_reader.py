from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.processing import ProcessingEvidenceV1
from app.models.processing import ProcessingRevision
from app.services.processing_contract_projection import project_processing_evidence_v1


def read_processing_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    evidence_id: uuid.UUID,
) -> ProcessingEvidenceV1 | None:
    """Read canonical processing evidence from authoritative persisted state.

    Organization scope is part of the PostgreSQL lookup. A caller cannot read a
    processing revision by identifier alone and then apply tenancy filtering in
    memory.
    """

    revision = session.scalar(
        select(ProcessingRevision).where(
            ProcessingRevision.id == evidence_id,
            ProcessingRevision.organization_id == organization_id,
        )
    )
    if revision is None:
        return None
    return project_processing_evidence_v1(revision)
