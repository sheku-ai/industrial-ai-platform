from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.audit import AuditEvent, AuditHistory
from app.models.core import (
    Organization,
    OrganizationNode,
    OrganizationNodeType,
    OrganizationRelationship,
    OrganizationStructureAggregate,
)
from app.schemas.organization_structure import (
    OrganizationStructureConvergenceApplyRequest,
    OrganizationStructureConvergencePreviewRequest,
    OrganizationStructureSaveRequest,
)
from app.services.organization_structure import (
    ADMIN_PERMISSION,
    READ_PERMISSION,
    OrganizationStructureError,
    OrganizationStructureService,
    analyze_legacy_contains,
)


class _FakeRepository:
    def __init__(self, organization_id: uuid.UUID) -> None:
        self.organization_id = organization_id
        self.organization_item = Organization(
            id=organization_id,
            slug="scoped-organization",
            name="Scoped organization",
            status="active",
            config={},
        )
        self.aggregate_item: OrganizationStructureAggregate | None = None
        self.catalog_items: list[OrganizationNodeType] = []
        self.node_items: list[OrganizationNode] = []
        self.relationship_items: list[OrganizationRelationship] = []
        self.audit_items: list[AuditEvent | AuditHistory] = []

    def organization(self, *, for_update=False, for_share=False):
        return self.organization_item

    def aggregate(self, *, for_update=False):
        return self.aggregate_item

    def node_types(self, *, for_share=False):
        del for_share
        return list(self.catalog_items)

    def nodes(self, *, for_update=False):
        return list(self.node_items)

    def relationships(self, *, for_update=False):
        return list(self.relationship_items)

    def add(self, item):
        now = datetime.now(UTC)
        if getattr(item, "created_at", None) is None:
            item.created_at = now
        if getattr(item, "updated_at", None) is None:
            item.updated_at = now
        if isinstance(item, OrganizationStructureAggregate):
            self.aggregate_item = item
        elif isinstance(item, OrganizationNode) and item not in self.node_items:
            self.node_items.append(item)
        elif (
            isinstance(item, OrganizationRelationship)
            and item not in self.relationship_items
        ):
            self.relationship_items.append(item)
        elif isinstance(item, AuditEvent | AuditHistory):
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()
            self.audit_items.append(item)

    def flush(self):
        return None


def _catalog(
    code: str,
    *,
    status: str = "active",
    allows_children: bool = True,
    allowed_child_types: list[str] | None = None,
    available_for_new: bool = True,
) -> OrganizationNodeType:
    return OrganizationNodeType(
        id=uuid.uuid4(),
        code=code,
        name=code,
        status=status,
        allows_children=allows_children,
        allowed_child_types=allowed_child_types or [],
        presentation_metadata={},
        display_order=10,
        available_for_new=available_for_new,
        edition="community",
    )


def _node(
    organization_id: uuid.UUID,
    code: str,
    *,
    parent_node_id: uuid.UUID | None = None,
    status: str = "active",
    node_type: str = "structure_group",
) -> OrganizationNode:
    now = datetime.now(UTC)
    return OrganizationNode(
        id=uuid.uuid4(),
        organization_id=organization_id,
        parent_node_id=parent_node_id,
        node_type=node_type,
        code=code,
        name=code,
        description=None,
        metadata_json={},
        position={"x": 10, "y": 10},
        status=status,
        created_at=now,
        updated_at=now,
    )


def _service() -> tuple[OrganizationStructureService, _FakeRepository]:
    organization_id = uuid.uuid4()
    service = OrganizationStructureService(
        None,  # type: ignore[arg-type]
        organization_id=organization_id,
        actor_reference="authenticated-user",
        actor_permissions=frozenset({READ_PERMISSION, ADMIN_PERMISSION}),
        correlation_id="structure-correlation",
    )
    repository = _FakeRepository(organization_id)
    repository.catalog_items = [
        _catalog("structure_root"),
        _catalog("structure_group"),
        _catalog("structure_node", allows_children=False),
    ]
    service.repository = repository  # type: ignore[assignment]
    return service, repository


def _proposal(item: OrganizationNode, *, intent: str = "update") -> dict:
    return {
        "ref": str(item.id),
        "node_id": str(item.id),
        "intent": intent,
        "node_type": item.node_type,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "metadata": item.metadata_json,
        "position": item.position,
    }


