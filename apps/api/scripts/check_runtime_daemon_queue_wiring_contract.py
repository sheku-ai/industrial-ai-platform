import inspect
import json
import uuid

from app.workers import runtime_daemon


def main():
    organization_id = uuid.uuid4()

    default_policy = runtime_daemon.build_workload_policy(
        execution_type="document.ingestion",
        queue_key="platform-default",
        accepted_queue_keys=None,
    )
    default_classification = runtime_daemon.validate_workload_assignment(
        default_policy,
        organization_id,
        "document.ingestion",
    )

    scoped_policy = runtime_daemon.build_workload_policy(
        execution_type="document.ingestion.heavy",
        queue_key="ingestion-heavy",
        accepted_queue_keys="ingestion-heavy,enrichment-optional",
    )
    scoped_classification = runtime_daemon.validate_workload_assignment(
        scoped_policy,
        organization_id,
        "document.ingestion.heavy",
    )

    rejected = False
    rejected_policy = runtime_daemon.build_workload_policy(
        execution_type="document.ingestion.heavy",
        queue_key="ingestion-heavy",
        accepted_queue_keys="ingestion-standard",
    )
    try:
        runtime_daemon.validate_workload_assignment(
            rejected_policy,
            organization_id,
            "document.ingestion.heavy",
        )
    except RuntimeError:
        rejected = True

    source = inspect.getsource(runtime_daemon)
    checks = {
        "default_execution_type_preserved": 'WORKER_EXECUTION_TYPE", "document.ingestion' in source,
        "default_queue_preserves_compatibility": default_classification.queue_key == "platform-default",
        "configured_queue_admitted": scoped_classification.queue_key == "ingestion-heavy",
        "configured_workload_class_traceable": scoped_classification.workload_class == "document_ingestion_heavy",
        "foreign_queue_rejected_before_worker_build": rejected,
        "accepted_queue_keys_configurable": "WORKER_ACCEPTED_QUEUE_KEYS" in source,
        "queue_key_configurable": "WORKER_QUEUE_KEY" in source,
        "execution_type_forwarded_once": "worker.run_once(organization_id, execution_type=args.execution_type)"
        in source,
        "hardcoded_runtime_execution_removed": 'execution_type="document.ingestion")' not in source,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
