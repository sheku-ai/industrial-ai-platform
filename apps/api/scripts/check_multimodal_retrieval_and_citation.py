import json

from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
from app.services.knowledge_record_citation import knowledge_record_citation
from app.services.knowledge_record_selection import select_knowledge_records
from app.services.visual_knowledge_records import VisualKnowledgeRecord


def main():
    text = {
        "schema": "text-knowledge-record/v1",
        "record_id": "text:1",
        "content": "Source text",
        "metadata": {"content_modality": "text", "provenance": {"page": 1}},
    }
    visual = VisualKnowledgeRecord(
        "visual:1",
        "Visual content",
        {
            "content_modality": "visual_description",
            "derived_content": True,
            "source_locator": {"page_number": 1},
            "provider_key": "deterministic-local-vision",
            "image_hash": "abc",
        },
    )
    records = KnowledgeNdjsonComposer().compose([text], visual_records=[visual]).records
    text_only = select_knowledge_records(records, modalities={"text"})
    visual_only = select_knowledge_records(records, modalities={"visual_description"})
    derived_only = select_knowledge_records(records, evidence_roles={"derived"})
    citation = knowledge_record_citation(visual_only[0])
    checks = {
        "text_filter": len(text_only) == 1 and text_only[0]["record_id"] == "text:1",
        "visual_filter": len(visual_only) == 1 and visual_only[0]["record_id"] == "visual:1",
        "derived_filter": len(derived_only) == 1 and derived_only[0]["record_id"] == "visual:1",
        "visual_citation_basis": citation["citation_basis"] == "derived_visual_description",
        "visual_locator": citation["source_locator"] == {"page_number": 1},
        "provider_traceability": citation["provider_key"] == "deterministic-local-vision",
        "image_traceability": citation["image_hash"] == "abc",
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "citation": citation, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
