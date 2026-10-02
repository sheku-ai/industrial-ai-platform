from __future__ import annotations

import uuid

from app.contracts.assistant_execution import AssistantExecutionEvidenceV1
from app.models.assistant_runtime import AssistantRuntimeRun


def project_assistant_execution_evidence_v1(
    run: AssistantRuntimeRun,
    *,
    organization_id: uuid.UUID,
) -> AssistantExecutionEvidenceV1:
    """Project persisted assistant execution evidence into the canonical v1 contract.

    The projection accepts only organization-owned ``AssistantRuntimeRun`` rows
    and validates the requested tenant against the persisted organization scope.
    Global or legacy-unscoped runs must never be inferred into an organization.
    """

    if run.ownership_scope != "organization":
        raise ValueError("assistant execution evidence requires organization ownership scope")
    if run.organization_id is None:
        raise ValueError("assistant execution evidence requires persisted organization_id")
    if run.organization_id != organization_id:
        raise ValueError("assistant execution evidence does not match requested organization scope")

    return AssistantExecutionEvidenceV1(
        assistant_run_id=run.assistant_run_id,
        organization_id=run.organization_id,
        assistant_id=run.assistant_id,
        assistant_session_id=run.assistant_session_id,
        ownership_scope=run.ownership_scope,
        data_origin=run.data_origin,
        run_status=run.run_status,
        requested_query=run.requested_query,
        selected_search_mode=run.selected_search_mode,
        selected_runtime_domain=run.selected_runtime_domain,
        execution_state=run.execution_state,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        failure_reason=run.failure_reason,
        created_at=run.created_at,
        updated_at=run.updated_at,
        runtime_metadata=dict(run.runtime_metadata or {}),
    )
