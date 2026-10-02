from __future__ import annotations

import inspect
import json

from app.workers import runtime_ingestion_worker


def main() -> int:
    worker_source = inspect.getsource(runtime_ingestion_worker)

    validation_call = worker_source.rfind("validate_workload_assignment(")
    run_once_call = worker_source.rfind("worker.run_once(")

    checks = {
        "execution_type_configurable": 'WORKER_EXECUTION_TYPE", "document.ingestion"' in worker_source,
        "candidate_query_uses_configured_execution_type": "RuntimeExecution.execution_type == execution_type"
        in worker_source,
        "registry_validates_configured_execution_type": "registry.resolve(execution_type)" in worker_source,
        "run_once_uses_configured_execution_type": "execution_type=execution_type" in worker_source,
        "queue_policy_present_in_production_entrypoint": "RuntimeWorkloadPolicy" in worker_source,
        "queue_key_configurable": 'WORKER_QUEUE_KEY", "platform-default"' in worker_source,
        "accepted_queue_keys_configurable": "WORKER_ACCEPTED_QUEUE_KEYS" in worker_source,
        "candidate_limit_configurable": "WORKER_QUEUE_CANDIDATE_LIMIT" in worker_source,
        "queue_assignment_validated_before_run": validation_call >= 0
        and run_once_call >= 0
        and validation_call < run_once_call,
        "configured_execution_type_reaches_candidate_query": "pending_candidates(execution_type, candidate_limit)"
        in worker_source,
        "configured_execution_type_reaches_registry": "build_registry(execution_type)" in worker_source,
        "legacy_default_preserved": "document.ingestion" in worker_source and "platform-default" in worker_source,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
