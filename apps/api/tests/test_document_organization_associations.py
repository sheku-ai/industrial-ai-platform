from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.audit import AuditEvent, AuditHistory
from app.models.core import OrganizationNode, OrganizationNodeType
from app.models.documents import (
    DocumentOrganizationAssociation,
    DocumentOrganizationAssociationAggregate,
    DocumentRecord,
)
from app.schemas.document_organization_associations import (
    DocumentOrganizationAssociationSaveRequest,
)
from app.schemas.documents import DocumentLifecycleOrchestrateRequest
from app.services.document_organization_associations import (
    ADMIN_DOCUMENT_PERMISSION,
    READ_DOCUMENT_PERMISSION,
    READ_STRUCTURE_PERMISSION,
    DocumentOrganizationAssociationError,
    DocumentOrganizationAssociationService,
)


class _FakeRepository:
    def __init__(self, organization_id: uuid.UUID, document: DocumentRecord) -> None:
        self.organization_id = organization_id
        self.document_item = document
        self.aggregate_item: DocumentOrganizationAssociationAggregate | None = None
        self.association_items: list[DocumentOrganizationAssociation] = []
        self.node_items: list[OrganizationNode] = []
        self.catalog_items: list[OrganizationNodeType] = []
        self.audit_items: list[AuditEvent | AuditHistory] = []
        self.bulk_association_reads = 0

    def document(self, document_id, *, for_update=False):
        del for_update
        if (
            self.document_item.id == document_id
            and self.document_item.organization_id == self.organization_id
        ):
            return self.document_item
        return None

    def aggregate(self, document_id, *, for_update=False):
        del for_update
        if self.aggregate_item and self.aggregate_item.document_id == document_id:
            return self.aggregate_item
        return None

    def associations(self, document_id, *, for_update=False):
        del for_update
        return [
            item
            for item in self.association_items
            if item.document_id == document_id
            and item.organization_id == self.organization_id
        ]

    def associations_for_documents(self, document_ids):
        self.bulk_association_reads += 1
        return [
            item
            for item in self.association_items
            if item.document_id in document_ids
            and item.organization_id == self.organization_id
        ]

    def nodes(self, node_ids=None):
        result = [
            item
            for item in self.node_items
            if item.organization_id == self.organization_id
        ]
        if node_ids is not None:
            result = [item for item in result if item.id in node_ids]
        return result

    def node_types(self):
        return list(self.catalog_items)

    def add(self, item):
        now = datetime.now(UTC)
        if getattr(item, "id", None) is None and hasattr(item, "id"):
            item.id = uuid.uuid4()
        if getattr(item, "created_at", None) is None:
            item.created_at = now
        if getattr(item, "updated_at", None) is None:
            item.updated_at = now
        if isinstance(item, DocumentOrganizationAssociationAggregate):
            self.aggregate_item = item
        elif (
            isinstance(item, DocumentOrganizationAssociation)
            and item not in self.association_items
        ):
            self.association_items.append(item)
        elif isinstance(item, AuditEvent | AuditHistory):
            self.audit_items.append(item)

    def flush(self):
        return None


def _document(
    organization_id: uuid.UUID,
    *,
    status: str = "registered",
) -> DocumentRecord:
    now = datetime.now(UTC)
    return DocumentRecord(
        id=uuid.uuid4(),
        organization_id=organization_id,
        title="Governed document",
        source_type="upload",
        source_ref={},
        metadata_json={},
        classification={},
        status=status,
        created_at=now,
        updated_at=now,
    )


def _node(
    organization_id: uuid.UUID,
    code: str,
    *,
    status: str = "active",
    node_type: str = "structure_node",
    parent_node_id: uuid.UUID | None = None,
) -> OrganizationNode:
    now = datetime.now(UTC)
    return OrganizationNode(
        id=uuid.uuid4(),
        organization_id=organization_id,
        parent_node_id=parent_node_id,
        node_type=node_type,
        code=code,
        name=code.replace("-", " ").title(),
        metadata_json={},
        position={},
        status=status,
        created_at=now,
        updated_at=now,
    )


def _catalog(code: str = "structure_node") -> OrganizationNodeType:
    return OrganizationNodeType(
        id=uuid.uuid4(),
        code=code,
        name=code,
        status="active",
        allows_children=True,
        allowed_child_types=[],
        presentation_metadata={},
        display_order=10,
        available_for_new=True,
        edition="community",
    )


