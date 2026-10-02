from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.protected_document_runtime_adapter import (
    ProtectedDocumentRuntimeAdapter,
    ProtectedDocumentRuntimeError,
)
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem
from app.services.secret_store import InMemorySecretStore, SecretNotFound, SecretValue


class StubDelegate:
    execution_type = "document.ingestion"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen_password = None

    def execute(self, item, heartbeat):
        self.seen_password = item.input_payload["options"]["document_password"]
        if self.fail:
            raise RuntimeError("failed")
        return RuntimeAdapterResult(metrics={"delegate": True})


class StubSession:
    def __init__(self, case) -> None:
        self.case = case
        self.added = []

    def scalar(self, statement):
        return self.case

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class StubHeartbeat:
    pass


def make_case(review_id):
    return SimpleNamespace(
        id=review_id,
        organization_id=uuid4(),
        status="approved_for_processing",
        resolved_at=None,
        secret_reference="secret://review/one",
        secret_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def make_item(secret_reference: str | None = "secret://review/one") -> RuntimeWorkItem:
    review_id = uuid4()
    payload = {
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "pipeline_profile_id": str(uuid4()),
        "source_reference": "memory://protected.pdf",
        "declared_media_type": "application/pdf",
        "original_file_name": "protected.pdf",
        "options": {},
    }
    if secret_reference is not None:
        payload.update(
            {
                "protected_document": True,
                "review_case_id": str(review_id),
                "secret_reference": secret_reference,
            }
        )
    return RuntimeWorkItem(
        organization_id=uuid4(),
        execution_id=uuid4(),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        input_payload=payload,
        policy_snapshot={},
    )


def test_unprotected_execution_passes_through() -> None:
    delegate = StubDelegate()
    adapter = ProtectedDocumentRuntimeAdapter(
        delegate,
        secret_store=InMemorySecretStore(),
        session_factory=lambda: StubSession(None),
    )
    item = make_item(secret_reference=None)
    item.input_payload["options"]["document_password"] = "existing"

    result = adapter.execute(item, StubHeartbeat())

    assert result.metrics["delegate"] is True
    assert delegate.seen_password == "existing"


def test_secret_is_resolved_only_in_worker_memory_and_consumed() -> None:
    store = InMemorySecretStore()
    reference = "secret://review/one"
    store.put(
        reference,
        SecretValue(
            value="temporary-password",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            single_use=True,
        ),
    )
    delegate = StubDelegate()
    item = make_item(reference)
    case = make_case(item.input_payload["review_case_id"])
    adapter = ProtectedDocumentRuntimeAdapter(
        delegate,
        secret_store=store,
        session_factory=lambda: StubSession(case),
    )

    result = adapter.execute(item, StubHeartbeat())

    assert delegate.seen_password == "temporary-password"
    assert result.metrics["secret_value_persisted"] is False
    assert case.status == "resolved"
    assert case.secret_reference is None
    with pytest.raises(SecretNotFound):
        store.inspect(reference)


def test_missing_secret_produces_controlled_error() -> None:
    item = make_item("secret://missing")
    case = make_case(item.input_payload["review_case_id"])
    adapter = ProtectedDocumentRuntimeAdapter(
        StubDelegate(),
        secret_store=InMemorySecretStore(),
        session_factory=lambda: StubSession(case),
    )

    with pytest.raises(ProtectedDocumentRuntimeError, match="not found"):
        adapter.execute(item, StubHeartbeat())
    assert case.status == "pending_human_review"
