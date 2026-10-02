from types import SimpleNamespace
from uuid import uuid4

from app.services.document_ingestion_status import DocumentIngestionStatusAdapter
from app.services.runtime_worker import RuntimeAdapterResult


class State:
    def __init__(self):
        self.calls = []

    def mark_processing(self, organization_id, document_version_id, *, execution_id):
        self.calls.append("processing")

    def mark_indexed(self, organization_id, document_version_id, *, execution_id):
        self.calls.append("indexed")

    def mark_failed(self, organization_id, document_version_id, *, execution_id):
        self.calls.append("failed")


class Delegate:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def execute(self, item, heartbeat):
        if self.should_fail:
            raise ValueError("delegate error")
        return RuntimeAdapterResult(metrics={"ok": True})


def _item():
    return SimpleNamespace(
        organization_id=uuid4(),
        subject_id=uuid4(),
        execution_id=uuid4(),
    )


def test_success_state_sequence():
    state = State()
    result = DocumentIngestionStatusAdapter(Delegate(), state).execute(_item(), object())
    assert result.metrics == {
        "ok": True,
        "partial_availability_connected": True,
        "document_availability": "complete",
    }
    assert state.calls == ["processing", "indexed"]


def test_failure_state_sequence():
    state = State()
    try:
        DocumentIngestionStatusAdapter(Delegate(True), state).execute(_item(), object())
    except ValueError as exc:
        assert str(exc) == "delegate error"
    else:
        raise AssertionError("delegate error was not propagated")
    assert state.calls == ["processing", "failed"]
