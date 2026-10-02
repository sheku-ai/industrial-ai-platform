import json
import uuid

from app.services.knowledge_artifact_runtime_adapter import KnowledgeArtifactRuntimeAdapter
from app.services.multimodal_observability import visual_artifact_metrics
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem
from app.services.visual_enrichment_runtime_adapter import VisualEnrichmentRuntimeAdapter


class Delegate:
    execution_type = "document.ingestion"

    def __init__(self, revision_id):
        self.revision_id = revision_id

    def execute(self, item, heartbeat):
        return RuntimeAdapterResult(
            metrics={"processing_revision_id": str(self.revision_id)},
            continue_execution=False,
        )


class Producer:
    def produce(self, item, heartbeat):
        return {
            "schema": "visual-enrichment/v1",
            "items": [
                {
                    "image_hash": "image-1",
                    "visual": {
                        "status": "succeeded",
                        "provider_key": "provider-a",
                    },
                },
                {
                    "image_hash": "image-2",
                    "visual": {
                        "status": "partial",
                        "provider_key": "provider-a",
                    },
                },
                {
                    "image_hash": "image-3",
                    "visual": {
                        "status": "failed",
                        "provider_key": "provider-b",
                    },
                },
            ],
        }


class Publisher:
    def __init__(self):
        self.calls = 0

    def publish(self, **kwargs):
        self.calls += 1
        return uuid.uuid4()


class KnowledgePublisher:
    def publish(self, **kwargs):
        return uuid.uuid4()


class Indexer:
    def __init__(self, revision_id):
        self.revision_id = revision_id

    def run(self, **kwargs):
        return {
            "visual_chunk_indexing_connected": True,
            "visual_chunk_indexing_failed": False,
            "visual_chunks_created": 2,
            "visual_chunks_existing": 0,
            "visual_chunks_requested": 2,
            "visual_text_chunks_available": 4,
            "visual_chunk_indexing_duration_ms": 3,
            "visual_chunk_provider_counts": {"provider-a": 2},
            "visual_chunk_status_counts": {"partial": 1, "succeeded": 1},
            "multimodal_processing_revision_id": str(self.revision_id),
        }


class FailingIndexer:
    def run(self, **kwargs):
        raise RuntimeError("indexing unavailable")


class Heartbeat:
    def __init__(self):
        self.pulses = 0
        self.checkpoints = 0

    def pulse(self):
        self.pulses += 1

    def checkpoint(self):
        self.checkpoints += 1


def _item(revision_id):
    organization_id = uuid.uuid4()
    document_version_id = uuid.uuid4()
    return RuntimeWorkItem(
        organization_id=organization_id,
        execution_id=uuid.uuid4(),
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=document_version_id,
        attempt_id=uuid.uuid4(),
        attempt_number=1,
        lease_token=uuid.uuid4(),
        input_payload={"document_version_id": str(document_version_id)},
        policy_snapshot={},
    )


def main():
    revision_id = uuid.uuid4()
    item = _item(revision_id)
    artifact = Producer().produce(item, Heartbeat())
    summary = visual_artifact_metrics(artifact)

    visual_publisher = Publisher()
    enrichment_result = VisualEnrichmentRuntimeAdapter(
        Delegate(revision_id),
        Producer(),
        visual_publisher,
    ).execute(item, Heartbeat())

    indexing_result = KnowledgeArtifactRuntimeAdapter(
        Delegate(revision_id),
        KnowledgePublisher(),
        Indexer(revision_id),
    ).execute(item, Heartbeat())

    degraded_result = KnowledgeArtifactRuntimeAdapter(
        Delegate(revision_id),
        KnowledgePublisher(),
        FailingIndexer(),
    ).execute(item, Heartbeat())

    checks = {
        "artifact_detected_count": summary["visual_items_detected"] == 3,
        "artifact_enriched_count": summary["visual_items_enriched"] == 2,
        "artifact_failed_count": summary["visual_items_failed"] == 1,
        "artifact_provider_counts": summary["visual_provider_counts"]
        == {
            "provider-a": 2,
            "provider-b": 1,
        },
        "artifact_status_degraded": summary["multimodal_flow_status"] == "degraded",
        "enrichment_metrics_propagated": (
            enrichment_result.metrics["visual_items_detected"] == 3
            and enrichment_result.metrics["visual_items_enriched"] == 2
            and enrichment_result.metrics["visual_enrichment_published"] is True
            and enrichment_result.metrics["visual_enrichment_duration_ms"] >= 0
        ),
        "revision_traceability_preserved": (
            enrichment_result.metrics["multimodal_processing_revision_id"] == str(revision_id)
            and indexing_result.metrics["multimodal_processing_revision_id"] == str(revision_id)
        ),
        "indexing_metrics_propagated": (
            indexing_result.metrics["visual_chunks_requested"] == 2
            and indexing_result.metrics["visual_chunks_created"] == 2
            and indexing_result.metrics["visual_text_chunks_available"] == 4
            and indexing_result.metrics["visual_chunk_provider_counts"] == {"provider-a": 2}
        ),
        "indexing_failure_observable": (
            degraded_result.metrics["visual_chunk_indexing_failed"] is True
            and degraded_result.metrics["visual_chunk_indexing_error_type"] == "RuntimeError"
            and degraded_result.metrics["multimodal_flow_status"] == "degraded"
            and degraded_result.metrics["visual_chunk_indexing_duration_ms"] >= 0
        ),
        "publication_called_once": visual_publisher.calls == 1,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
