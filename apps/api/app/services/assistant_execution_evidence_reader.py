from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.assistant_execution import AssistantExecutionEvidenceV1
from app.models.assistant_runtime import AssistantRuntimeRun
from app.services.assistant_execution_contract_projection import project_assistant_execution_evidence_v1


def read_assistant_execution_evidence_v1(
    session: Session,
    *,
    organization_id: uuid.UUID,
    assistant_run_id: uuid.UUID,
) -> AssistantExecutionEvidenceV1 | None:
    """Read organization-scoped assistant execution evidence from PostgreSQL."""

    run = session.scalar(
        select(AssistantRuntimeRun).where(
            AssistantRuntimeRun.assistant_run_id == assistant_run_id,
            AssistantRuntimeRun.organization_id == organization_id,
            AssistantRuntimeRun.ownership_scope == "organization",
        )
    )
    if run is None:
        return None

    return project_assistant_execution_evidence_v1(run, organization_id=organization_id)
