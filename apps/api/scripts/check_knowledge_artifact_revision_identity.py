import json

from app.services.knowledge_artifact_publisher import KnowledgeArtifactPublisher
from app.services.knowledge_ndjson_composer import KnowledgeNdjsonComposer


def build(revision):
    composition = KnowledgeNdjsonComposer().compose(
        (
            {
                "record_id": "text:1",
                "content": "Revision identity smoke.",
                "metadata": {"content_modality": "text"},
            },
        )
    )
    return KnowledgeArtifactPublisher().build(
        composition,
        document_version_id="version-identity-1",
        processing_revision_id=revision,
    )


def main():
    first = build("revision-1")
    first_again = build("revision-1")
    second = build("revision-2")

    blank_revision_rejected = False
    try:
        build(" ")
    except ValueError:
        blank_revision_rejected = True

    unsafe_revision_rejected = False
    try:
        build("nested/revision")
    except ValueError:
        unsafe_revision_rejected = True

    checks = {
        "revision_path_scoped": first.object_name
        == ("document-versions/version-identity-1/revisions/revision-1/knowledge.ndjson"),
        "manifest_revision_preserved": first.manifest.get("processing_revision_id") == "revision-1",
        "same_revision_deterministic": (
            first.object_name == first_again.object_name
            and first.manifest.get("sha256") == first_again.manifest.get("sha256")
            and first.payload == first_again.payload
        ),
        "different_revision_isolated": second.object_name != first.object_name,
        "content_checksum_stable_across_revisions": (second.manifest.get("sha256") == first.manifest.get("sha256")),
        "blank_revision_rejected": blank_revision_rejected,
        "unsafe_revision_rejected": unsafe_revision_rejected,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "object_name": first.object_name, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
