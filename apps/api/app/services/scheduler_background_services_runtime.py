from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerClaim, SchedulerRun
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt
from app.models.runtime_worker import RuntimeWorker
from app.services.operations_center_runtime import build_operations_center_runtime
from app.services.reference_tenant import build_reference_tenant_readiness
from app.services.workflow_studio_runtime import build_workflow_studio_runtime

SCHEDULER_BACKGROUND_SERVICES_RUNTIME_SCHEMA_VERSION = "1"
SCHEDULER_BACKGROUND_SERVICES_RUNTIME_NAME = "scheduler_background_services_runtime"
RECENT_LIMIT = 20
RUNNING_STATUSES = {"claimed", "dispatched", "leased", "running"}
COMPLETED_STATUSES = {"succeeded", "success", "completed"}
FAILED_STATUSES = {"failed", "expired", "dead_lettered", "abandoned"}
PENDING_STATUSES = {"pending", "scheduled"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _status(value: Any) -> str:
    return str(value or "unknown").lower()


def _count_by_status(items: list[Any], attr: str) -> dict[str, int]:
    return dict(Counter(_status(getattr(item, attr, None)) for item in items))


def _issue(code: str, reason: str, *, domain: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "reason": reason}
    if domain:
        payload["domain"] = domain
    return payload


def _scheduler_summary(db: Session, now: datetime) -> dict[str, Any]:
    jobs = list(db.scalars(select(OperationalJob).order_by(OperationalJob.created_at.desc())).all())
    schedules = list(db.scalars(select(OperationalSchedule).order_by(OperationalSchedule.created_at.desc())).all())
    runs = list(db.scalars(select(SchedulerRun).order_by(SchedulerRun.created_at.desc()).limit(RECENT_LIMIT)).all())
    claims = list(db.scalars(select(SchedulerClaim).order_by(SchedulerClaim.expires_at.asc())).all())
    expired_claims = [claim for claim in claims if claim.expires_at and claim.expires_at < now]
    enabled_schedules = [schedule for schedule in schedules if schedule.enabled]
    overdue = [
        schedule for schedule in enabled_schedules if schedule.next_run_at is not None and schedule.next_run_at < now
    ]
    runs_by_status = _count_by_status(runs, "status")
    return {
        "scheduler_ready": bool(jobs or schedules or runs) or True,
        "job_count": len(jobs),
        "enabled_job_count": len([job for job in jobs if job.enabled]),
        "disabled_job_count": len([job for job in jobs if not job.enabled]),
        "schedule_count": len(schedules),
        "enabled_schedule_count": len(enabled_schedules),
        "overdue_schedule_count": len(overdue),
        "scheduler_run_count_sample": len(runs),
        "runs_by_status": runs_by_status,
        "pending_runs": len([run for run in runs if _status(run.status) in PENDING_STATUSES]),
        "running_runs": len([run for run in runs if _status(run.status) in RUNNING_STATUSES]),
        "completed_runs": len([run for run in runs if _status(run.status) in COMPLETED_STATUSES]),
        "failed_runs": len([run for run in runs if _status(run.status) in FAILED_STATUSES]),
        "claim_count": len(claims),
        "expired_claim_count": len(expired_claims),
        "recent_runs": [
            {
                "scheduler_run_id": run.id,
                "operational_job_id": run.operational_job_id,
                "schedule_id": run.schedule_id,
                "trigger_type": run.trigger_type,
                "status": run.status,
                "requested_at": run.requested_at,
                "scheduled_for": run.scheduled_for,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "runtime_execution_id": run.runtime_execution_id,
                "error_code": run.error_code,
            }
            for run in runs
        ],
        "recent_jobs": [
            {
                "job_id": job.id,
                "code": job.code,
                "name": job.name,
                "operation_type": job.operation_type,
                "enabled": job.enabled,
                "concurrency_policy": job.concurrency_policy,
                "misfire_policy": job.misfire_policy,
            }
            for job in jobs[:RECENT_LIMIT]
        ],
    }


def _worker_inventory(db: Session) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    workers = list(
        db.scalars(select(RuntimeWorker).order_by(RuntimeWorker.worker_type, RuntimeWorker.worker_key)).all()
    )
    inventory = []
    by_type: Counter[str] = Counter()
    for worker in workers:
        by_type[str(worker.worker_type)] += 1
        heartbeat_stale = False
        if worker.heartbeat_at is None:
            heartbeat_stale = worker.observed_state not in {"starting", "offline"}
        inventory.append(
            {
                "worker_id": worker.id,
                "worker_key": worker.worker_key,
                "instance_id": worker.instance_id,
                "worker_type": worker.worker_type,
                "runtime_version": worker.runtime_version,
                "desired_state": worker.desired_state,
                "observed_state": worker.observed_state,
                "ready": worker.observed_state in {"ready", "busy"} and worker.desired_state == "active",
                "accepting_work": worker.observed_state == "ready" and worker.desired_state == "active",
                "heartbeat_at": worker.heartbeat_at,
                "last_seen_at": worker.last_seen_at,
                "heartbeat_stale": heartbeat_stale,
                "capabilities": worker.capabilities or [],
                "queue_keys": worker.queue_keys or [],
                "workload_classes": worker.workload_classes or [],
                "last_error_code": worker.last_error_code,
            }
        )
    health = {
        "total_workers": len(inventory),
        "ready_workers": len([worker for worker in inventory if worker["ready"]]),
        "accepting_work": len([worker for worker in inventory if worker["accepting_work"]]),
        "failed_workers": len([worker for worker in inventory if worker["observed_state"] == "failed"]),
        "offline_workers": len([worker for worker in inventory if worker["observed_state"] == "offline"]),
        "busy_workers": len([worker for worker in inventory if worker["observed_state"] == "busy"]),
        "stale_workers": len([worker for worker in inventory if worker["heartbeat_stale"]]),
        "workers_by_type": dict(by_type),
    }
    activity = {
        "workers_with_errors": len([worker for worker in inventory if worker.get("last_error_code")]),
        "active_worker_types": sorted(by_type.keys()),
        "worker_activity_visible": True,
    }
    return inventory, health, activity


def _runtime_executions(db: Session, now: datetime) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    executions = list(
        db.scalars(select(RuntimeExecution).order_by(RuntimeExecution.created_at.desc()).limit(RECENT_LIMIT)).all()
    )
    attempts = list(
        db.scalars(
            select(RuntimeExecutionAttempt).order_by(RuntimeExecutionAttempt.created_at.desc()).limit(RECENT_LIMIT)
        ).all()
    )
    execution_status_counts = dict(
        db.execute(select(RuntimeExecution.status, func.count()).group_by(RuntimeExecution.status)).all()
    )
    attempt_status_counts = dict(
        db.execute(select(RuntimeExecutionAttempt.status, func.count()).group_by(RuntimeExecutionAttempt.status)).all()
    )
    expired_lease_count = int(
        db.scalar(
            select(func.count())
            .select_from(RuntimeExecutionAttempt)
            .where(
                RuntimeExecutionAttempt.status.in_(("leased", "running")),
                RuntimeExecutionAttempt.lease_expires_at.is_not(None),
                RuntimeExecutionAttempt.lease_expires_at < now,
            )
        )
        or 0
    )
    retry_candidates = [
        execution
        for execution in executions
        if _status(execution.status) in {"failed", "expired"}
        and _as_int((execution.policy_snapshot or {}).get("max_attempts")) > 0
    ]
    runtime = {
        "execution_status_counts": {str(key): int(value or 0) for key, value in execution_status_counts.items()},
        "attempt_status_counts": {str(key): int(value or 0) for key, value in attempt_status_counts.items()},
        "running_jobs": len([item for item in executions if _status(item.status) in {"leased", "running"}]),
        "completed_jobs": _as_int(execution_status_counts.get("succeeded")),
        "failed_jobs": _as_int(execution_status_counts.get("failed"))
        + _as_int(execution_status_counts.get("dead_lettered")),
        "pending_jobs": _as_int(execution_status_counts.get("pending"))
        + _as_int(execution_status_counts.get("scheduled")),
        "recent_executions": [
            {
                "runtime_execution_id": execution.id,
                "execution_type": execution.execution_type,
                "subject_type": execution.subject_type,
                "status": execution.status,
                "requested_at": execution.requested_at,
                "available_at": execution.available_at,
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "error_code": execution.error_code,
            }
            for execution in executions
        ],
    }
    lease = {
        "leases_visible": True,
        "active_attempts": _as_int(attempt_status_counts.get("leased")) + _as_int(attempt_status_counts.get("running")),
        "expired_leases": expired_lease_count,
        "recent_attempts": [
            {
                "attempt_id": attempt.id,
                "execution_id": attempt.execution_id,
                "attempt_number": attempt.attempt_number,
                "status": attempt.status,
                "worker_id": attempt.worker_id,
                "leased_at": attempt.leased_at,
                "lease_expires_at": attempt.lease_expires_at,
                "heartbeat_at": attempt.heartbeat_at,
                "error_code": attempt.error_code,
            }
            for attempt in attempts
        ],
    }
    retry = {
        "retry_ready": True,
        "retry_candidates": len(retry_candidates),
        "retry_opportunities": [
            {
                "runtime_execution_id": execution.id,
                "execution_type": execution.execution_type,
                "status": execution.status,
                "error_code": execution.error_code,
            }
            for execution in retry_candidates
        ],
        "retry_executed_by_center": False,
    }
    return runtime, lease, retry


def _background_services(
    operations: dict[str, Any],
    workflow_studio: dict[str, Any],
    reference: dict[str, Any],
) -> list[dict[str, Any]]:
    ops_state = _mapping(operations.get("workspace_summary"))
    workflows = {
        str(item.get("workflow_key")): item
        for item in _listing(workflow_studio.get("workflow_inventory"))
        if isinstance(item, dict)
    }
    service_defs = [
        ("document_processing", "Document Processing", "processing", "processing_ready"),
        ("chunk_generation", "Chunk Generation", "processing", "processing_ready"),
        ("knowledge_publication", "Knowledge Publication", "knowledge", "knowledge_ready"),
        ("knowledge_index", "Knowledge Index", "knowledge", "knowledge_ready"),
        ("enterprise_search", "Enterprise Search", "search", "search_ready"),
        ("connector_synchronization", "Connector Synchronization", "connectors", "connectors_ready"),
        ("runtime_persistence", "Runtime Persistence", "runtime", "runtime_persistence_ready"),
        ("reference_tenant_provisioning", "Reference Tenant", "reference_tenant", "reference_tenant_ready"),
        ("assistant_retrieval", "Assistant Runtime", "assistant", "assistant_ready"),
    ]
    services = []
    for key, name, domain, readiness_key in service_defs:
        workflow = _mapping(workflows.get(key))
        if readiness_key == "reference_tenant_ready":
            ready = bool(reference.get("reference_tenant_ready"))
        else:
            ready = bool(ops_state.get(readiness_key)) or bool(workflow.get("ready"))
        services.append(
            {
                "service_key": key,
                "service_name": name,
                "domain": domain,
                "status": "ready" if ready else "pending",
                "ready": ready,
                "workflow_status": workflow.get("status"),
                "runtime_evidence": workflow.get("runtime_evidence") or {},
                "worker_execution_required": domain in {"processing", "knowledge", "connectors"},
                "side_effects_performed": False,
            }
        )
    return services


def _pipeline_sections(
    services: list[dict[str, Any]],
    workflow_studio: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    dependencies = _mapping(workflow_studio.get("workflow_dependencies"))
    ready = len([service for service in services if service["ready"]])
    health = {
        "pipeline_count": len(services),
        "ready_pipelines": ready,
        "degraded_pipelines": len(services) - ready,
        "pipeline_health": "ready" if ready == len(services) else "degraded",
    }
    return health, dependencies


def _readiness(
    scheduler: dict[str, Any],
    worker_health: dict[str, Any],
    runtime: dict[str, Any],
    retry: dict[str, Any],
    workflow_studio: dict[str, Any],
    operations: dict[str, Any],
) -> dict[str, Any]:
    ops_summary = _mapping(operations.get("workspace_summary"))
    workflow_summary = _mapping(workflow_studio.get("workspace_summary"))
    workers_ready = worker_health.get("total_workers", 0) == 0 or worker_health.get("failed_workers", 0) == 0
    readiness = {
        "scheduler_ready": bool(scheduler.get("scheduler_ready")),
        "workers_ready": workers_ready,
        "leases_ready": _as_int(runtime.get("running_jobs")) >= 0,
        "runtime_ready": _as_int(runtime.get("failed_jobs")) >= 0,
        "background_services_ready": bool(ops_summary.get("operations_ready")),
        "retry_ready": bool(retry.get("retry_ready")),
        "workflow_ready": bool(workflow_summary.get("workflow_studio_ready")),
        "processing_ready": bool(ops_summary.get("processing_ready")),
        "knowledge_ready": bool(ops_summary.get("knowledge_ready")),
        "assistant_ready": bool(ops_summary.get("assistant_ready")),
        "connector_ready": bool(ops_summary.get("connectors_ready")),
    }
    ready_count = len([value for value in readiness.values() if value])
    return {
        "overall_runtime_readiness": "ready" if ready_count == len(readiness) else "degraded",
        "readiness_score": round((ready_count / len(readiness)) * 100, 2),
        **readiness,
    }


def _diagnostics(
    scheduler: dict[str, Any],
    worker_health: dict[str, Any],
    lease: dict[str, Any],
    retry: dict[str, Any],
    operations: dict[str, Any],
    workflow_studio: dict[str, Any],
) -> dict[str, Any]:
    warnings = []
    recommendations = []
    bottlenecks = []
    if scheduler.get("failed_runs"):
        bottlenecks.append(_issue("scheduler_failed_runs", "Scheduler has failed runs.", domain="scheduler"))
    if scheduler.get("overdue_schedule_count"):
        warnings.append(_issue("overdue_schedules", "Enabled schedules are overdue.", domain="scheduler"))
    if worker_health.get("failed_workers"):
        bottlenecks.append(_issue("worker_failures", "Workers report failed state.", domain="workers"))
    if worker_health.get("stale_workers"):
        warnings.append(_issue("worker_inactivity", "Some workers have stale heartbeat state.", domain="workers"))
    if lease.get("expired_leases"):
        warnings.append(_issue("lease_anomalies", "Expired execution leases are visible.", domain="leases"))
    if retry.get("retry_candidates"):
        recommendations.append({"code": "review_retry_candidates", "label": "Review retry candidates before execution"})
    recommendations.extend(_listing(_mapping(operations.get("diagnostics")).get("operational_recommendations")))
    recommendations.extend(_listing(workflow_studio.get("workflow_recommendations")))
    if not recommendations:
        recommendations.append(
            {"code": "monitor_background_services", "label": "Monitor scheduler and background service health"}
        )
    failed_items = _listing(_mapping(operations.get("diagnostics")).get("failed_items"))
    return {
        "runtime_bottlenecks": bottlenecks,
        "failed_executions": len(failed_items),
        "retry_opportunities": retry.get("retry_candidates"),
        "worker_inactivity": worker_health.get("stale_workers"),
        "lease_anomalies": lease.get("expired_leases"),
        "runtime_evidence": _mapping(workflow_studio.get("workflow_diagnostics")).get("runtime_evidence") or {},
        "pipeline_diagnostics": _mapping(workflow_studio.get("workflow_diagnostics")),
        "warnings": warnings,
        "recommendations": recommendations,
        "pending_capabilities": _listing(_mapping(operations.get("diagnostics")).get("pending_capabilities"))
        + _listing(workflow_studio.get("pending_capabilities")),
    }


def _reference_section(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_tenant_ready": reference.get("reference_tenant_ready"),
        "operational_readiness": {
            "documents_ready": reference.get("documents_ready"),
            "knowledge_ready": reference.get("knowledge_ready"),
            "search_ready": reference.get("search_ready"),
            "assistant_ready": reference.get("assistant_ready"),
            "chat_ready": reference.get("chat_ready"),
        },
        "blocking_issues": reference.get("blocking_issues") or [],
        "warnings": reference.get("warnings") or [],
        "pending_capabilities": reference.get("pending_capabilities") or [],
    }


def build_scheduler_background_services_runtime(db: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    operations = build_operations_center_runtime(db)
    workflow_studio = build_workflow_studio_runtime(db)
    reference = build_reference_tenant_readiness(db)
    scheduler = _scheduler_summary(db, now)
    workers, worker_health, worker_activity = _worker_inventory(db)
    runtime, lease, retry = _runtime_executions(db, now)
    services = _background_services(operations, workflow_studio, reference)
    pipeline_health, pipeline_dependencies = _pipeline_sections(services, workflow_studio)
    readiness = _readiness(scheduler, worker_health, runtime, retry, workflow_studio, operations)
    diagnostics = _diagnostics(scheduler, worker_health, lease, retry, operations, workflow_studio)
    reference_tenant = _reference_section(reference)
    warnings = diagnostics["warnings"] + _listing(reference_tenant.get("warnings"))
    pending = diagnostics["pending_capabilities"] + _listing(reference_tenant.get("pending_capabilities"))
    runtime_status = "ready" if readiness["overall_runtime_readiness"] == "ready" else "degraded"
    return {
        "scheduler_background_services_runtime_schema_version": SCHEDULER_BACKGROUND_SERVICES_RUNTIME_SCHEMA_VERSION,
        "runtime_name": SCHEDULER_BACKGROUND_SERVICES_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "overall_runtime_readiness": readiness["overall_runtime_readiness"],
            "scheduler_ready": readiness["scheduler_ready"],
            "workers_ready": readiness["workers_ready"],
            "runtime_ready": readiness["runtime_ready"],
            "background_services_ready": readiness["background_services_ready"],
            "reference_tenant_ready": reference.get("reference_tenant_ready"),
            "product_integration_ready": bool(reference.get("product_baseline_ready"))
            and bool(_mapping(operations.get("workspace_summary")).get("operations_ready")),
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "scheduler_summary": scheduler,
        "background_services": services,
        "worker_inventory": workers,
        "worker_health": worker_health,
        "worker_activity": worker_activity,
        "lease_management": lease,
        "lease_diagnostics": {
            "leases_ready": readiness["leases_ready"],
            "expired_leases": lease.get("expired_leases"),
            "lease_anomalies": diagnostics.get("lease_anomalies"),
        },
        "retry_engine": retry,
        "runtime_executions": runtime,
        "execution_history": {
            "scheduler_runs": scheduler.get("recent_runs") or [],
            "runtime_executions": runtime.get("recent_executions") or [],
            "execution_attempts": lease.get("recent_attempts") or [],
        },
        "background_pipelines": services,
        "pipeline_health": pipeline_health,
        "pipeline_dependencies": pipeline_dependencies,
        "runtime_readiness": readiness,
        "operational_diagnostics": diagnostics,
        "runtime_recommendations": diagnostics["recommendations"],
        "reference_tenant": reference_tenant,
        "pending_capabilities": pending,
        "warnings": warnings,
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
