import contextlib
import hashlib
import json
import os
import uuid
from urllib.parse import urlparse

from sqlalchemy import select

from app.api.routes.knowledge import retrieve_knowledge
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.ingestion import IngestionPipelineProfile
from app.models.runtime import RuntimeExecution, RuntimeExecutionArtifact, RuntimeExecutionAttempt
from app.schemas.product_api import KnowledgeContextRequest
from app.services.checkpoint_runtime_worker import CheckpointRuntimeWorker
from app.services.runtime_worker import RuntimeAdapterRegistry
from app.workers.document_ingestion_factory import build_document_ingestion_adapter
from scripts.check_worker_multimodal_full_chain_e2e import build_pdf, s3_client


def main():
    os.environ["VISUAL_UNDERSTANDING_ENABLED"] = "1"
    os.environ["VISUAL_UNDERSTANDING_PROVIDER"] = "deterministic-local"
    os.environ["VISUAL_UNDERSTANDING_PROFILE"] = "balanced"
    s3 = s3_client()
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "industrial-ai-smoke")
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    organization_id, document_id, version_id, execution_id, profile_id = [uuid.uuid4() for _ in range(5)]
    source_key = f"worker-multimodal-full-chain/{execution_id}/source.pdf"
    payload = build_pdf()
    checksum = hashlib.sha256(payload).hexdigest()
    s3.put_object(
        Bucket=bucket, Key=source_key, Body=payload, ContentType="application/pdf", Metadata={"sha256": checksum}
    )

    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"multimodal-full-chain-{uuid.uuid4().hex}",
                name="Multimodal Full Chain E2E",
                status="active",
                config={},
            )
        )
        db.add(
            IngestionPipelineProfile(
                id=profile_id,
                organization_id=organization_id,
                code="multimodal-full-chain",
                name="Multimodal Full Chain",
                revision="1",
                enabled=True,
                deployment_edition="community",
                default_adapter_key="platform.pdf.text_layer",
                adapter_policies=[
                    {
                        "adapter_key": "platform.pdf.text_layer",
                        "enabled": True,
                        "priority": 100,
                        "allowed_media_types": ["application/pdf"],
                    }
                ],
                adapter_versions={"platform.pdf.text_layer": "1.0.0"},
                adapter_settings={"platform.pdf.text_layer": {"max_pages": 10, "enable_ocr": False}},
            )
        )
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Multimodal Full Chain E2E",
                source_type="e2e",
                source_ref={"uri": f"s3://{bucket}/{source_key}"},
                metadata_json={},
                classification={},
                status="registered",
            )
        )
        db.add(
            DocumentVersion(
                id=version_id,
                organization_id=organization_id,
                document_record_id=document_id,
                version_number=1,
                content_type="application/pdf",
                file_name="source.pdf",
                size_bytes=len(payload),
                checksum_sha256=checksum,
                source_snapshot={},
                status="processing",
            )
        )
        db.add(
            RuntimeExecution(
                id=execution_id,
                organization_id=organization_id,
                execution_type="document.ingestion",
                subject_type="document_version",
                subject_id=version_id,
                priority=100,
                status="pending",
                input_payload={
                    "document_id": str(document_id),
                    "document_version_id": str(version_id),
                    "source_reference": f"s3://{bucket}/{source_key}",
                    "declared_media_type": "application/pdf",
                    "original_file_name": "source.pdf",
                    "content_length": len(payload),
                    "checksum_sha256": checksum,
                    "pipeline_profile_id": str(profile_id),
                    "metadata": {},
                    "options": {"visual_understanding": {"enabled": True, "profile": "balanced"}},
                },
                policy_snapshot={},
                metrics={},
            )
        )
        db.commit()
    finally:
        db.close()

    registry = RuntimeAdapterRegistry()
    registry.register(build_document_ingestion_adapter(session_factory=SessionLocal))
    claimed = CheckpointRuntimeWorker(
        SessionLocal, registry, worker_id="worker-multimodal-full-chain-contract-e2e"
    ).run_once(organization_id, execution_id=execution_id)

    db = SessionLocal()
    knowledge_key = None
    try:
        execution = db.get(RuntimeExecution, execution_id)
        attempt = db.scalar(select(RuntimeExecutionAttempt).where(RuntimeExecutionAttempt.execution_id == execution_id))
        version = db.get(DocumentVersion, version_id)
        chunks = list(db.scalars(select(Chunk).where(Chunk.document_version_id == version_id)).all())
        visual_chunks = [
            chunk for chunk in chunks if (chunk.metadata_json or {}).get("content_modality") == "visual_description"
        ]
        artifacts = list(
            db.scalars(
                select(RuntimeExecutionArtifact).where(RuntimeExecutionArtifact.execution_id == execution_id)
            ).all()
        )
        by_type = {item.artifact_type: item for item in artifacts}
        knowledge = by_type.get("knowledge_ndjson")
        records = []
        if knowledge is not None:
            parsed = urlparse(knowledge.storage_uri)
            knowledge_key = parsed.path.lstrip("/")
            body = s3.get_object(Bucket=parsed.netloc, Key=knowledge_key)["Body"]
            try:
                records = [json.loads(line) for line in body.read().decode().splitlines() if line]
            finally:
                body.close()
        modalities = [item.get("metadata", {}).get("content_modality") for item in records]
        visual = [item for item in records if item.get("metadata", {}).get("content_modality") == "visual_description"]
        retrieval = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="Visual content",
                metadata={"content_modality": "visual_description"},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        retrieved_visual = tuple(retrieval.context)
        checks = {
            "work_item_claimed": claimed is not None,
            "execution_succeeded": execution.status == "succeeded",
            "attempt_succeeded": attempt is not None and attempt.status == "succeeded",
            "document_indexed": version.status == "indexed",
            "text_chunks_persisted": any(
                (chunk.metadata_json or {}).get("content_modality") != "visual_description" for chunk in chunks
            ),
            "visual_chunks_materialized": bool(visual_chunks),
            "visual_enrichment_published": by_type.get("visual_enrichment") is not None,
            "knowledge_artifact_published": knowledge is not None,
            "mixed_records": "text" in modalities and "visual_description" in modalities,
            "text_first": bool(modalities) and modalities[0] == "text",
            "provider_traceability": bool(visual)
            and visual[0]["metadata"].get("provider_key") == "deterministic-local-vision",
            "visual_provenance_preserved": bool(visual) and visual[0]["metadata"].get("source_kind") == "pdf",
            "visual_retrieval_connected": bool(retrieved_visual),
            "visual_retrieval_filtered": bool(retrieved_visual)
            and all(item.metadata.get("content_modality") == "visual_description" for item in retrieved_visual),
            "visual_citation_generated": bool(retrieval.citations)
            and retrieval.citations[0].metadata.get("citation_basis") == "derived_visual_description",
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "execution_id": str(execution_id),
                    "artifact_types": sorted(by_type),
                    "modalities": modalities,
                    "visual_chunk_count": len(visual_chunks),
                    "retrieved_visual_count": len(retrieved_visual),
                    "database_evidence_retained": True,
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
        for key in (source_key, knowledge_key):
            if key:
                with contextlib.suppress(Exception):
                    s3.delete_object(Bucket=bucket, Key=key)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