def _request(
    nodes: list[dict],
    hierarchy: list[dict] | None = None,
    *,
    revision: int = 0,
    mutation_key: uuid.UUID | None = None,
    normalize_legacy_contains: bool = False,
) -> OrganizationStructureSaveRequest:
    return OrganizationStructureSaveRequest(
        expected_revision=revision,
        mutation_key=mutation_key or uuid.uuid4(),
        nodes=nodes,
        hierarchy=hierarchy or [],
        additional_relationships=[],
        normalize_legacy_contains=normalize_legacy_contains,
    )


def _convergence_preview_request(
    targets: list[dict],
) -> OrganizationStructureConvergencePreviewRequest:
    return OrganizationStructureConvergencePreviewRequest(
        targets=targets,
        normalize_legacy_contains=True,
    )


def test_runtime_is_organization_scoped_and_foreign_uuid_is_not_enumerable() -> None:
    service, repository = _service()
    own = _node(repository.organization_id, "own")
    repository.node_items = [own]

    runtime = service.runtime()

    assert [item["id"] for item in runtime["nodes"]] == [own.id]
    foreign = _node(uuid.uuid4(), "foreign")
    with pytest.raises(OrganizationStructureError, match="node_not_found"):
        service.save(_request([_proposal(own), _proposal(foreign)]))


def test_foreign_parent_reference_is_not_enumerable() -> None:
    service, repository = _service()
    own = _node(repository.organization_id, "own")
    repository.node_items = [own]
    foreign_parent_id = uuid.uuid4()

    with pytest.raises(OrganizationStructureError, match="node_not_found"):
        service.save(
            _request(
                [_proposal(own)],
                [
                    {
                        "parent_ref": str(foreign_parent_id),
                        "child_ref": str(own.id),
                    }
                ],
            )
        )


def test_valid_create_is_backend_identified_versioned_and_audited() -> None:
    service, repository = _service()
    request = _request(
        [
            {
                "ref": f"local:{uuid.uuid4()}",
                "node_id": None,
                "intent": "create",
                "node_type": "structure_root",
                "code": None,
                "name": "Governed root",
                "description": None,
                "metadata": {},
                "position": {"x": 25, "y": 50},
            }
        ]
    )

    result = service.save(request)

    assert result["revision"] == 1
    assert len(repository.node_items) == 1
    assert repository.node_items[0].code.startswith("structure_root-")
    assert len(repository.audit_items) == 4
    assert all(
        item.organization_id == repository.organization_id
        for item in repository.audit_items
    )


@pytest.mark.parametrize(
    ("hierarchy", "error"),
    [
        (
            lambda first, second, third: [
                {"parent_ref": str(first.id), "child_ref": str(first.id)}
            ],
            "self_reference",
        ),
        (
            lambda first, second, third: [
                {"parent_ref": str(first.id), "child_ref": str(second.id)},
                {"parent_ref": str(second.id), "child_ref": str(first.id)},
            ],
            "cycle",
        ),
        (
            lambda first, second, third: [
                {"parent_ref": str(first.id), "child_ref": str(second.id)},
                {"parent_ref": str(second.id), "child_ref": str(third.id)},
                {"parent_ref": str(third.id), "child_ref": str(first.id)},
            ],
            "cycle",
        ),
        (
            lambda first, second, third: [
                {"parent_ref": str(first.id), "child_ref": str(third.id)},
                {"parent_ref": str(second.id), "child_ref": str(third.id)},
            ],
            "multiple_parents",
        ),
        (
            lambda first, second, third: [
                {"parent_ref": str(first.id), "child_ref": str(second.id)},
                {"parent_ref": str(first.id), "child_ref": str(second.id)},
            ],
            "duplicate_relationship",
        ),
    ],
)
def test_invalid_hierarchy_is_rejected_without_partial_mutation(
    hierarchy,
    error,
) -> None:
    service, repository = _service()
    first = _node(repository.organization_id, "first")
    second = _node(repository.organization_id, "second")
    third = _node(repository.organization_id, "third")
    repository.node_items = [first, second, third]
    original = [(item.id, item.parent_node_id, item.status) for item in repository.node_items]

    with pytest.raises(OrganizationStructureError, match=error):
        service.save(
            _request(
                [_proposal(first), _proposal(second), _proposal(third)],
                hierarchy(first, second, third),
            )
        )

    assert [
        (item.id, item.parent_node_id, item.status)
        for item in repository.node_items
    ] == original
    assert repository.audit_items == []


