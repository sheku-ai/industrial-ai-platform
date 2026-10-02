import hashlib
import json
import uuid

from app.api.routes.knowledge import retrieve_knowledge
from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.schemas.product_api import KnowledgeContextRequest


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main():
    organization_id, document_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    text_value = "Generic evidence describes a controlled platform component."
    visual_value = "Generic evidence shows a diagram with two connected components."
    db = SessionLocal()
    try:
        db.add(
            Organization(
                id=organization_id,
                slug=f"multimodal-retrieval-{uuid.uuid4().hex}",
                name="Multimodal Retrieval E2E",
                status="active",
                config={},
            )
        )
        db.flush()
        db.add(
            DocumentRecord(
                id=document_id,
                organization_id=organization_id,
                title="Multimodal Retrieval E2E",
                source_type="e2e",
                source_ref={},
                metadata_json={},
                classification={},
                status="indexed",
            )
        )
        db.flush()
        db.add(
            DocumentVersion(
                id=version_id,
                organization_id=organization_id,
                document_record_id=document_id,
                version_number=1,
                content_type="application/pdf",
                file_name="source.pdf",
                source_snapshot={},
                status="indexed",
            )
        )
        db.flush()
        db.add(
            Chunk(
                id=uuid.uuid4(),
                organization_id=organization_id,
                document_record_id=document_id,
                document_version_id=version_id,
                chunk_index=0,
                chunk_key="text:0",
                content_hash=_hash(text_value),
                text=text_value,
                content_type="text/plain",
                section_ref={"page_number": 1},
                provenance={"page_number": 1},
                quality={},
                metadata_json={},
                status="indexed",
            )
        )
        db.add(
            Chunk(
                id=uuid.uuid4(),
                organization_id=organization_id,
                document_record_id=document_id,
                document_version_id=version_id,
                chunk_index=1,
                chunk_key="visual:1",
                content_hash=_hash(visual_value),
                text=visual_value,
                content_type="text/plain",
                section_ref={},
                provenance={},
                quality={},
                metadata_json={
                    "content_modality": "visual_description",
                    "evidence_role": "derived",
                    "authoritative": False,
                    "derived_content": True,
                    "citation_basis": "derived_visual_description",
                    "source_locator": {"page_number": 1},
                    "provider_key": "deterministic-local-vision",
                    "image_hash": "image-abc",
                },
                status="indexed",
            )
        )
        db.commit()

        text_response = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="generic evidence",
                metadata={"content_modality": "text"},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        visual_response = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="generic evidence",
                metadata={"content_modality": "visual_description"},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )
        derived_response = retrieve_knowledge(
            KnowledgeContextRequest(
                organization_id=organization_id,
                query_text="generic evidence",
                metadata={"evidence_role": "derived"},
                top_k=10,
                candidate_k=20,
            ),
            db,
        )

        visual_citation = visual_response.citations[0].metadata if visual_response.citations else {}
        checks = {
            "text_endpoint_filter": len(text_response.context) == 1
            and text_response.context[0].metadata.get("content_modality") == "text",
            "visual_endpoint_filter": len(visual_response.context) == 1
            and visual_response.context[0].metadata.get("content_modality") == "visual_description",
            "derived_endpoint_filter": len(derived_response.context) == 1
            and derived_response.context[0].metadata.get("evidence_role") == "derived",
            "visual_citation_basis": visual_citation.get("citation_basis") == "derived_visual_description",
            "visual_source_locator": visual_citation.get("source_locator") == {"page_number": 1},
            "visual_provider_traceability": visual_citation.get("provider_key") == "deterministic-local-vision",
            "visual_image_traceability": visual_citation.get("image_hash") == "image-abc",
            "text_default_authoritative": text_response.context[0].metadata.get("evidence_role") == "authoritative",
        }
        passed = all(checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "organization_id": str(organization_id),
                    "text_context_count": len(text_response.context),
                    "visual_context_count": len(visual_response.context),
                    "derived_context_count": len(derived_response.context),
                    "database_evidence_retained": True,
                    **checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
