from __future__ import annotations

import importlib
import os
import socket
import time
from collections.abc import Callable

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.runtime import RuntimeExecution
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.ingestion_queue_admission import IngestionQueueAdmission, IngestionQueuePolicy
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.services.runtime_worker_registry import (
    RuntimeWorkerRegistration,
    RuntimeWorkerRegistry,
)
from app.services.runtime_workload_policy import RuntimeWorkloadPolicy, WorkloadClassification


class RuntimeWorkerConfigurationError(RuntimeError):
    pass


def _load_registry_factory(path: str) -> Callable:
    module_name, separator, attribute_name = path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise RuntimeWorkerConfigurationError("RUNTIME_ADAPTER_REGISTRY_FACTORY must use module:function syntax")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise RuntimeWorkerConfigurationError("runtime adapter registry factory is not callable")
    return factory


def build_registry(execution_type: str = "document.ingestion") -> RuntimeAdapterRegistry:
    factory_path = os.getenv(
        "RUNTIME_ADAPTER_REGISTRY_FACTORY",
        "app.workers.review_detection_registry:build_review_detection_registry",
    )
    registry = _load_registry_factory(factory_path)(session_factory=SessionLocal)
    if not isinstance(registry, RuntimeAdapterRegistry):
        raise RuntimeWorkerConfigurationError("registry factory returned an invalid object")
    if registry.resolve(execution_type) is None:
        raise RuntimeWorkerConfigurationError(f"{execution_type} adapter is not registered; worker startup aborted")
    return registry


def pending_candidates(execution_type: str, limit: int):
    session = SessionLocal()
    try:
        return list(
            session.scalars(
                select(RuntimeExecution)
                .where(
                    RuntimeExecution.execution_type == execution_type,
                    RuntimeExecution.status.in_(["pending", "scheduled", "expired"]),
                )
                .order_by(
                    RuntimeExecution.priority.asc(),
                    RuntimeExecution.available_at.asc(),
                    RuntimeExecution.created_at.asc(),
                )
                .limit(limit)
            ).all()
        )
    finally:
        session.close()


def accepted_queue_keys(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))


def build_workload_policy(
    *,
    execution_type: str,
    accepted_queue_keys_value: str | None,
) -> RuntimeWorkloadPolicy:
    accepted = set(accepted_queue_keys(accepted_queue_keys_value))
    return RuntimeWorkloadPolicy(
        lambda organization_id, requested_execution_type: WorkloadClassification(
            workload_class=(requested_execution_type or execution_type).replace(".", "_"),
            queue_key=os.getenv("WORKER_QUEUE_KEY", "platform-default"),
        ),
        accepted_queue_keys=accepted,
    )


def validate_workload_assignment(
    policy: RuntimeWorkloadPolicy,
    organization_id,
    execution_type: str,
) -> None:
    decision = policy.evaluate(organization_id, execution_type)
    if not decision.admitted:
        raise RuntimeWorkerConfigurationError(f"worker queue assignment rejected: {decision.classification.queue_key}")


def run_forever() -> int:
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
    worker = CheckpointRuntimeWorker(
        SessionLocal,
        build_registry(execution_type),
        worker_id=worker_id,
    )
    lifecycle = RuntimeWorkerRegistry(SessionLocal)
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
    lifecycle.heartbeat(
        worker_key=worker_id,
        instance_id=instance_id,
        observed_state="ready",
    )
    next_heartbeat = time.monotonic() + heartbeat_interval

    try:
        while True:
            now = time.monotonic()
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

            validate_workload_assignment(
                workload_policy,
                execution.organization_id,
                execution_type,
            )
            lifecycle.heartbeat(
                worker_key=worker_id,
                instance_id=instance_id,
                observed_state="busy",
                metrics={"current_lane": lane},
            )
            try:
                worker.run_once(
                    execution.organization_id,
                    execution_type=execution_type,
                    execution_id=execution.id,
                )
            finally:
                lifecycle.heartbeat(
                    worker_key=worker_id,
                    instance_id=instance_id,
                    observed_state="ready",
                    metrics={"current_lane": None},
                )
                next_heartbeat = time.monotonic() + heartbeat_interval
    except KeyboardInterrupt:
        lifecycle.mark_offline(worker_key=worker_id, instance_id=instance_id)
        return 0
    except Exception as exc:
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