def test_archived_or_unknown_type_and_duplicate_codes_are_rejected() -> None:
    service, repository = _service()
    repository.catalog_items.append(_catalog("archived_type", status="archived"))
    first_ref = f"local:{uuid.uuid4()}"
    second_ref = f"local:{uuid.uuid4()}"
    base = {
        "node_id": None,
        "intent": "create",
        "node_type": "structure_group",
        "code": "duplicate",
        "name": "Node",
        "description": None,
        "metadata": {},
        "position": {},
    }
    with pytest.raises(OrganizationStructureError, match="code_conflict"):
        service.save(
            _request(
                [
                    {**base, "ref": first_ref},
                    {**base, "ref": second_ref},
                ]
            )
        )

    with pytest.raises(OrganizationStructureError, match="type_unavailable"):
        service.save(
            _request(
                [
                    {
                        **base,
                        "ref": first_ref,
                        "code": "archived",
                        "node_type": "archived_type",
                    }
                ]
            )
        )

    with pytest.raises(OrganizationStructureError, match="type_unavailable"):
        service.save(
            _request(
                [
                    {
                        **base,
                        "ref": first_ref,
                        "code": "unknown",
                        "node_type": "unregistered_type",
                    }
                ]
            )
        )


def test_revision_conflict_and_persisted_retry_are_deterministic() -> None:
    service, repository = _service()
    mutation_key = uuid.uuid4()
    request = _request(
        [
            {
                "ref": f"local:{uuid.uuid4()}",
                "node_id": None,
                "intent": "create",
                "node_type": "structure_root",
                "code": None,
                "name": "Root",
                "description": None,
                "metadata": {},
                "position": {},
            }
        ],
        mutation_key=mutation_key,
    )
    first = service.save(request)
    replay = service.save(request)

    assert first["revision"] == 1
    assert replay["revision"] == 1
    assert replay["replayed"] is True
    assert len(repository.node_items) == 1

    with pytest.raises(OrganizationStructureError, match="revision_conflict"):
        service.save(
            _request(
                [_proposal(repository.node_items[0])],
                revision=0,
            )
        )


def test_archive_requires_all_active_descendants_and_restore_checks_parent() -> None:
    service, repository = _service()
    parent = _node(repository.organization_id, "parent")
    child = _node(repository.organization_id, "child", parent_node_id=parent.id)
    repository.node_items = [parent, child]
    hierarchy = [{"parent_ref": str(parent.id), "child_ref": str(child.id)}]

    with pytest.raises(OrganizationStructureError, match="active_descendants"):
        service.save(
            _request(
                [_proposal(parent, intent="archive"), _proposal(child)],
                hierarchy,
            )
        )

    archived = service.save(
        _request(
            [
                _proposal(parent, intent="archive"),
                _proposal(child, intent="archive"),
            ],
            hierarchy,
        )
    )
    assert archived["revision"] == 1
    assert all(item.status == "archived" for item in repository.node_items)

    repository.aggregate_item.revision = 1
    with pytest.raises(
        OrganizationStructureError,
        match="active_child_archived_parent",
    ):
        service.save(
            _request(
                [_proposal(parent), _proposal(child, intent="restore")],
                hierarchy,
                revision=1,
            )
        )


