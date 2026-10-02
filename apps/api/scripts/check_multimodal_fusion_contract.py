import json

from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer
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
        {"content_modality": "visual_description", "derived_content": True, "source_locator": {"page_number": 1}},
    )
    mixed = KnowledgeNdjsonComposer().compose([text], visual_records=[visual])
    plain = KnowledgeNdjsonComposer().compose([text], visual_records=[visual], include_visual=False)
    first, second = mixed.records
    checks = {
        "text_first": first["record_id"] == "text:1",
        "orders": [item["metadata"]["fusion_order"] for item in mixed.records] == [0, 1],
        "text_authoritative": first["metadata"]["evidence_role"] == "authoritative",
        "visual_derived": second["metadata"]["evidence_role"] == "derived",
        "citation_bases": [first["metadata"]["citation_basis"], second["metadata"]["citation_basis"]]
        == ["source_text", "derived_visual_description"],
        "locators": first["metadata"]["source_locator"] == {"page": 1}
        and second["metadata"]["source_locator"] == {"page_number": 1},
        "metrics": mixed.metrics["authoritative_records"] == 1 and mixed.metrics["derived_records"] == 1,
        "no_ai": len(plain.records) == 1 and plain.metrics["derived_records"] == 0,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
