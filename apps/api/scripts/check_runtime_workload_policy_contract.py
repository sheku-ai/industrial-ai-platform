import json
import uuid

from app.services.runtime_workload_policy import RuntimeWorkloadPolicy, WorkloadClassification, workload_policy_metrics


def classifier(organization_id, execution_type):
    mapping = {
        "document.ingestion": WorkloadClassification("standard", "ingestion-standard"),
        "document.ingestion.heavy": WorkloadClassification("heavy", "ingestion-heavy"),
        "knowledge.enrichment": WorkloadClassification("optional_enrichment", "enrichment-optional"),
    }
    return mapping.get(execution_type, WorkloadClassification("default", "platform-default"))


def main():
    organization_id = uuid.uuid4()
    standard_policy = RuntimeWorkloadPolicy(
        classifier,
        accepted_queue_keys={"ingestion-standard", "platform-default"},
    )
    heavy_policy = RuntimeWorkloadPolicy(
        classifier,
        accepted_queue_keys={"ingestion-heavy"},
    )
    enrichment_policy = RuntimeWorkloadPolicy(
        classifier,
        accepted_queue_keys={"enrichment-optional"},
    )
    unrestricted_policy = RuntimeWorkloadPolicy(classifier)

    standard = standard_policy.evaluate(organization_id, "document.ingestion")
    heavy_rejected = standard_policy.evaluate(organization_id, "document.ingestion.heavy")
    heavy = heavy_policy.evaluate(organization_id, "document.ingestion.heavy")
    enrichment = enrichment_policy.evaluate(organization_id, "knowledge.enrichment")
    default = standard_policy.evaluate(organization_id, None)
    unrestricted = unrestricted_policy.evaluate(organization_id, "knowledge.enrichment")

    checks = {
        "standard_queue_admitted": standard.admitted and standard.classification.workload_class == "standard",
        "heavy_queue_isolated": not heavy_rejected.admitted and heavy_rejected.reason == "workload_queue_not_accepted",
        "heavy_worker_accepts_heavy_queue": heavy.admitted and heavy.classification.queue_key == "ingestion-heavy",
        "optional_enrichment_isolated": enrichment.admitted
        and enrichment.classification.workload_class == "optional_enrichment",
        "default_queue_supported": default.admitted and default.classification.queue_key == "platform-default",
        "unrestricted_policy_preserves_compatibility": unrestricted.admitted,
        "metrics_expose_class_and_queue": workload_policy_metrics(heavy)
        == {
            "workload_admitted": True,
            "workload_reason": "workload_queue_admitted",
            "workload_class": "heavy",
            "workload_queue_key": "ingestion-heavy",
        },
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