def test_legacy_contains_is_only_normalized_when_unambiguous_and_explicit() -> None:
    service, repository = _service()
    parent = _node(repository.organization_id, "parent")
    other_parent = _node(repository.organization_id, "other")
    child = _node(repository.organization_id, "child")
    safe = OrganizationRelationship(
        id=uuid.uuid4(),
        organization_id=repository.organization_id,
        source_node_id=parent.id,
        target_node_id=child.id,
        relationship_type="contains",
        metadata_json={},
        status="active",
    )
    repository.node_items = [parent, child]
    repository.relationship_items = [safe]

    analysis = analyze_legacy_contains(repository.node_items, [safe])
    assert analysis.normalizable[child.id] is safe
    preview = service.runtime()
    assert preview["revision"] == 0
    assert len(preview["legacy_normalization_candidates"]) == 1
    candidate = preview["legacy_normalization_candidates"][0]
    assert candidate["relationship_id"] == safe.id
    assert candidate["legacy_relationship_type"] == "contains"
    assert candidate["proposed_parent"] == {
        "node_id": parent.id,
        "code": parent.code,
        "name": parent.name,
    }
    assert candidate["proposed_child"] == {
        "node_id": child.id,
        "code": child.code,
        "name": child.name,
    }
    assert candidate["proposed_result"]["authority"] == "parent_node_id"
    assert candidate["normalizable_reason"] == (
        "legacy_contains_single_in_scope_parent_without_cycle"
    )
    assert child.parent_node_id is None
    assert safe.status == "active"
    assert repository.audit_items == []

    result = service.save(
        _request(
            [_proposal(parent), _proposal(child)],
            normalize_legacy_contains=True,
        )
    )
    assert result["revision"] == 1
    assert child.parent_node_id == parent.id
    assert safe.status == "archived"

    ambiguous_child = _node(repository.organization_id, "ambiguous")
    first = OrganizationRelationship(
        id=uuid.uuid4(),
        organization_id=repository.organization_id,
        source_node_id=parent.id,
        target_node_id=ambiguous_child.id,
        relationship_type="contains",
        metadata_json={},
        status="active",
    )
    second = OrganizationRelationship(
        id=uuid.uuid4(),
        organization_id=repository.organization_id,
        source_node_id=other_parent.id,
        target_node_id=ambiguous_child.id,
        relationship_type="contains",
        metadata_json={},
        status="active",
    )
    ambiguous = analyze_legacy_contains(
        [parent, other_parent, ambiguous_child],
        [first, second],
    )
    assert ambiguous.normalizable == {}
    assert set(ambiguous.reasons.values()) == {"legacy_contains_multiple_parents"}
    repository.node_items = [parent, other_parent, ambiguous_child]
    repository.relationship_items = [first, second]
    ambiguous_runtime = service.runtime()
    assert ambiguous_runtime["legacy_normalization_candidates"] == []
    assert {
        warning["code"]
        for warning in ambiguous_runtime["legacy_warnings"]
    } == {"legacy_contains_multiple_parents"}


def test_unregistered_legacy_type_remains_readable_and_unavailable_for_new_nodes() -> None:
    service, repository = _service()
    legacy = _node(
        repository.organization_id,
        "legacy",
        node_type="unregistered_historical_type",
    )
    repository.node_items = [legacy]

    runtime = service.runtime()

    legacy_catalog = next(
        item
        for item in runtime["node_type_catalog"]
        if item["code"] == legacy.node_type
    )
    assert legacy_catalog["name"] == "Unregistered Historical Type"
    assert legacy_catalog["legacy"] is True
    assert legacy_catalog["available_for_new"] is False
    assert runtime["nodes"][0]["node_type"] == legacy.node_type


def test_convergence_preview_requires_explicit_targets_and_is_read_only() -> None:
    service, repository = _service()
    parent = _node(
        repository.organization_id,
        "legacy-parent",
        node_type="historical_group",
    )
    child = _node(
        repository.organization_id,
        "legacy-child",
        node_type="historical_node",
    )
    relationship = OrganizationRelationship(
        id=uuid.uuid4(),
        organization_id=repository.organization_id,
        source_node_id=parent.id,
        target_node_id=child.id,
        relationship_type="contains",
        metadata_json={},
        status="active",
    )
    repository.node_items = [parent, child]
    repository.relationship_items = [relationship]

    preview = service.convergence_preview(_convergence_preview_request([]))

    assert preview["ready"] is False
    assert {
        item["code"] for item in preview["blockers"]
    } == {"organization_structure_convergence_target_required"}
    assert preview["hierarchy_changes"][0]["detected_parent"] == {
        "name": parent.name,
        "code": parent.code,
    }
    assert preview["hierarchy_changes"][0]["projected_parent"] == {
        "name": parent.name,
        "code": parent.code,
    }
    assert parent.node_type == "historical_group"
    assert child.node_type == "historical_node"
    assert child.parent_node_id is None
    assert relationship.status == "active"
    assert repository.aggregate_item is None
    assert repository.audit_items == []


