from __future__ import annotations

import os
import socket
import time

from app.db.session import SessionLocal
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.ingestion_queue_admission import IngestionQueueAdmission, IngestionQueuePolicy
from app.services.runtime_dependency_recovery import (
    RuntimeDependencyRecovery,
    is_transient_dependency_error,
)
from app.services.runtime_worker_control import RuntimeWorkerControl
from app.services.runtime_worker_registry import RuntimeWorkerRegistration, RuntimeWorkerRegistry
from app.workers.runtime_ingestion_worker import (
    RuntimeWorkerConfigurationError,
    accepted_queue_keys,
    build_registry,
    build_workload_policy,
    pending_candidates,
    validate_workload_assignment,
)


def run_forever() -> int:
    recovery = RuntimeDependencyRecovery()
    while True:
        try:
            result = _run_registered_worker()
            recovery.recovered()
            return result
        except Exception as exc:
            if not is_transient_dependency_error(exc):
                raise
            recovery.wait()


def _run_registered_worker() -> int:
    if SessionLocal is None:
        raise RuntimeWorkerConfigurationError("database url is not configured")

    hostname = socket.gethostname()
    worker_id = os.getenv("WORKER_ID") or f"ingestion-runtime-{hostname}"
    instance_id = os.getenv("WORKER_INSTANCE_ID") or f"{worker_id}:{hostname}:{os.getpid()}"
    execution_type = os.getenv("WORKER_EXECUTION_TYPE", "document.ingestion")
    queue_key = os.getenv("WORKER_QUEUE_KEY", "platform-default")
    configured_queue_keys = accepted_queue_keys(os.getenv("WORKER_ACCEPTED_QUEUE_KEYS"))
    published_queue_keys = configured_queue_keys or (queue_key,)
    poll_interval = max(float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2")), 0.1)
    heartbeat_interval = max(float(os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "10")), 1.0)
    candidate_limit = max(int(os.getenv("WORKER_QUEUE_CANDIDATE_LIMIT", "100")), 1)

    workload_policy = build_workload_policy(
        execution_type=execution_type,
        accepted_queue_keys_value=os.getenv("WORKER_ACCEPTED_QUEUE_KEYS"),
    )
    admission = IngestionQueueAdmission(
        IngestionQueuePolicy(
            heavy_bytes_threshold=max(int(os.getenv("WORKER_HEAVY_BYTES_THRESHOLD", "100000000")), 1),
            heavy_pages_threshold=max(int(os.getenv("WORKER_HEAVY_PAGES_THRESHOLD", "500")), 1),
            max_consecutive_heavy=max(int(os.getenv("WORKER_MAX_CONSECUTIVE_HEAVY", "1")), 1),
        )
    )
    runtime_worker = CheckpointRuntimeWorker(
        SessionLocal,
        build_registry(execution_type),
        worker_id=worker_id,
    )
    lifecycle = RuntimeWorkerRegistry(SessionLocal)
    control = RuntimeWorkerControl(SessionLocal)

    lifecycle.register(
        RuntimeWorkerRegistration(
            worker_key=worker_id,
            instance_id=instance_id,
            worker_type="runtime.execution",
            runtime_version=os.getenv("WORKER_RUNTIME_VERSION") or os.getenv("BUILD_COMMIT"),
            capabilities=("runtime.execution", execution_type),
            queue_keys=published_queue_keys,
            workload_classes=(execution_type.replace(".", "_"),),
            metadata={"hostname": hostname, "process_id": os.getpid()},
        )
    )
    lifecycle.heartbeat(worker_key=worker_id, instance_id=instance_id, observed_state="ready")
    next_heartbeat = time.monotonic() + heartbeat_interval

    try:
        while True:
            decision = control.decision(worker_key=worker_id, instance_id=instance_id)
            if decision.should_exit:
                lifecycle.mark_offline(worker_key=worker_id, instance_id=instance_id)
                return 0

            now = time.monotonic()
            if not decision.accepts_work:
                if now >= next_heartbeat:
                    lifecycle.heartbeat(
                        worker_key=worker_id,
                        instance_id=instance_id,
                        observed_state=decision.observed_state,
                    )
                    next_heartbeat = now + heartbeat_interval
                time.sleep(poll_interval)
                continue

            if now >= next_heartbeat:
                lifecycle.heartbeat(
                    worker_key=worker_id,
                    instance_id=instance_id,
                    observed_state="ready",
                )
                next_heartbeat = now + heartbeat_interval

            execution, lane = admission.choose(pending_candidates(execution_type, candidate_limit))
            if execution is None:
                time.sleep(poll_interval)
                continue

            validate_workload_assignment(workload_policy, execution.organization_id, execution_type)
            lifecycle.heartbeat(
                worker_key=worker_id,
                instance_id=instance_id,
                observed_state="busy",
                metrics={"current_lane": lane},
            )
            try:
                runtime_worker.run_once(
                    execution.organization_id,
                    execution_type=execution_type,
                    execution_id=execution.id,
                )
            finally:
                post_run = control.decision(worker_key=worker_id, instance_id=instance_id)
                lifecycle.heartbeat(
                    worker_key=worker_id,
                    instance_id=instance_id,
                    observed_state=post_run.observed_state,
                    metrics={"current_lane": None},
                )
                next_heartbeat = time.monotonic() + heartbeat_interval
    except KeyboardInterrupt:
        lifecycle.mark_offline(worker_key=worker_id, instance_id=instance_id)
        return 0
    except Exception as exc:
        if is_transient_dependency_error(exc):
            raise
        lifecycle.mark_offline(
            worker_key=worker_id,
            instance_id=instance_id,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        raise


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