def _service(
    *,
    permissions: frozenset[str] | None = None,
    document_status: str = "registered",
) -> tuple[
    DocumentOrganizationAssociationService,
    _FakeRepository,
    DocumentRecord,
]:
    organization_id = uuid.uuid4()
    document = _document(organization_id, status=document_status)
    service = DocumentOrganizationAssociationService(
        None,  # type: ignore[arg-type]
        organization_id=organization_id,
        actor_reference="authenticated-user",
        actor_permissions=permissions
        or frozenset(
            {
                READ_DOCUMENT_PERMISSION,
                ADMIN_DOCUMENT_PERMISSION,
                READ_STRUCTURE_PERMISSION,
            }
        ),
        correlation_id="document-structure-correlation",
    )
    repository = _FakeRepository(organization_id, document)
    repository.catalog_items = [_catalog()]
    service.repository = repository  # type: ignore[assignment]
    return service, repository, document


def _request(
    *,
    revision: int,
    proposals: list[dict],
    mutation_key: uuid.UUID | None = None,
) -> DocumentOrganizationAssociationSaveRequest:
    return DocumentOrganizationAssociationSaveRequest(
        expected_revision=revision,
        mutation_key=mutation_key or uuid.uuid4(),
        associations=proposals,
    )


def test_existing_document_without_associations_remains_valid_and_unassigned() -> None:
    service, _, document = _service()

    runtime = service.runtime(document.id)

    assert runtime["revision"] == 0
    assert runtime["active_associations"] == []
    assert runtime["archived_associations"] == []
    assert runtime["association_semantics"] == "organizational_relation_only"


def test_initial_multiple_associations_are_persisted_versioned_and_audited() -> None:
    service, repository, document = _service()
    first = _node(repository.organization_id, "first")
    second = _node(repository.organization_id, "second")
    repository.node_items = [first, second]

    result = service.apply_initial(
        document,
        organization_node_ids=[first.id, second.id],
        mutation_key="document-lifecycle:stable-key",
        document_created=True,
    )

    assert result["revision"] == 1
    assert {
        item["organization_node_id"] for item in result["active_associations"]
    } == {first.id, second.id}
    assert len(repository.association_items) == 2
    assert len({item.id for item in repository.association_items}) == 2
    assert all(item.organization_id == repository.organization_id for item in repository.association_items)
    assert any(
        isinstance(item, AuditEvent)
        and item.summary == "initial_associations_created"
        for item in repository.audit_items
    )


def test_initial_empty_association_set_does_not_require_structure_read_access() -> None:
    service, repository, document = _service(
        permissions=frozenset({ADMIN_DOCUMENT_PERMISSION}),
    )

    result = service.apply_initial(
        document,
        organization_node_ids=[],
        mutation_key="document-lifecycle:no-structure",
        document_created=True,
    )

    assert result["revision"] == 0
    assert result["active_associations"] == []
    assert result["structure_options"] == []
    assert result["capabilities"] == {"read": False, "administer": False}
    assert repository.association_items == []


def test_foreign_document_and_foreign_or_missing_node_are_not_enumerable() -> None:
    service, repository, document = _service()
    foreign_document_id = uuid.uuid4()
    foreign_node = _node(uuid.uuid4(), "foreign")
    repository.node_items = [foreign_node]

    with pytest.raises(DocumentOrganizationAssociationError, match="document_not_found"):
        service.runtime(foreign_document_id)

    with pytest.raises(DocumentOrganizationAssociationError, match="node_not_found"):
        service.save(
            document.id,
            _request(
                revision=0,
                proposals=[
                    {
                        "organization_node_id": foreign_node.id,
                        "intent": "add",
                    }
                ],
            ),
        )
    assert repository.association_items == []


def test_archived_or_legacy_node_cannot_be_added_and_failure_is_atomic() -> None:
    service, repository, document = _service()
    valid = _node(repository.organization_id, "valid")
    archived = _node(repository.organization_id, "archived", status="archived")
    legacy = _node(
        repository.organization_id,
        "legacy",
        node_type="historical_type",
    )
    repository.node_items = [valid, archived, legacy]

    with pytest.raises(DocumentOrganizationAssociationError, match="node_archived"):
        service.save(
            document.id,
            _request(
                revision=0,
                proposals=[
                    {"organization_node_id": valid.id, "intent": "add"},
                    {"organization_node_id": archived.id, "intent": "add"},
                ],
            ),
        )
    assert repository.association_items == []
    assert repository.audit_items == []

    with pytest.raises(DocumentOrganizationAssociationError, match="type_unavailable"):
        service.save(
            document.id,
            _request(
                revision=0,
                proposals=[
                    {"organization_node_id": legacy.id, "intent": "add"}
                ],
            ),
        )


