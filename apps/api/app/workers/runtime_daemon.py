import argparse
import os
import socket
import time
from pathlib import Path
from uuid import UUID

import boto3

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.ingestion_artifact_publication import (
    S3CompatibleArtifactObjectWriter,
    SessionIngestionArtifactPublisher,
)
from app.services.object_storage_reader import S3CompatibleSourceObjectReader
from app.services.runtime_workload_policy import RuntimeWorkloadPolicy, WorkloadClassification
from app.workers.artifact_runtime_bootstrap import build_artifact_checkpoint_worker


def build_object_storage_client(settings):
    if not settings.object_storage_bucket:
        raise RuntimeError("OBJECT_STORAGE_BUCKET is required")
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url or None,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key or None,
        aws_secret_access_key=settings.object_storage_secret_key or None,
        use_ssl=settings.object_storage_secure,
    )


def build_worker(settings, worker_id):
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")
    client = build_object_storage_client(settings)
    reader = S3CompatibleSourceObjectReader(
        client,
        required_bucket=settings.object_storage_bucket,
    )
    publisher = SessionIngestionArtifactPublisher(
        SessionLocal,
        S3CompatibleArtifactObjectWriter(client),
        bucket=settings.object_storage_bucket,
    )
    return build_artifact_checkpoint_worker(
        SessionLocal,
        reader,
        publisher,
        worker_id=worker_id,
        workspace_root=Path(settings.ingestion_workspace_root),
        max_source_bytes=settings.ingestion_max_source_bytes,
    )


def build_workload_policy(*, execution_type: str, queue_key: str, accepted_queue_keys: str | None):
    accepted = None
    if accepted_queue_keys is not None:
        accepted = {value.strip() for value in accepted_queue_keys.split(",") if value.strip()}
    return RuntimeWorkloadPolicy(
        lambda organization_id, requested_execution_type: WorkloadClassification(
            workload_class=(requested_execution_type or execution_type).replace(".", "_"),
            queue_key=queue_key,
        ),
        accepted_queue_keys=accepted,
    )


def validate_workload_assignment(
    policy: RuntimeWorkloadPolicy,
    organization_id: UUID,
    execution_type: str,
) -> WorkloadClassification:
    decision = policy.evaluate(organization_id, execution_type)
    if not decision.admitted:
        raise RuntimeError(f"worker queue assignment rejected: {decision.classification.queue_key}")
    return decision.classification


def parse_args():
    parser = argparse.ArgumentParser(description="Run the platform ingestion runtime worker")
    parser.add_argument("--organization-id", default=os.getenv("ORGANIZATION_ID"))
    parser.add_argument("--worker-id", default=os.getenv("WORKER_ID") or f"platform-worker-{socket.gethostname()}")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("WORKER_POLL_SECONDS", "5")))
    parser.add_argument("--execution-type", default=os.getenv("WORKER_EXECUTION_TYPE", "document.ingestion"))
    parser.add_argument("--queue-key", default=os.getenv("WORKER_QUEUE_KEY", "platform-default"))
    parser.add_argument("--accepted-queue-keys", default=os.getenv("WORKER_ACCEPTED_QUEUE_KEYS"))
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.organization_id:
        raise SystemExit("--organization-id or ORGANIZATION_ID is required")
    organization_id = UUID(args.organization_id)
    policy = build_workload_policy(
        execution_type=args.execution_type,
        queue_key=args.queue_key,
        accepted_queue_keys=args.accepted_queue_keys,
    )
    validate_workload_assignment(policy, organization_id, args.execution_type)
    worker = build_worker(get_settings(), args.worker_id)

    if args.once:
        worker.run_once(organization_id, execution_type=args.execution_type)
        return 0

    while True:
        item = worker.run_once(organization_id, execution_type=args.execution_type)
        if item is None:
            time.sleep(max(args.poll_seconds, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