def test_convergence_applies_in_place_normalizes_hierarchy_and_is_audited() -> None:
    service, repository = _service()
    parent = _node(
        repository.organization_id,
        "legacy-parent",
        node_type="historical_group",
    )
    child = _node(
        repository.organization_id,
        "legacy-child",
        node_type="historical_node",
    )
    child.metadata_json = {"classification": "governed"}
    relationship = OrganizationRelationship(
        id=uuid.uuid4(),
        organization_id=repository.organization_id,
        source_node_id=parent.id,
        target_node_id=child.id,
        relationship_type="contains",
        metadata_json={"source": "persisted"},
        status="active",
    )
    repository.node_items = [parent, child]
    repository.relationship_items = [relationship]
    original_parent_id = parent.id
    original_child_id = child.id
    targets = [
        {
            "node_id": parent.id,
            "target_node_type": "structure_group",
        },
        {
            "node_id": child.id,
            "target_node_type": "structure_node",
        },
    ]
    preview = service.convergence_preview(
        _convergence_preview_request(targets)
    )
    mutation_key = uuid.uuid4()
    request = OrganizationStructureConvergenceApplyRequest(
        targets=targets,
        normalize_legacy_contains=True,
        expected_revision=preview["source_revision"],
        mutation_key=mutation_key,
        preview_hash=preview["preview_hash"],
    )

    applied = service.apply_convergence(request)
    replayed = service.apply_convergence(request)

    assert preview["ready"] is True
    assert applied["applied"] is True
    assert applied["revision"] == 1
    assert parent.id == original_parent_id
    assert child.id == original_child_id
    assert parent.node_type == "structure_group"
    assert child.node_type == "structure_node"
    assert child.metadata_json == {"classification": "governed"}
    assert child.parent_node_id == parent.id
    assert relationship.status == "archived"
    assert replayed["replayed"] is True
    assert replayed["revision"] == 1
    assert {
        item.action
        for item in repository.audit_items
        if isinstance(item, AuditHistory)
    } >= {
        "legacy_type_converged",
        "legacy_converged",
        "legacy_normalized",
        "legacy_convergence_applied",
    }
    convergence_history = next(
        item
        for item in repository.audit_items
        if isinstance(item, AuditHistory)
        and item.action == "legacy_convergence_applied"
    )
    assert convergence_history.organization_id == repository.organization_id
    assert convergence_history.actor_id == "authenticated-user"
    assert convergence_history.after_state["result"] == "applied"


def test_convergence_revalidates_preview_and_rejects_ineligible_targets() -> None:
    service, repository = _service()
    legacy = _node(
        repository.organization_id,
        "legacy",
        node_type="historical_type",
    )
    repository.node_items = [legacy]
    repository.catalog_items.append(
        _catalog("unavailable_type", available_for_new=False)
    )
    unavailable = service.convergence_preview(
        _convergence_preview_request(
            [
                {
                    "node_id": legacy.id,
                    "target_node_type": "unavailable_type",
                }
            ]
        )
    )
    assert unavailable["ready"] is False
    assert unavailable["blockers"][0]["code"] == (
        "organization_structure_convergence_target_unavailable"
    )

    targets = [
        {
            "node_id": legacy.id,
            "target_node_type": "structure_node",
        }
    ]
    preview = service.convergence_preview(
        _convergence_preview_request(targets)
    )
    legacy.updated_at = datetime.now(UTC)
    with pytest.raises(
        OrganizationStructureError,
        match="convergence_preview_stale",
    ):
        service.apply_convergence(
            OrganizationStructureConvergenceApplyRequest(
                targets=targets,
                normalize_legacy_contains=True,
                expected_revision=preview["source_revision"],
                mutation_key=uuid.uuid4(),
                preview_hash=preview["preview_hash"],
            )
        )
    assert legacy.node_type == "historical_type"
    assert repository.audit_items == []

    with pytest.raises(
        OrganizationStructureError,
        match="convergence_node_not_found",
    ):
        service.convergence_preview(
            _convergence_preview_request(
                [
                    {
                        "node_id": uuid.uuid4(),
                        "target_node_type": "structure_node",
                    }
                ]
            )
        )


