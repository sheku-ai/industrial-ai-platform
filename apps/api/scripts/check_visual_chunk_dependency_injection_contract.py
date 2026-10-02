from __future__ import annotations

import inspect
import json
from uuid import uuid4

from app.services.knowledge_artifact_runtime_adapter import KnowledgeArtifactRuntimeAdapter
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem
from app.workers import document_ingestion_factory


class Delegate:
    execution_type = "document.ingestion"

    def __init__(self, processing_revision_id):
        self.processing_revision_id = processing_revision_id

    def execute(self, item, heartbeat):
        return RuntimeAdapterResult(
            metrics={"processing_revision_id": str(self.processing_revision_id)},
            continue_execution=False,
        )


class PublicationService:
    def __init__(self, artifact_id):
        self.artifact_id = artifact_id
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        return self.artifact_id


class VisualChunkIndexingService:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "visual_chunk_indexing_connected": True,
            "visual_chunk_indexing_failed": False,
            "visual_chunks_created": 1,
            "visual_chunks_existing": 0,
        }


class Heartbeat:
    def __init__(self):
        self.pulses = 0

    def pulse(self):
        self.pulses += 1


def _work_item(document_version_id):
    return RuntimeWorkItem(
        organization_id=uuid4(),
        execution_id=uuid4(),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=document_version_id,
        attempt_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        input_payload={"document_version_id": str(document_version_id)},
        policy_snapshot={},
    )


def main() -> None:
    document_version_id = uuid4()
    processing_revision_id = uuid4()
    artifact_id = uuid4()
    item = _work_item(document_version_id)

    publication = PublicationService(artifact_id)
    visual_indexing = VisualChunkIndexingService()
    heartbeat = Heartbeat()
    adapter = KnowledgeArtifactRuntimeAdapter(
        Delegate(processing_revision_id),
        publication,
        visual_indexing,
    )
    result = adapter.execute(item, heartbeat)

    publication_without_private_dependencies = PublicationService(uuid4())
    optional_heartbeat = Heartbeat()
    optional_result = KnowledgeArtifactRuntimeAdapter(
        Delegate(processing_revision_id),
        publication_without_private_dependencies,
    ).execute(item, optional_heartbeat)

    adapter_source = inspect.getsource(KnowledgeArtifactRuntimeAdapter)
    factory_source = inspect.getsource(document_ingestion_factory.build_document_ingestion_adapter)

    checks = {
        "adapter_has_no_private_session_factory_access": "_session_factory" not in adapter_source,
        "adapter_has_no_private_visual_source_access": "_visual_source" not in adapter_source,
        "factory_constructs_visual_indexing_service": "RuntimeVisualChunkIndexingService(" in factory_source,
        "factory_injects_visual_indexing_service": "visual_chunk_indexing_service," in factory_source,
        "explicit_visual_indexing_called_once": len(visual_indexing.calls) == 1,
        "publication_called_once": len(publication.calls) == 1,
        "visual_metrics_propagated": result.metrics.get("visual_chunks_created") == 1,
        "visual_indexing_optional": optional_result.metrics.get("visual_chunk_indexing_connected") is False,
        "optional_path_does_not_require_private_dependencies": len(publication_without_private_dependencies.calls) == 1,
        "heartbeat_contract_preserved": heartbeat.pulses == 3 and optional_heartbeat.pulses == 3,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