def test_converged_node_is_immediately_selectable_without_recreating_identity() -> None:
    service, repository, document = _service()
    node = _node(
        repository.organization_id,
        "legacy-location",
        node_type="historical_type",
    )
    original_id = node.id
    repository.node_items = [node]

    before = service.runtime(document.id)
    assert before["structure_options"][0]["legacy"] is True
    assert before["structure_options"][0]["selectable"] is False

    node.node_type = "structure_node"
    after = service.runtime(document.id)
    persisted = service.save(
        document.id,
        _request(
            revision=0,
            proposals=[
                {
                    "organization_node_id": node.id,
                    "intent": "add",
                }
            ],
        ),
    )

    assert node.id == original_id
    assert after["structure_options"][0]["legacy"] is False
    assert after["structure_options"][0]["selectable"] is True
    assert persisted["active_associations"][0]["organization_node_id"] == original_id


def test_duplicate_payload_nodes_are_rejected_before_persistence() -> None:
    node_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="must be unique"):
        _request(
            revision=0,
            proposals=[
                {"organization_node_id": node_id, "intent": "add"},
                {"organization_node_id": node_id, "intent": "retain"},
            ],
        )


def test_equivalent_retry_does_not_duplicate_or_increment_revision() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    mutation_key = uuid.uuid4()
    first = service.save(
        document.id,
        _request(
            revision=0,
            mutation_key=mutation_key,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )

    replay = service.save(
        document.id,
        _request(
            revision=0,
            mutation_key=mutation_key,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )

    assert first["revision"] == replay["revision"] == 1
    assert replay["replayed"] is True
    assert len(repository.association_items) == 1


def test_equivalent_set_with_a_new_mutation_key_does_not_increment_revision() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    service.save(
        document.id,
        _request(
            revision=0,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )

    equivalent = service.save(
        document.id,
        _request(
            revision=1,
            proposals=[{"organization_node_id": node.id, "intent": "retain"}],
        ),
    )

    assert equivalent["revision"] == 1
    assert len(repository.association_items) == 1


def test_stale_revision_and_reused_mutation_key_with_different_payload_conflict() -> None:
    service, repository, document = _service()
    first = _node(repository.organization_id, "first")
    second = _node(repository.organization_id, "second")
    repository.node_items = [first, second]
    mutation_key = uuid.uuid4()
    service.save(
        document.id,
        _request(
            revision=0,
            mutation_key=mutation_key,
            proposals=[{"organization_node_id": first.id, "intent": "add"}],
        ),
    )

    with pytest.raises(DocumentOrganizationAssociationError, match="idempotency_conflict"):
        service.save(
            document.id,
            _request(
                revision=1,
                mutation_key=mutation_key,
                proposals=[{"organization_node_id": second.id, "intent": "add"}],
            ),
        )

    with pytest.raises(DocumentOrganizationAssociationError, match="revision_conflict"):
        service.save(
            document.id,
            _request(
                revision=0,
                proposals=[{"organization_node_id": second.id, "intent": "add"}],
            ),
        )


def test_archive_and_restore_preserve_association_identity_and_lineage() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    created = service.save(
        document.id,
        _request(
            revision=0,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )
    association_id = created["active_associations"][0]["id"]

    archived = service.save(
        document.id,
        _request(
            revision=1,
            proposals=[{"organization_node_id": node.id, "intent": "archive"}],
        ),
    )
    restored = service.save(
        document.id,
        _request(
            revision=2,
            proposals=[{"organization_node_id": node.id, "intent": "restore"}],
        ),
    )

    assert archived["archived_associations"][0]["id"] == association_id
    assert restored["active_associations"][0]["id"] == association_id
    assert repository.association_items[0].archived_at is not None
    assert repository.association_items[0].restored_at is not None
    audit_actions = {
        item.action
        for item in repository.audit_items
        if isinstance(item, AuditHistory)
    }
    assert {"added", "archived", "restored", "revision_committed"} <= audit_actions


def test_restore_under_archived_node_and_mutation_of_archived_document_are_blocked() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    service.save(
        document.id,
        _request(
            revision=0,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )
    service.save(
        document.id,
        _request(
            revision=1,
            proposals=[{"organization_node_id": node.id, "intent": "archive"}],
        ),
    )
    node.status = "archived"

    with pytest.raises(DocumentOrganizationAssociationError, match="node_archived"):
        service.save(
            document.id,
            _request(
                revision=2,
                proposals=[{"organization_node_id": node.id, "intent": "restore"}],
            ),
        )
    document.status = "archived"
    with pytest.raises(DocumentOrganizationAssociationError, match="not_administrable"):
        service.save(document.id, _request(revision=2, proposals=[]))
    assert repository.association_items[0].status == "archived"


def test_archiving_node_or_document_does_not_cascade_association_deletion() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    service.save(
        document.id,
        _request(
            revision=0,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )
    node.status = "archived"
    document.status = "archived"

    runtime = service.runtime(document.id)

    assert len(repository.association_items) == 1
    assert runtime["active_associations"][0]["node"]["node_status"] == "archived"
    assert runtime["warnings"][0]["code"] == "associated_organization_node_archived"


def test_read_and_admin_permissions_remain_independent() -> None:
    read_service, repository, document = _service(
        permissions=frozenset({READ_DOCUMENT_PERMISSION, READ_STRUCTURE_PERMISSION})
    )
    with pytest.raises(DocumentOrganizationAssociationError, match="admin_permission"):
        read_service.save(document.id, _request(revision=0, proposals=[]))

    hidden_service = DocumentOrganizationAssociationService(
        None,  # type: ignore[arg-type]
        organization_id=repository.organization_id,
        actor_reference="document-reader",
        actor_permissions=frozenset({READ_DOCUMENT_PERMISSION}),
    )
    hidden_service.repository = repository  # type: ignore[assignment]
    with pytest.raises(DocumentOrganizationAssociationError, match="read_permission"):
        hidden_service.runtime(document.id)


def test_workspace_projection_batches_associations_and_omits_uuid_from_summary() -> None:
    service, repository, document = _service()
    node = _node(repository.organization_id, "node")
    repository.node_items = [node]
    service.save(
        document.id,
        _request(
            revision=0,
            proposals=[{"organization_node_id": node.id, "intent": "add"}],
        ),
    )
    workspace = {
        "document_registry": [
            {
                "document_record_id": str(document.id),
                "title": document.title,
            }
        ]
    }

    enriched = service.enrich_workspace(workspace)
    summary = enriched["document_registry"][0]["organization_associations"]

    assert repository.bulk_association_reads == 1
    assert summary["active"][0]["name"] == node.name
    assert "organization_node_id" not in summary["active"][0]


def test_workspace_projection_hides_node_names_without_structure_read_access() -> None:
    service, repository, document = _service(
        permissions=frozenset({READ_DOCUMENT_PERMISSION}),
    )
    node = _node(repository.organization_id, "private-node")
    repository.node_items = [node]
    repository.association_items = [
        DocumentOrganizationAssociation(
            id=uuid.uuid4(),
            organization_id=repository.organization_id,
            document_id=document.id,
            organization_node_id=node.id,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    ]
    workspace = {
        "document_registry": [
            {
                "document_record_id": str(document.id),
                "title": document.title,
            }
        ]
    }

    enriched = service.enrich_workspace(workspace)

    assert enriched["document_registry"][0]["organization_associations"] == {
        "visible": False,
        "active_count": 0,
        "active": [],
        "has_unavailable": False,
    }
    assert enriched["organization_associations"]["structure_options"] == []
    assert node.name not in str(enriched)


def test_contract_does_not_accept_client_organization_authority() -> None:
    association_schema = DocumentOrganizationAssociationSaveRequest.model_json_schema()
    assert "organization_id" not in association_schema["properties"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DocumentOrganizationAssociationSaveRequest.model_validate(
            {
                "expected_revision": 0,
                "mutation_key": str(uuid.uuid4()),
                "associations": [],
                "organization_id": str(uuid.uuid4()),
            }
        )
    lifecycle_schema = DocumentLifecycleOrchestrateRequest.model_json_schema()
    assert "organization_node_ids" in lifecycle_schema["properties"]


def test_registration_and_initial_associations_commit_before_version_and_processing() -> None:
    source_path = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "document_lifecycle_orchestrator.py"
    )
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source)
    registration = source.index("build_document_registration_execution(")
    association = source.index(").apply_initial(", registration)
    commit = source.index("db.commit()", association)
    version = source.index("_create_or_get_document_version(", commit)
    processing = source.index(
        "_processing_publication_search_with_runtime_execution(",
        version,
    )

    assert registration < association < commit < version < processing


def test_migration_is_new_head_after_structure_and_creates_no_associations() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260729_994_document_organization_associations.py"
    )
    source = migration_path.read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260729_993"' in source
    assert "INSERT INTO documents.document_organization_associations" not in source
    assert "FROM documents.document_records" in source
