import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.runtime import RuntimeExecutionArtifact
from app.services.ingestion_artifact_publication import (
    S3CompatibleArtifactObjectWriter,
    SessionIngestionArtifactPublisher,
)
from app.services.object_storage_reader import S3CompatibleSourceObjectReader
from app.workers.artifact_runtime_bootstrap import build_artifact_checkpoint_worker
from app.workers.smoke_ingestion_runtime import (
    _client,
    _preflight,
    _seed,
    _validate_settings,
    _verify,
)


def main():
    settings = get_settings()
    _validate_settings(settings)
    client = _client(settings)
    _preflight(client, settings.object_storage_bucket)

    reader = S3CompatibleSourceObjectReader(
        client,
        required_bucket=settings.object_storage_bucket,
    )
    publisher = SessionIngestionArtifactPublisher(
        SessionLocal,
        S3CompatibleArtifactObjectWriter(client),
        bucket=settings.object_storage_bucket,
    )

    session = SessionLocal()
    try:
        identifiers = _seed(session, client, settings.object_storage_bucket)
        worker = build_artifact_checkpoint_worker(
            SessionLocal,
            reader,
            publisher,
            worker_id="runtime-artifact-smoke-worker",
            workspace_root=Path(settings.ingestion_workspace_root),
            max_source_bytes=settings.ingestion_max_source_bytes,
        )
        item = worker.run_once(
            identifiers["organization_id"],
            execution_type="document.ingestion",
        )
        if item is None or item.execution_id != identifiers["execution_id"]:
            raise RuntimeError("artifact smoke execution was not claimed")

        session.expire_all()
        result = _verify(session, identifiers)
        artifact = session.scalar(
            select(RuntimeExecutionArtifact).where(
                RuntimeExecutionArtifact.organization_id == identifiers["organization_id"],
                RuntimeExecutionArtifact.execution_id == identifiers["execution_id"],
                RuntimeExecutionArtifact.artifact_type == "ingestion.manifest",
            )
        )
        if artifact is None or artifact.status != "published":
            raise RuntimeError("ingestion manifest artifact was not published")

        bucket, key = artifact.storage_uri.removeprefix("s3://").split("/", 1)
        response = client.head_object(Bucket=bucket, Key=key)
        if response.get("Metadata", {}).get("sha256") != artifact.checksum_sha256:
            raise RuntimeError("artifact object checksum metadata does not match registry")

        result["artifact"] = {
            "artifact_id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "storage_uri": artifact.storage_uri,
            "status": artifact.status,
            "checksum_sha256": artifact.checksum_sha256,
            "size_bytes": artifact.size_bytes,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
