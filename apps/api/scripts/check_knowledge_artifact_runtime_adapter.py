import json
import uuid

from app.services.knowledge_artifact_runtime_adapter import KnowledgeArtifactRuntimeAdapter
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem


class FakeDelegate:
    execution_type = "document.ingestion"

    def __init__(self, *, continue_execution=False):
        self.continue_execution = continue_execution
        self.calls = 0

    def execute(self, item, heartbeat):
        self.calls += 1
        return RuntimeAdapterResult(
            metrics={"processing_revision_id": str(uuid.UUID(int=9)), "delegate_ok": True},
            continue_execution=self.continue_execution,
        )


class FakePublicationService:
    def __init__(self):
        self.calls = []
        self.artifact_id = uuid.UUID(int=10)

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        return self.artifact_id


class FakeHeartbeat:
    def __init__(self):
        self.pulses = 0

    def pulse(self):
        self.pulses += 1


def work_item():
    document_version_id = uuid.UUID(int=4)
    return RuntimeWorkItem(
        organization_id=uuid.UUID(int=1),
        execution_id=uuid.UUID(int=2),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=document_version_id,
        attempt_id=uuid.UUID(int=3),
        attempt_number=1,
        lease_token=uuid.UUID(int=5),
        input_payload={"document_version_id": str(document_version_id)},
        policy_snapshot={},
    )


def main():
    delegate = FakeDelegate()
    publication = FakePublicationService()
    heartbeat = FakeHeartbeat()
    adapter = KnowledgeArtifactRuntimeAdapter(delegate, publication)
    item = work_item()
    result = adapter.execute(item, heartbeat)

    continuing_delegate = FakeDelegate(continue_execution=True)
    continuing_publication = FakePublicationService()
    continuing_heartbeat = FakeHeartbeat()
    continuing_result = KnowledgeArtifactRuntimeAdapter(
        continuing_delegate,
        continuing_publication,
    ).execute(item, continuing_heartbeat)

    invalid_delegate_rejected = False
    try:
        KnowledgeArtifactRuntimeAdapter(object(), publication)
    except ValueError:
        invalid_delegate_rejected = True

    call = publication.calls[0]
    checks = {
        "delegate_called": delegate.calls == 1,
        "publication_called": len(publication.calls) == 1,
        "organization_preserved": call["organization_id"] == item.organization_id,
        "execution_preserved": call["execution_id"] == item.execution_id,
        "attempt_preserved": call["attempt_id"] == item.attempt_id,
        "document_version_preserved": call["document_version_id"] == item.subject_id,
        "processing_revision_preserved": call["processing_revision_id"] == uuid.UUID(int=9),
        "metrics_merged": (
            result.metrics.get("delegate_ok") is True
            and result.metrics.get("knowledge_artifact_publication_connected") is True
            and result.metrics.get("knowledge_artifact_id") == str(publication.artifact_id)
        ),
        "heartbeat_bracketed": heartbeat.pulses == 2,
        "continuation_not_published": (
            continuing_result.continue_execution is True
            and len(continuing_publication.calls) == 0
            and continuing_heartbeat.pulses == 0
        ),
        "invalid_delegate_rejected": invalid_delegate_rejected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