def test_convergence_blocks_cycles_and_incompatible_resulting_hierarchy() -> None:
    service, repository = _service()
    parent = _node(
        repository.organization_id,
        "legacy-parent",
        node_type="historical_group",
    )
    child = _node(
        repository.organization_id,
        "legacy-child",
        parent_node_id=parent.id,
        node_type="historical_node",
    )
    parent.parent_node_id = child.id
    repository.node_items = [parent, child]
    targets = [
        {
            "node_id": parent.id,
            "target_node_type": "structure_group",
        },
        {
            "node_id": child.id,
            "target_node_type": "structure_node",
        },
    ]

    cyclic = service.convergence_preview(
        _convergence_preview_request(targets)
    )

    assert cyclic["ready"] is False
    assert "organization_structure_convergence_cycle" in {
        item["code"] for item in cyclic["blockers"]
    }
    assert parent.node_type == "historical_group"
    assert child.node_type == "historical_node"

    parent.parent_node_id = None
    child.parent_node_id = parent.id
    targets[0]["target_node_type"] = "structure_node"
    incompatible = service.convergence_preview(
        _convergence_preview_request(targets)
    )
    assert incompatible["ready"] is False
    assert "organization_structure_parent_disallows_children" in {
        item["code"] for item in incompatible["blockers"]
    }
    with pytest.raises(
        OrganizationStructureError,
        match="organization_structure_convergence_blocked",
    ):
        service.apply_convergence(
            OrganizationStructureConvergenceApplyRequest(
                targets=targets,
                normalize_legacy_contains=True,
                expected_revision=incompatible["source_revision"],
                mutation_key=uuid.uuid4(),
                preview_hash=incompatible["preview_hash"],
            )
        )
    assert parent.node_type == "historical_group"
    assert child.node_type == "historical_node"
    assert repository.audit_items == []


def test_convergence_uses_admin_permission_and_context_organization_authority() -> None:
    service, repository = _service()
    legacy = _node(
        repository.organization_id,
        "legacy",
        node_type="historical_type",
    )
    repository.node_items = [legacy]
    service.actor_permissions = frozenset({READ_PERMISSION})

    with pytest.raises(
        OrganizationStructureError,
        match="organization_structure_permission_required",
    ):
        service.convergence_preview(_convergence_preview_request([]))

    schema = OrganizationStructureConvergencePreviewRequest.model_json_schema()
    assert "organization_id" not in schema["properties"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OrganizationStructureConvergencePreviewRequest.model_validate(
            {
                "organization_id": str(uuid.uuid4()),
                "targets": [],
                "normalize_legacy_contains": True,
            }
        )


def test_frontend_has_no_hardcoded_organization_node_type_catalog() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "admin-portal"
        / "components"
        / "organization"
        / "OrganizationBuilder.tsx"
    ).read_text()

    for legacy_type in (
        "organization_root",
        "organization_unit",
        "location_node",
        "system_node",
        "asset_node",
        "custom_node",
    ):
        assert legacy_type not in source
    assert "Asset Node" not in source
    assert "legacyTypeCompatibility" in source
    assert "item.available_for_new && item.status === 'active'" in source
    assert "previewOrganizationStructureConvergence" in source
    assert "applyOrganizationStructureConvergence" in source
    assert 'href="/documents"' in source


def test_frontend_uses_localized_catalog_codes_and_accessible_node_states() -> None:
    portal_root = Path(__file__).resolve().parents[2] / "admin-portal"
    source = (
        portal_root
        / "components"
        / "organization"
        / "OrganizationBuilder.tsx"
    ).read_text()
    styles = (portal_root / "app" / "globals.css").read_text()

    for catalog_code in ("structure_root", "structure_group", "structure_node"):
        assert catalog_code in source
    assert "localizedCatalogName(item, t)" in source
    assert "candidate.proposed_parent.name" in source
    assert "candidate.proposed_child.name" in source
    assert "candidate.relationship_id" not in source
    assert "edges={displayedEdges}" in source
    assert "nodeTypes={STRUCTURE_NODE_TYPES}" in source

    for selector in (
        ".structure-graph-node.is-archived",
        ".react-flow__node-organizationStructure:hover",
        ".react-flow__node-organizationStructure.selected",
        ".react-flow__node-organizationStructure:focus-visible",
        ".structure-edge-normalization-preview",
        ".structure-convergence-targets",
        ".structure-convergence-preview-nodes",
    ):
        assert selector in styles
