from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.services import assistant_citation_verification_runtime as runtime


def test_citation_verification_resolves_persisted_assistant_execution(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    assistant_run_id = uuid.uuid4()
    evidence = SimpleNamespace(assistant_run_id=assistant_run_id)
    captured: dict[str, object] = {}

    def _reader(session, *, organization_id, assistant_run_id):
        captured["organization_id"] = organization_id
        captured["assistant_run_id"] = assistant_run_id
        return evidence

    monkeypatch.setattr(runtime, "read_assistant_execution_evidence_v1", _reader)

    resolved, issue = runtime._assistant_runtime_evidence(
        MagicMock(spec=Session),
        {
            "organization_id": str(uuid.uuid4()),
            "assistant_run_id": str(assistant_run_id),
        },
        organization_id=organization_id,
    )

    assert resolved is evidence
    assert issue is None
    assert captured == {
        "organization_id": organization_id,
        "assistant_run_id": assistant_run_id,
    }


def test_citation_verification_blocks_invalid_assistant_execution_lineage() -> None:
    resolved, issue = runtime._assistant_runtime_evidence(
        MagicMock(spec=Session),
        {
            "organization_id": str(uuid.uuid4()),
            "assistant_run_id": "not-a-uuid",
        },
        organization_id=uuid.uuid4(),
    )

    assert resolved is None
    assert issue is not None
    assert issue["code"] == "assistant_execution_lineage_invalid"
