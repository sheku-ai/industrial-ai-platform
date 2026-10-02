"""PostgreSQL-authoritative RuntimeRun claim and recovery fencing."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantLlmExecution, AssistantRuntimeRun

_LEASE_INTERVAL = text("clock_timestamp() + interval '5 minutes'")


def initialize_chat_run_claim(db: Session, run: AssistantRuntimeRun) -> int:
    owner = uuid.uuid4()
    generation = db.scalar(
        update(AssistantRuntimeRun)
        .where(
            AssistantRuntimeRun.assistant_run_id == run.assistant_run_id,
            AssistantRuntimeRun.recovery_state.is_(None),
        )
        .values(
            recovery_state="claimed",
            recovery_owner=owner,
            recovery_lease_expires_at=_LEASE_INTERVAL,
            recovery_generation=1,
        )
        .returning(AssistantRuntimeRun.recovery_generation)
    )
    if generation != 1:
        raise RuntimeError("new chat RuntimeRun claim could not be persisted")
    db.expire(run)
    return generation


def _uncertain_provider_exists(run_id: uuid.UUID) -> Any:
    return exists(
        select(AssistantLlmExecution.llm_execution_id).where(
            AssistantLlmExecution.request_payload_metadata["assistant_run_id"].astext == str(run_id),
            AssistantLlmExecution.provider_call_started_at.is_not(None),
            AssistantLlmExecution.provider_call_finished_at.is_(None),
        )
    )


def attempt_chat_run_takeover(
    db: Session,
    *,
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    assistant_session_id: uuid.UUID,
) -> int | None:
    generation = db.scalar(
        update(AssistantRuntimeRun)
        .where(
            AssistantRuntimeRun.assistant_run_id == run_id,
            AssistantRuntimeRun.organization_id == organization_id,
            AssistantRuntimeRun.assistant_id == assistant_id,
            AssistantRuntimeRun.assistant_session_id == assistant_session_id,
            AssistantRuntimeRun.ownership_scope == "organization",
            AssistantRuntimeRun.recovery_state == "claimed",
            AssistantRuntimeRun.recovery_lease_expires_at <= func.clock_timestamp(),
            ~_uncertain_provider_exists(run_id),
        )
        .values(
            recovery_owner=uuid.uuid4(),
            recovery_lease_expires_at=_LEASE_INTERVAL,
            recovery_generation=AssistantRuntimeRun.recovery_generation + 1,
        )
        .returning(AssistantRuntimeRun.recovery_generation)
        .execution_options(synchronize_session=False)
    )
    return int(generation) if generation is not None else None


def mark_expired_provider_uncertain(
    db: Session,
    *,
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    assistant_session_id: uuid.UUID,
) -> bool:
    changed = db.scalar(
        update(AssistantRuntimeRun)
        .where(
            AssistantRuntimeRun.assistant_run_id == run_id,
            AssistantRuntimeRun.organization_id == organization_id,
            AssistantRuntimeRun.assistant_id == assistant_id,
            AssistantRuntimeRun.assistant_session_id == assistant_session_id,
            AssistantRuntimeRun.ownership_scope == "organization",
            AssistantRuntimeRun.recovery_state == "claimed",
            AssistantRuntimeRun.recovery_lease_expires_at <= func.clock_timestamp(),
            _uncertain_provider_exists(run_id),
        )
        .values(
            recovery_state="uncertain",
            recovery_owner=None,
            recovery_lease_expires_at=None,
            run_status="blocked",
            execution_state="blocked",
            failure_reason="Provider call started without a persisted outcome; manual review required.",
        )
        .returning(AssistantRuntimeRun.assistant_run_id)
        .execution_options(synchronize_session=False)
    )
    return changed is not None


def lock_current_provider_claim(
    db: Session,
    *,
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    assistant_id: uuid.UUID,
    assistant_session_id: uuid.UUID,
    generation: int,
) -> bool:
    run = db.scalar(
        select(AssistantRuntimeRun)
        .where(
            AssistantRuntimeRun.assistant_run_id == run_id,
            AssistantRuntimeRun.organization_id == organization_id,
            AssistantRuntimeRun.assistant_id == assistant_id,
            AssistantRuntimeRun.assistant_session_id == assistant_session_id,
            AssistantRuntimeRun.ownership_scope == "organization",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        return False
    database_now = db.scalar(select(func.clock_timestamp()))
    lease_valid = bool(run.recovery_lease_expires_at and run.recovery_lease_expires_at > database_now)
    return bool(
        run.recovery_state == "claimed"
        and run.recovery_owner is not None
        and run.recovery_generation == generation
        and lease_valid
    )
