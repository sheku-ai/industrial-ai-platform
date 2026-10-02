from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.assistant_runtime import AssistantRuntimeRun
from app.services.assistant_execution_evidence_reader import read_assistant_execution_evidence_v1


def _run(organization_id: uuid.UUID, assistant_run_id: uuid.UUID) -> AssistantRuntimeRun:
    now = datetime.now(UTC)
    return AssistantRuntimeRun(
        assistant_run_id=assistant_run_id,
        organization_id=organization_id,
        ownership_scope="organization",
        data_origin="operational",
        assistant_id=uuid.uuid4(),
        assistant_session_id=uuid.uuid4(),
        run_status="completed",
        requested_query="maintenance procedure",
        selected_search_mode="enterprise_search",
        selected_runtime_domain="enterprise_search",
        execution_state="completed",
        started_at=now,
        completed_at=now,
        runtime_metadata={"source": "postgresql"},
        created_at=now,
        updated_at=now,
    )


def test_reader_projects_scoped_run() -> None:
    organization_id = uuid.uuid4()
    assistant_run_id = uuid.uuid4()
    session = MagicMock(spec=Session)
    session.scalar.return_value = _run(organization_id, assistant_run_id)

    evidence = read_assistant_execution_evidence_v1(
        session,
        organization_id=organization_id,
        assistant_run_id=assistant_run_id,
    )

    assert evidence is not None
    assert evidence.assistant_run_id == assistant_run_id
    assert evidence.organization_id == organization_id

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert assistant_run_id.hex in compiled
    assert organization_id.hex in compiled
    assert "assistant_runtime_runs.ownership_scope" in compiled


def test_reader_returns_none_without_scoped_run() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    assert (
        read_assistant_execution_evidence_v1(
            session,
            organization_id=uuid.uuid4(),
            assistant_run_id=uuid.uuid4(),
        )
        is None
    )


def test_reader_rejects_scope_mismatch_from_persisted_row() -> None:
    requested_organization_id = uuid.uuid4()
    run = _run(uuid.uuid4(), uuid.uuid4())
    session = MagicMock(spec=Session)
    session.scalar.return_value = run

    try:
        read_assistant_execution_evidence_v1(
            session,
            organization_id=requested_organization_id,
            assistant_run_id=run.assistant_run_id,
        )
    except ValueError as exc:
        assert "requested organization scope" in str(exc)
    else:
        raise AssertionError("organization scope mismatch was not rejected")
