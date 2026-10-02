from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.core import (
    Organization,
    OrganizationNode,
    OrganizationNodeType,
    OrganizationRelationship,
    OrganizationStructureAggregate,
)
from app.repositories.organization_structure import OrganizationStructureRepository
from app.schemas.organization_structure import (
    OrganizationStructureConvergenceApplyRequest,
    OrganizationStructureConvergencePreviewRequest,
    OrganizationStructureNodeProposal,
    OrganizationStructureSaveRequest,
)

READ_PERMISSION = "reference_tenant:read"
ADMIN_PERMISSION = "reference_tenant:administer"
MAX_NODES = 1000
MAX_RELATIONSHIPS = 2000
ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
LEGACY_HIERARCHY_TYPE = "contains"
NODE_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
METADATA_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")
SENSITIVE_METADATA_FRAGMENTS = (
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


class OrganizationStructureError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class LegacyContainsAnalysis:
    normalizable: dict[uuid.UUID, OrganizationRelationship]
    reasons: dict[uuid.UUID, str]


def _cycle_nodes(parent_by_child: dict[uuid.UUID, uuid.UUID | None]) -> set[uuid.UUID]:
    cycle_members: set[uuid.UUID] = set()
    completed: set[uuid.UUID] = set()
    for start in parent_by_child:
        if start in completed:
            continue
        path: list[uuid.UUID] = []
        positions: dict[uuid.UUID, int] = {}
        current: uuid.UUID | None = start
        while current is not None and current in parent_by_child and current not in completed:
            if current in positions:
                cycle_members.update(path[positions[current] :])
                break
            positions[current] = len(path)
            path.append(current)
            current = parent_by_child.get(current)
        completed.update(path)
    return cycle_members


def analyze_legacy_contains(
    nodes: list[OrganizationNode],
    relationships: list[OrganizationRelationship],
) -> LegacyContainsAnalysis:
    nodes_by_id = {item.id: item for item in nodes}
    contains = [
        item
        for item in relationships
        if item.status == ACTIVE_STATUS and item.relationship_type == LEGACY_HIERARCHY_TYPE
    ]
    incoming: dict[uuid.UUID, list[OrganizationRelationship]] = defaultdict(list)
    reasons: dict[uuid.UUID, str] = {}
    for relationship in contains:
        source = nodes_by_id.get(relationship.source_node_id)
        target = nodes_by_id.get(relationship.target_node_id)
        if source is None or target is None:
            reasons[relationship.id] = "legacy_contains_endpoint_missing"
        elif source.organization_id != target.organization_id:
            reasons[relationship.id] = "legacy_contains_cross_organization"
        elif source.id == target.id:
            reasons[relationship.id] = "legacy_contains_self_reference"
        else:
            incoming[target.id].append(relationship)

    candidates: dict[uuid.UUID, OrganizationRelationship] = {}
    for child_id, relationships_for_child in incoming.items():
        child = nodes_by_id[child_id]
        if len(relationships_for_child) > 1:
            for relationship in relationships_for_child:
                reasons[relationship.id] = "legacy_contains_multiple_parents"
            continue
        relationship = relationships_for_child[0]
        if child.parent_node_id not in {None, relationship.source_node_id}:
            reasons[relationship.id] = "legacy_contains_conflicts_with_primary_parent"
            continue
        candidates[child_id] = relationship

    proposed_parents = {item.id: item.parent_node_id for item in nodes}
    for child_id, relationship in candidates.items():
        proposed_parents[child_id] = relationship.source_node_id
    cyclic = _cycle_nodes(proposed_parents)
    normalizable: dict[uuid.UUID, OrganizationRelationship] = {}
    for child_id, relationship in candidates.items():
        if child_id in cyclic or relationship.source_node_id in cyclic:
            reasons[relationship.id] = "legacy_contains_cycle"
        else:
            normalizable[child_id] = relationship
    return LegacyContainsAnalysis(normalizable=normalizable, reasons=reasons)


def _payload_hash(payload: OrganizationStructureSaveRequest) -> str:
    data = payload.model_dump(mode="json")
    data.pop("mutation_key", None)
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _convergence_payload_hash(
    payload: OrganizationStructureConvergenceApplyRequest,
) -> str:
    data = payload.model_dump(mode="json")
    data.pop("mutation_key", None)
    data.pop("expected_revision", None)
    serialized = json.dumps(
        {"operation": "organization_structure_convergence", **data},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _catalog_item(item: OrganizationNodeType) -> dict[str, Any]:
    allowed = item.allowed_child_types if isinstance(item.allowed_child_types, list) else []
    presentation = (
        item.presentation_metadata if isinstance(item.presentation_metadata, dict) else {}
    )
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "allows_children": item.allows_children,
        "allowed_child_types": [
            str(value) for value in allowed if isinstance(value, str)
        ],
        "presentation": {
            key: value
            for key, value in presentation.items()
            if key in {"color", "icon", "shape"} and isinstance(value, str)
        },
        "display_order": item.display_order,
        "available_for_new": item.available_for_new and item.status == ACTIVE_STATUS,
        "edition": item.edition,
        "legacy": False,
    }


def _legacy_catalog_item(code: str, order: int) -> dict[str, Any]:
    return {
        "id": None,
        "code": code,
        "name": code.replace("_", " ").replace("-", " ").strip().title(),
        "description": "Existing unregistered node type retained for compatibility.",
        "status": "legacy",
        "allows_children": True,
        "allowed_child_types": [],
        "presentation": {"shape": "legacy"},
        "display_order": order,
        "available_for_new": False,
        "edition": "community",
        "legacy": True,
    }


def _safe_existing_metadata(value: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, dict) or len(value) > 32:
        return {}, False
    result: dict[str, Any] = {}
    valid = True
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not METADATA_KEY_PATTERN.fullmatch(key)
            or any(fragment in key.casefold() for fragment in SENSITIVE_METADATA_FRAGMENTS)
            or (item is not None and not isinstance(item, str | int | float | bool))
            or (isinstance(item, str) and len(item) > 1024)
        ):
            valid = False
            continue
        result[key] = item
    return result, valid


def _safe_existing_position(value: Any) -> tuple[dict[str, float], bool]:
    if not isinstance(value, dict) or set(value) - {"x", "y"}:
        return {}, False
    result: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(item, int | float) or isinstance(item, bool):
            return {}, False
        number = float(item)
        if not -100000 <= number <= 100000:
            return {}, False
        result[key] = number
    return result, True


class OrganizationStructureService:
    def __init__(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID,
        actor_reference: str,
        actor_permissions: frozenset[str],
        correlation_id: str | None,
    ) -> None:
        self.organization_id = organization_id
        self.actor_reference = actor_reference
        self.actor_permissions = actor_permissions
        self.correlation_id = correlation_id
        self.repository = OrganizationStructureRepository(db, organization_id)

    def runtime(self, *, replayed: bool = False) -> dict[str, Any]:
        self._require(READ_PERMISSION)
        organization = self.repository.organization(for_share=True)
        if organization is None:
            raise OrganizationStructureError(404, "organization_structure_not_found")
        aggregate = self.repository.aggregate()
        node_types = self.repository.node_types()
        nodes = self.repository.nodes()
        relationships = self.repository.relationships()
        return self._runtime(
            organization,
            aggregate,
            node_types,
            nodes,
            relationships,
            replayed=replayed,
        )

    def convergence_preview(
        self,
        payload: OrganizationStructureConvergencePreviewRequest,
    ) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        organization = self.repository.organization(for_share=True)
        if organization is None:
            raise OrganizationStructureError(404, "organization_structure_not_found")
        aggregate = self.repository.aggregate()
        return self._convergence_preview(
            payload,
            revision=aggregate.revision if aggregate else 0,
            catalog=self.repository.node_types(),
            nodes=self.repository.nodes(),
            relationships=self.repository.relationships(),
        )

    def apply_convergence(
        self,
        payload: OrganizationStructureConvergenceApplyRequest,
    ) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        organization = self.repository.organization(for_update=True)
        if organization is None:
            raise OrganizationStructureError(404, "organization_structure_not_found")
        aggregate = self.repository.aggregate(for_update=True)
        if aggregate is None:
            aggregate = OrganizationStructureAggregate(
                organization_id=self.organization_id,
                revision=0,
                created_by=self.actor_reference,
                updated_by=self.actor_reference,
            )
            self.repository.add(aggregate)
            self.repository.flush()

        payload_hash = _convergence_payload_hash(payload)
        mutation_key = str(payload.mutation_key)
        if aggregate.last_mutation_key == mutation_key:
            if aggregate.last_payload_hash != payload_hash:
                raise OrganizationStructureError(
                    409,
                    "organization_structure_convergence_idempotency_conflict",
                )
            return self._convergence_apply_result(
                organization=organization,
                aggregate=aggregate,
                previous_revision=aggregate.revision,
                changes=[],
                applied=False,
                replayed=True,
            )
        if payload.expected_revision != aggregate.revision:
            raise OrganizationStructureError(
                409,
                "organization_structure_convergence_revision_conflict",
            )

        catalog = self.repository.node_types(for_share=True)
        nodes = self.repository.nodes(for_update=True)
        relationships = self.repository.relationships(for_update=True)
        preview_payload = OrganizationStructureConvergencePreviewRequest(
            targets=payload.targets,
            normalize_legacy_contains=payload.normalize_legacy_contains,
        )
        preview = self._convergence_preview(
            preview_payload,
            revision=aggregate.revision,
            catalog=catalog,
            nodes=nodes,
            relationships=relationships,
        )
        if payload.preview_hash != preview["preview_hash"]:
            raise OrganizationStructureError(
                409,
                "organization_structure_convergence_preview_stale",
            )
        if not preview["ready"]:
            raise OrganizationStructureError(
                409,
                "organization_structure_convergence_blocked",
            )

        target_by_node = {
            item.node_id: item.target_node_type for item in payload.targets
        }
        legacy = analyze_legacy_contains(nodes, relationships)
        normalized_by_child = (
            legacy.normalizable if payload.normalize_legacy_contains else {}
        )
        changes: list[dict[str, Any]] = []
        for node in nodes:
            target_type = target_by_node.get(node.id, node.node_type)
            normalized_relationship = normalized_by_child.get(node.id)
            target_parent = (
                normalized_relationship.source_node_id
                if normalized_relationship is not None
                else node.parent_node_id
            )
            if (
                target_type == node.node_type
                and target_parent == node.parent_node_id
            ):
                continue
            before = self._node_state(node)
            type_changed = target_type != node.node_type
            parent_changed = target_parent != node.parent_node_id
            node.node_type = target_type
            node.parent_node_id = target_parent
            node.updated_by = self.actor_reference
            self.repository.add(node)
            after = self._node_state(node)
            if type_changed and parent_changed:
                action = "legacy_converged"
            elif type_changed:
                action = "legacy_type_converged"
            else:
                action = "legacy_parent_normalized"
            changes.append(
                {
                    "resource": "node",
                    "id": str(node.id),
                    "action": action,
                    "code": node.code,
                    "previous_node_type": before["node_type"],
                    "node_type": after["node_type"],
                    "parent_changed": parent_changed,
                }
            )
            self._audit_node(
                action,
                node,
                before=before,
                after=after,
                parent_id=target_parent,
            )

        normalized_relationship_ids = {
            relationship.id for relationship in normalized_by_child.values()
        }
        for relationship in relationships:
            if (
                relationship.id not in normalized_relationship_ids
                or relationship.status != ACTIVE_STATUS
            ):
                continue
            before_status = relationship.status
            relationship.status = ARCHIVED_STATUS
            relationship.updated_by = self.actor_reference
            self.repository.add(relationship)
            changes.append(
                {
                    "resource": "relationship",
                    "id": str(relationship.id),
                    "action": "legacy_normalized",
                    "relationship_type": relationship.relationship_type,
                }
            )
            self._audit_relationship(
                "legacy_normalized",
                relationship,
                before_status=before_status,
                after_status=relationship.status,
            )

        previous_revision = aggregate.revision
        if changes:
            aggregate.revision += 1
            aggregate.last_mutation_key = mutation_key
            aggregate.last_payload_hash = payload_hash
            aggregate.updated_by = self.actor_reference
            self.repository.add(aggregate)
            self._audit_convergence(
                previous_revision=previous_revision,
                new_revision=aggregate.revision,
                changes=changes,
            )
            self.repository.flush()

        return self._convergence_apply_result(
            organization=organization,
            aggregate=aggregate,
            previous_revision=previous_revision,
            changes=changes,
            applied=bool(changes),
            replayed=False,
        )

    def save(self, payload: OrganizationStructureSaveRequest) -> dict[str, Any]:
        self._require(ADMIN_PERMISSION)
        organization = self.repository.organization(for_update=True)
        if organization is None:
            raise OrganizationStructureError(404, "organization_structure_not_found")
        aggregate = self.repository.aggregate(for_update=True)
        if aggregate is None:
            aggregate = OrganizationStructureAggregate(
                organization_id=self.organization_id,
                revision=0,
                created_by=self.actor_reference,
                updated_by=self.actor_reference,
            )
            self.repository.add(aggregate)
            self.repository.flush()

        payload_hash = _payload_hash(payload)
        mutation_key = str(payload.mutation_key)
        if payload.expected_revision != aggregate.revision:
            if (
                aggregate.last_mutation_key == mutation_key
                and aggregate.last_payload_hash == payload_hash
            ):
                return self._runtime(
                    organization,
                    aggregate,
                    self.repository.node_types(),
                    self.repository.nodes(),
                    self.repository.relationships(),
                    replayed=True,
                )
            raise OrganizationStructureError(409, "organization_structure_revision_conflict")

        node_types = self.repository.node_types()
        nodes = self.repository.nodes(for_update=True)
        relationships = self.repository.relationships(for_update=True)
        changes = self._apply(
            payload,
            aggregate=aggregate,
            catalog=node_types,
            nodes=nodes,
            relationships=relationships,
        )
        if changes:
            previous_revision = aggregate.revision
            aggregate.revision += 1
            aggregate.last_mutation_key = mutation_key
            aggregate.last_payload_hash = payload_hash
            aggregate.updated_by = self.actor_reference
            self.repository.add(aggregate)
            self._audit_aggregate(
                previous_revision=previous_revision,
                new_revision=aggregate.revision,
                changes=changes,
            )
            self.repository.flush()

        return self._runtime(
            organization,
            aggregate,
            node_types,
            self.repository.nodes(),
            self.repository.relationships(),
            replayed=False,
        )

    def _convergence_preview(
        self,
        payload: OrganizationStructureConvergencePreviewRequest,
        *,
        revision: int,
        catalog: list[OrganizationNodeType],
        nodes: list[OrganizationNode],
        relationships: list[OrganizationRelationship],
    ) -> dict[str, Any]:
        nodes_by_id = {item.id: item for item in nodes}
        catalog_by_code = {item.code: item for item in catalog}
        registered_codes = set(catalog_by_code)
        target_by_node = {
            item.node_id: item.target_node_type for item in payload.targets
        }
        if set(target_by_node) - set(nodes_by_id):
            raise OrganizationStructureError(
                404,
                "organization_structure_convergence_node_not_found",
            )

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        projected_types = {item.id: item.node_type for item in nodes}
        legacy_node_ids = {
            item.id for item in nodes if item.node_type not in registered_codes
        }

        for node_id in sorted(legacy_node_ids, key=str):
            node = nodes_by_id[node_id]
            target_code = target_by_node.get(node_id)
            if target_code is None:
                blockers.append(
                    {
                        "code": "organization_structure_convergence_target_required",
                        "node_id": node_id,
                    }
                )
                continue
            target = catalog_by_code.get(target_code)
            if (
                target is None
                or target.status != ACTIVE_STATUS
                or not target.available_for_new
            ):
                blockers.append(
                    {
                        "code": "organization_structure_convergence_target_unavailable",
                        "node_id": node_id,
                    }
                )
                continue
            projected_types[node_id] = target.code
            if node.status != ACTIVE_STATUS:
                warnings.append(
                    {
                        "code": "organization_structure_convergence_node_archived",
                        "node_id": node_id,
                    }
                )

        for node_id, target_code in target_by_node.items():
            if node_id in legacy_node_ids:
                continue
            node = nodes_by_id[node_id]
            if node.node_type != target_code:
                blockers.append(
                    {
                        "code": "organization_structure_convergence_node_not_legacy",
                        "node_id": node_id,
                    }
                )
            else:
                warnings.append(
                    {
                        "code": "organization_structure_convergence_already_applied",
                        "node_id": node_id,
                    }
                )

        legacy = analyze_legacy_contains(nodes, relationships)
        normalizable_relationship_ids = {
            item.id for item in legacy.normalizable.values()
        }
        projected_parents = {item.id: item.parent_node_id for item in nodes}
        hierarchy_changes: list[dict[str, Any]] = []
        for relationship in relationships:
            if (
                relationship.status != ACTIVE_STATUS
                or relationship.relationship_type != LEGACY_HIERARCHY_TYPE
            ):
                continue
            parent = nodes_by_id.get(relationship.source_node_id)
            child = nodes_by_id.get(relationship.target_node_id)
            reason = legacy.reasons.get(relationship.id)
            normalizable = relationship.id in normalizable_relationship_ids
            if reason is not None:
                blockers.append(
                    {
                        "code": reason,
                        "relationship_id": relationship.id,
                    }
                )
            elif not payload.normalize_legacy_contains:
                blockers.append(
                    {
                        "code": (
                            "organization_structure_convergence_contains_"
                            "normalization_required"
                        ),
                        "relationship_id": relationship.id,
                    }
                )
            elif normalizable and child is not None:
                projected_parents[child.id] = relationship.source_node_id
            hierarchy_changes.append(
                {
                    "relationship_id": relationship.id,
                    "legacy_relationship_type": relationship.relationship_type,
                    "current_parent": self._safe_node_reference(
                        nodes_by_id.get(child.parent_node_id)
                        if child is not None and child.parent_node_id is not None
                        else None
                    ),
                    "detected_parent": self._safe_node_reference(parent),
                    "child": self._safe_node_reference(child),
                    "projected_parent": (
                        self._safe_node_reference(parent)
                        if normalizable and payload.normalize_legacy_contains
                        else self._safe_node_reference(
                            nodes_by_id.get(child.parent_node_id)
                            if child is not None
                            and child.parent_node_id is not None
                            else None
                        )
                    ),
                    "normalizable": normalizable,
                    "blocker": reason,
                }
            )

        cyclic = _cycle_nodes(projected_parents)
        for node_id in sorted(cyclic, key=str):
            blockers.append(
                {
                    "code": "organization_structure_convergence_cycle",
                    "node_id": node_id,
                }
            )

        projected = {
            item.id: {
                **self._node_state(item),
                "node_type": projected_types[item.id],
                "parent_node_id": projected_parents[item.id],
            }
            for item in nodes
        }
        if not cyclic:
            try:
                self._validate_hierarchy(
                    projected,
                    projected_parents,
                    catalog_by_code=catalog_by_code,
                )
            except OrganizationStructureError as exc:
                blockers.append({"code": exc.code})

        preview_nodes = []
        candidate_node_ids = legacy_node_ids | set(target_by_node)
        for node_id in sorted(
            candidate_node_ids,
            key=lambda value: (
                nodes_by_id[value].name.casefold(),
                nodes_by_id[value].code,
                str(value),
            ),
        ):
            node = nodes_by_id[node_id]
            target_code = target_by_node.get(node_id)
            target = catalog_by_code.get(target_code) if target_code else None
            current_parent = (
                nodes_by_id.get(node.parent_node_id)
                if node.parent_node_id is not None
                else None
            )
            projected_parent_id = projected_parents.get(node.id)
            projected_parent = (
                nodes_by_id.get(projected_parent_id)
                if projected_parent_id is not None
                else None
            )
            node_blockers = [
                item
                for item in blockers
                if item.get("node_id") == node.id
            ]
            node_warnings = [
                item
                for item in warnings
                if item.get("node_id") == node.id
            ]
            preview_nodes.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "code": node.code,
                    "status": node.status,
                    "current_type": {
                        "code": node.node_type,
                        "legacy": node.id in legacy_node_ids,
                    },
                    "target_type": (
                        {
                            "code": target.code,
                            "name": target.name,
                        }
                        if target is not None
                        else None
                    ),
                    "current_parent": self._safe_node_reference(current_parent),
                    "projected_parent": self._safe_node_reference(projected_parent),
                    "blockers": node_blockers,
                    "warnings": node_warnings,
                    "impact": {
                        "node_identity": "preserved",
                        "metadata": "preserved",
                        "references": "preserved",
                        "document_associations": "preserved",
                    },
                }
            )

        fingerprint = {
            "revision": revision,
            "targets": sorted(
                (
                    {
                        "node_id": str(node_id),
                        "target_node_type": target,
                    }
                    for node_id, target in target_by_node.items()
                ),
                key=lambda item: item["node_id"],
            ),
            "normalize_legacy_contains": payload.normalize_legacy_contains,
            "catalog": sorted(
                (
                    {
                        "id": str(item.id),
                        "code": item.code,
                        "status": item.status,
                        "allows_children": item.allows_children,
                        "allowed_child_types": (
                            item.allowed_child_types
                            if isinstance(item.allowed_child_types, list)
                            else []
                        ),
                        "available_for_new": item.available_for_new,
                        "updated_at": (
                            item.updated_at.isoformat()
                            if item.updated_at is not None
                            else None
                        ),
                    }
                    for item in catalog
                ),
                key=lambda item: item["code"],
            ),
            "nodes": sorted(
                (
                    {
                        "id": str(item.id),
                        "organization_id": str(item.organization_id),
                        "node_type": item.node_type,
                        "parent_node_id": (
                            str(item.parent_node_id)
                            if item.parent_node_id is not None
                            else None
                        ),
                        "status": item.status,
                        "updated_at": (
                            item.updated_at.isoformat()
                            if item.updated_at is not None
                            else None
                        ),
                    }
                    for item in nodes
                ),
                key=lambda item: item["id"],
            ),
            "relationships": sorted(
                (
                    {
                        "id": str(item.id),
                        "organization_id": str(item.organization_id),
                        "source_node_id": str(item.source_node_id),
                        "target_node_id": str(item.target_node_id),
                        "relationship_type": item.relationship_type,
                        "status": item.status,
                        "updated_at": (
                            item.updated_at.isoformat()
                            if item.updated_at is not None
                            else None
                        ),
                    }
                    for item in relationships
                ),
                key=lambda item: item["id"],
            ),
        }
        preview_hash = hashlib.sha256(
            json.dumps(
                fingerprint,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "organization_structure_convergence_schema_version": "1",
            "source_revision": revision,
            "preview_hash": preview_hash,
            "ready": not blockers,
            "nodes": preview_nodes,
            "hierarchy_changes": hierarchy_changes,
            "blockers": blockers,
            "warnings": warnings,
            "impact": {
                "node_identity": "preserved",
                "metadata": "preserved",
                "references": "preserved",
                "document_associations": "preserved",
                "legacy_relationships": (
                    "archived_after_parent_normalization"
                    if payload.normalize_legacy_contains
                    else "unchanged"
                ),
            },
            "capabilities": {
                "preview": ADMIN_PERMISSION in self.actor_permissions,
                "apply": ADMIN_PERMISSION in self.actor_permissions,
            },
            "postgresql_source_of_truth": True,
            "generated_at": datetime.now(UTC),
        }

    @staticmethod
    def _safe_node_reference(
        node: OrganizationNode | None,
    ) -> dict[str, str] | None:
        if node is None:
            return None
        return {
            "name": node.name,
            "code": node.code,
        }

    def _convergence_apply_result(
        self,
        *,
        organization: Organization,
        aggregate: OrganizationStructureAggregate,
        previous_revision: int,
        changes: list[dict[str, Any]],
        applied: bool,
        replayed: bool,
    ) -> dict[str, Any]:
        return {
            "organization_structure_convergence_schema_version": "1",
            "applied": applied,
            "replayed": replayed,
            "previous_revision": previous_revision,
            "revision": aggregate.revision,
            "changes": changes,
            "runtime": self._runtime(
                organization,
                aggregate,
                self.repository.node_types(),
                self.repository.nodes(),
                self.repository.relationships(),
                replayed=replayed,
            ),
            "postgresql_source_of_truth": True,
        }

    def _apply(
        self,
        payload: OrganizationStructureSaveRequest,
        *,
        aggregate: OrganizationStructureAggregate,
        catalog: list[OrganizationNodeType],
        nodes: list[OrganizationNode],
        relationships: list[OrganizationRelationship],
    ) -> list[dict[str, Any]]:
        del aggregate
        if len(payload.nodes) > MAX_NODES:
            raise OrganizationStructureError(422, "organization_structure_node_limit")
        if len(payload.additional_relationships) > MAX_RELATIONSHIPS:
            raise OrganizationStructureError(422, "organization_structure_relationship_limit")
        if payload.additional_relationships:
            raise OrganizationStructureError(
                422,
                "organization_structure_relationship_type_unsupported",
            )

        persisted_by_id = {item.id: item for item in nodes}
        original_status_by_id = {item.id: item.status for item in nodes}
        proposal_refs: set[str] = set()
        proposed_existing_ids: set[uuid.UUID] = set()
        seen_node_ids: set[uuid.UUID] = set()
        for proposal in payload.nodes:
            if proposal.ref in proposal_refs:
                raise OrganizationStructureError(422, "organization_structure_duplicate_reference")
            proposal_refs.add(proposal.ref)
            if proposal.node_id is not None:
                if proposal.node_id in seen_node_ids:
                    raise OrganizationStructureError(
                        422,
                        "organization_structure_duplicate_node_id",
                    )
                seen_node_ids.add(proposal.node_id)
                if proposal.node_id not in persisted_by_id:
                    raise OrganizationStructureError(404, "organization_structure_node_not_found")
                proposed_existing_ids.add(proposal.node_id)
        if proposed_existing_ids != set(persisted_by_id):
            raise OrganizationStructureError(422, "organization_structure_incomplete_aggregate")

        catalog_by_code = {item.code: item for item in catalog}
        desired: dict[uuid.UUID, dict[str, Any]] = {}
        ref_to_id: dict[str, uuid.UUID] = {}
        for proposal in payload.nodes:
            if proposal.intent == "create":
                node_id = uuid.uuid4()
            else:
                node_id = proposal.node_id
            if node_id is None:
                raise OrganizationStructureError(422, "organization_structure_node_identity_invalid")
            ref_to_id[proposal.ref] = node_id
            persisted = persisted_by_id.get(node_id)
            desired[node_id] = self._desired_node(
                proposal,
                persisted=persisted,
                catalog_by_code=catalog_by_code,
                node_id=node_id,
            )

        parent_by_child: dict[uuid.UUID, uuid.UUID | None] = {
            node_id: None for node_id in desired
        }
        seen_children: set[uuid.UUID] = set()
        seen_hierarchy: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for edge in payload.hierarchy:
            parent_id = ref_to_id.get(edge.parent_ref)
            child_id = ref_to_id.get(edge.child_ref)
            if parent_id is None or child_id is None:
                missing_reference = (
                    edge.parent_ref if parent_id is None else edge.child_ref
                )
                try:
                    uuid.UUID(missing_reference)
                except ValueError:
                    pass
                else:
                    raise OrganizationStructureError(
                        404,
                        "organization_structure_node_not_found",
                    )
                raise OrganizationStructureError(422, "organization_structure_node_reference_missing")
            if parent_id == child_id:
                raise OrganizationStructureError(422, "organization_structure_self_reference")
            pair = (parent_id, child_id)
            if pair in seen_hierarchy:
                raise OrganizationStructureError(422, "organization_structure_duplicate_relationship")
            if child_id in seen_children:
                raise OrganizationStructureError(422, "organization_structure_multiple_parents")
            seen_children.add(child_id)
            seen_hierarchy.add(pair)
            parent_by_child[child_id] = parent_id

        legacy = analyze_legacy_contains(nodes, relationships)
        normalized_relationship_ids: set[uuid.UUID] = set()
        if payload.normalize_legacy_contains:
            for child_id, relationship in legacy.normalizable.items():
                if child_id not in desired or relationship.source_node_id not in desired:
                    continue
                proposed_parent = parent_by_child[child_id]
                if proposed_parent not in {None, relationship.source_node_id}:
                    raise OrganizationStructureError(
                        409,
                        "organization_structure_legacy_normalization_conflict",
                    )
                parent_by_child[child_id] = relationship.source_node_id
                normalized_relationship_ids.add(relationship.id)

        cyclic = _cycle_nodes(parent_by_child)
        if cyclic:
            raise OrganizationStructureError(422, "organization_structure_cycle")

        self._validate_archival_descendants(
            desired,
            parent_by_child,
            original_status_by_id=original_status_by_id,
        )
        self._validate_hierarchy(
            desired,
            parent_by_child,
            catalog_by_code=catalog_by_code,
        )

        changes: list[dict[str, Any]] = []
        for node_id, state in desired.items():
            item = persisted_by_id.get(node_id)
            parent_id = parent_by_child[node_id]
            if item is None:
                item = OrganizationNode(
                    id=node_id,
                    organization_id=self.organization_id,
                    parent_node_id=parent_id,
                    node_type=state["node_type"],
                    code=state["code"],
                    name=state["name"],
                    description=state["description"],
                    metadata_json=state["metadata"],
                    position=state["position"],
                    status=state["status"],
                    created_by=self.actor_reference,
                    updated_by=self.actor_reference,
                )
                self.repository.add(item)
                changes.append(self._node_change("created", item, None, state, parent_id))
                self._audit_node("created", item, before=None, after=state, parent_id=parent_id)
                continue

            before = self._node_state(item)
            after = {**state, "parent_node_id": parent_id}
            if before == after:
                continue
            action = self._node_action(before, after)
            item.parent_node_id = parent_id
            item.node_type = state["node_type"]
            item.code = state["code"]
            item.name = state["name"]
            item.description = state["description"]
            item.metadata_json = state["metadata"]
            item.position = state["position"]
            item.status = state["status"]
            item.updated_by = self.actor_reference
            self.repository.add(item)
            changes.append(self._node_change(action, item, before, after, parent_id))
            self._audit_node(action, item, before=before, after=after, parent_id=parent_id)

        newly_archived_node_ids = {
            node_id
            for node_id, state in desired.items()
            if state["status"] == ARCHIVED_STATUS
            and original_status_by_id.get(node_id) == ACTIVE_STATUS
        }
        for relationship in relationships:
            should_archive = (
                relationship.status == ACTIVE_STATUS
                and (
                    relationship.id in normalized_relationship_ids
                    or relationship.source_node_id in newly_archived_node_ids
                    or relationship.target_node_id in newly_archived_node_ids
                )
            )
            if not should_archive:
                continue
            before_status = relationship.status
            relationship.status = ARCHIVED_STATUS
            relationship.updated_by = self.actor_reference
            self.repository.add(relationship)
            action = (
                "legacy_normalized"
                if relationship.id in normalized_relationship_ids
                else "archived"
            )
            change = {
                "resource": "relationship",
                "id": str(relationship.id),
                "action": action,
                "relationship_type": relationship.relationship_type,
            }
            changes.append(change)
            self._audit_relationship(
                action,
                relationship,
                before_status=before_status,
                after_status=relationship.status,
            )

        return changes

    def _desired_node(
        self,
        proposal: OrganizationStructureNodeProposal,
        *,
        persisted: OrganizationNode | None,
        catalog_by_code: dict[str, OrganizationNodeType],
        node_id: uuid.UUID,
    ) -> dict[str, Any]:
        if proposal.intent == "create" and persisted is not None:
            raise OrganizationStructureError(409, "organization_structure_node_conflict")
        if proposal.intent != "create" and persisted is None:
            raise OrganizationStructureError(404, "organization_structure_node_not_found")

        catalog_item = catalog_by_code.get(proposal.node_type)
        type_changed = persisted is not None and persisted.node_type != proposal.node_type
        if proposal.intent == "create" or type_changed:
            if (
                catalog_item is None
                or catalog_item.status != ACTIVE_STATUS
                or not catalog_item.available_for_new
            ):
                raise OrganizationStructureError(422, "organization_structure_node_type_unavailable")
        elif (
            proposal.intent == "restore"
            and catalog_item is not None
            and catalog_item.status == ARCHIVED_STATUS
        ):
            raise OrganizationStructureError(422, "organization_structure_node_type_archived")

        current_status = persisted.status if persisted is not None else None
        if proposal.intent == "archive":
            if current_status == ARCHIVED_STATUS:
                status = ARCHIVED_STATUS
            elif current_status != ACTIVE_STATUS:
                raise OrganizationStructureError(409, "organization_structure_lifecycle_invalid")
            else:
                status = ARCHIVED_STATUS
        elif proposal.intent == "restore":
            if current_status == ACTIVE_STATUS:
                status = ACTIVE_STATUS
            elif current_status != ARCHIVED_STATUS:
                raise OrganizationStructureError(409, "organization_structure_lifecycle_invalid")
            else:
                status = ACTIVE_STATUS
        elif proposal.intent == "create":
            status = ACTIVE_STATUS
        else:
            status = current_status
        if status not in {ACTIVE_STATUS, ARCHIVED_STATUS}:
            raise OrganizationStructureError(409, "organization_structure_legacy_status_unsupported")

        code = proposal.code
        if persisted is not None:
            if code is not None and code != persisted.code:
                raise OrganizationStructureError(
                    422,
                    "organization_structure_node_code_immutable",
                )
            code = persisted.code
        elif code is None:
            code = f"{proposal.node_type}-{node_id.hex[:12]}"
        unchanged_legacy_code = persisted is not None and code == persisted.code
        if not code or (not unchanged_legacy_code and not NODE_CODE_PATTERN.fullmatch(code)):
            raise OrganizationStructureError(422, "organization_structure_node_code_invalid")
        metadata = proposal.metadata
        if persisted is not None:
            safe_existing, existing_metadata_valid = _safe_existing_metadata(
                persisted.metadata_json
            )
            if not existing_metadata_valid and proposal.metadata == safe_existing:
                metadata = persisted.metadata_json
        position: dict[str, Any] = proposal.position
        if persisted is not None:
            safe_position, existing_position_valid = _safe_existing_position(
                persisted.position
            )
            if not existing_position_valid and proposal.position == safe_position:
                position = persisted.position
        return {
            "node_type": proposal.node_type,
            "code": code,
            "name": proposal.name,
            "description": proposal.description,
            "metadata": metadata,
            "position": position,
            "status": status,
        }

    @staticmethod
    def _validate_archival_descendants(
        desired: dict[uuid.UUID, dict[str, Any]],
        parent_by_child: dict[uuid.UUID, uuid.UUID | None],
        *,
        original_status_by_id: dict[uuid.UUID, str],
    ) -> None:
        children_by_parent: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for child_id, parent_id in parent_by_child.items():
            if parent_id is not None:
                children_by_parent[parent_id].append(child_id)

        newly_archived = {
            node_id
            for node_id, state in desired.items()
            if state["status"] == ARCHIVED_STATUS
            and original_status_by_id.get(node_id) == ACTIVE_STATUS
        }
        for archived_id in newly_archived:
            stack = list(children_by_parent.get(archived_id, []))
            while stack:
                descendant = stack.pop()
                if desired[descendant]["status"] == ACTIVE_STATUS:
                    raise OrganizationStructureError(
                        409,
                        "organization_structure_active_descendants",
                    )
                stack.extend(children_by_parent.get(descendant, []))

    def _validate_hierarchy(
        self,
        desired: dict[uuid.UUID, dict[str, Any]],
        parent_by_child: dict[uuid.UUID, uuid.UUID | None],
        *,
        catalog_by_code: dict[str, OrganizationNodeType],
    ) -> None:
        codes: dict[str, uuid.UUID] = {}
        for node_id, state in desired.items():
            existing = codes.get(state["code"])
            if existing is not None and existing != node_id:
                raise OrganizationStructureError(409, "organization_structure_node_code_conflict")
            codes[state["code"]] = node_id

        for child_id, parent_id in parent_by_child.items():
            child = desired[child_id]
            if parent_id is None:
                continue
            parent = desired.get(parent_id)
            if parent is None:
                raise OrganizationStructureError(422, "organization_structure_parent_missing")
            if child["status"] == ACTIVE_STATUS and parent["status"] != ACTIVE_STATUS:
                raise OrganizationStructureError(409, "organization_structure_active_child_archived_parent")
            parent_type = catalog_by_code.get(parent["node_type"])
            if parent_type is not None:
                if not parent_type.allows_children:
                    raise OrganizationStructureError(422, "organization_structure_parent_disallows_children")
                allowed = (
                    parent_type.allowed_child_types
                    if isinstance(parent_type.allowed_child_types, list)
                    else []
                )
                if allowed and child["node_type"] not in allowed:
                    raise OrganizationStructureError(
                        422,
                        "organization_structure_child_type_not_allowed",
                    )

    def _runtime(
        self,
        organization: Organization,
        aggregate: OrganizationStructureAggregate | None,
        node_types: list[OrganizationNodeType],
        nodes: list[OrganizationNode],
        relationships: list[OrganizationRelationship],
        *,
        replayed: bool,
    ) -> dict[str, Any]:
        registered_codes = {item.code for item in node_types}
        catalog = [_catalog_item(item) for item in node_types]
        legacy_codes = sorted({item.node_type for item in nodes} - registered_codes)
        catalog.extend(
            _legacy_catalog_item(code, 10000 + index)
            for index, code in enumerate(legacy_codes)
        )
        legacy = analyze_legacy_contains(nodes, relationships)
        nodes_by_id = {item.id: item for item in nodes}
        node_ids = {item.id for item in nodes}
        primary_parents = {item.id: item.parent_node_id for item in nodes}
        warnings: list[dict[str, Any]] = []
        for item in nodes:
            if item.parent_node_id is not None and item.parent_node_id not in node_ids:
                warnings.append(
                    {
                        "code": "primary_parent_missing_or_out_of_scope",
                        "node_id": item.id,
                    }
                )
            _position, position_valid = _safe_existing_position(item.position)
            if not position_valid:
                warnings.append(
                    {
                        "code": "legacy_node_position_requires_review",
                        "node_id": item.id,
                    }
                )
        for node_id in _cycle_nodes(primary_parents):
            warnings.append(
                {
                    "code": "primary_hierarchy_cycle",
                    "node_id": node_id,
                }
            )
        for item in nodes:
            _metadata, metadata_valid = _safe_existing_metadata(item.metadata_json)
            if not metadata_valid:
                warnings.append(
                    {
                        "code": "legacy_node_metadata_requires_review",
                        "node_id": item.id,
                    }
                )
        hierarchy = [
            {
                "parent_node_id": item.parent_node_id,
                "child_node_id": item.id,
                "source": "parent_node_id",
            }
            for item in nodes
            if item.parent_node_id is not None
        ]
        for child_id, relationship in legacy.normalizable.items():
            child = next(item for item in nodes if item.id == child_id)
            if child.parent_node_id is None:
                hierarchy.append(
                    {
                        "parent_node_id": relationship.source_node_id,
                        "child_node_id": child_id,
                        "source": "legacy_contains",
                        "relationship_id": relationship.id,
                    }
                )
        legacy_payload = []
        for relationship in relationships:
            if relationship.relationship_type != LEGACY_HIERARCHY_TYPE:
                if relationship.status == ACTIVE_STATUS:
                    warnings.append(
                        {
                            "code": "legacy_relationship_type_unsupported",
                            "relationship_id": relationship.id,
                        }
                    )
                legacy_payload.append(self._relationship_read(relationship, False, None))
                continue
            reason = legacy.reasons.get(relationship.id)
            normalizable = relationship in legacy.normalizable.values()
            legacy_payload.append(
                self._relationship_read(relationship, normalizable, reason)
            )
            if reason:
                warnings.append(
                    {
                        "code": reason,
                        "relationship_id": relationship.id,
                    }
                )
        normalization_candidates = []
        for child_id, relationship in sorted(
            legacy.normalizable.items(),
            key=lambda item: str(item[1].id),
        ):
            parent = nodes_by_id.get(relationship.source_node_id)
            child = nodes_by_id.get(child_id)
            if parent is None or child is None:
                continue
            normalization_candidates.append(
                {
                    "candidate_id": relationship.id,
                    "relationship_id": relationship.id,
                    "legacy_relationship_type": relationship.relationship_type,
                    "proposed_parent": {
                        "node_id": parent.id,
                        "code": parent.code,
                        "name": parent.name,
                    },
                    "proposed_child": {
                        "node_id": child.id,
                        "code": child.code,
                        "name": child.name,
                    },
                    "proposed_result": {
                        "authority": "parent_node_id",
                        "parent_node_id": parent.id,
                        "child_node_id": child.id,
                        "legacy_relationship_status_after_save": ARCHIVED_STATUS,
                    },
                    "normalizable_reason": (
                        "legacy_contains_single_in_scope_parent_without_cycle"
                    ),
                }
            )
        return {
            "organization_structure_schema_version": "1",
            "organization": {
                "id": organization.id,
                "name": organization.name,
                "status": organization.status,
            },
            "revision": aggregate.revision if aggregate else 0,
            "root_policy": "multiple",
            "capabilities": {
                "read": READ_PERMISSION in self.actor_permissions,
                "administer": ADMIN_PERMISSION in self.actor_permissions,
                "normalize_legacy": ADMIN_PERMISSION in self.actor_permissions,
            },
            "node_type_catalog": sorted(
                catalog,
                key=lambda item: (int(item["display_order"]), str(item["code"])),
            ),
            "relationship_type_catalog": [],
            "nodes": [self._node_read(item) for item in nodes],
            "hierarchy": hierarchy,
            "additional_relationships": [],
            "legacy_relationships": legacy_payload,
            "legacy_normalization_candidates": normalization_candidates,
            "legacy_warnings": warnings,
            "limits": {
                "max_nodes": MAX_NODES,
                "max_additional_relationships": MAX_RELATIONSHIPS,
            },
            "replayed": replayed,
            "postgresql_source_of_truth": True,
            "external_calls_performed": False,
            "generated_at": datetime.now(UTC),
        }

    @staticmethod
    def _node_read(item: OrganizationNode) -> dict[str, Any]:
        metadata, metadata_valid = _safe_existing_metadata(item.metadata_json)
        position, position_valid = _safe_existing_position(item.position)
        return {
            "id": item.id,
            "parent_node_id": item.parent_node_id,
            "node_type": item.node_type,
            "code": item.code,
            "name": item.name,
            "description": item.description,
            "metadata": metadata,
            "metadata_status": "valid" if metadata_valid else "legacy_requires_review",
            "position": position,
            "position_status": "valid" if position_valid else "legacy_requires_review",
            "status": item.status,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    @staticmethod
    def _relationship_read(
        item: OrganizationRelationship,
        normalizable: bool,
        reason: str | None,
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "source_node_id": item.source_node_id,
            "target_node_id": item.target_node_id,
            "relationship_type": item.relationship_type,
            "status": item.status,
            "normalizable": normalizable,
            "normalization_blocker": reason,
        }

    @staticmethod
    def _node_state(item: OrganizationNode) -> dict[str, Any]:
        return {
            "node_type": item.node_type,
            "code": item.code,
            "name": item.name,
            "description": item.description,
            "metadata": item.metadata_json if isinstance(item.metadata_json, dict) else {},
            "position": item.position if isinstance(item.position, dict) else {},
            "status": item.status,
            "parent_node_id": item.parent_node_id,
        }

    @staticmethod
    def _node_action(before: dict[str, Any], after: dict[str, Any]) -> str:
        if before["status"] != after["status"]:
            return "restored" if after["status"] == ACTIVE_STATUS else "archived"
        if before["parent_node_id"] != after["parent_node_id"]:
            return "parent_changed"
        return "updated"

    @staticmethod
    def _node_change(
        action: str,
        item: OrganizationNode,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        parent_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        return {
            "resource": "node",
            "id": str(item.id),
            "action": action,
            "code": item.code,
            "parent_changed": (
                before is None or before.get("parent_node_id") != parent_id
            ),
            "status": after["status"],
        }

    def _audit_node(
        self,
        action: str,
        item: OrganizationNode,
        *,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        parent_id: uuid.UUID | None,
    ) -> None:
        safe_before = self._safe_audit_node(before)
        safe_after = self._safe_audit_node({**after, "parent_node_id": parent_id})
        self._audit(
            resource_type="organization_structure.node",
            resource_id=str(item.id),
            action=action,
            before=safe_before,
            after=safe_after,
        )

    def _audit_relationship(
        self,
        action: str,
        item: OrganizationRelationship,
        *,
        before_status: str,
        after_status: str,
    ) -> None:
        self._audit(
            resource_type="organization_structure.relationship",
            resource_id=str(item.id),
            action=action,
            before={"status": before_status},
            after={
                "status": after_status,
                "relationship_type": item.relationship_type,
                "source_node_id": str(item.source_node_id),
                "target_node_id": str(item.target_node_id),
            },
        )

    def _audit_aggregate(
        self,
        *,
        previous_revision: int,
        new_revision: int,
        changes: list[dict[str, Any]],
    ) -> None:
        summary = [
            {
                key: value
                for key, value in change.items()
                if key in {"resource", "id", "action", "code", "parent_changed", "status"}
            }
            for change in changes
        ]
        self._audit(
            resource_type="organization_structure.aggregate",
            resource_id=str(self.organization_id),
            action="revision_committed",
            before={"revision": previous_revision},
            after={"revision": new_revision, "changes": summary},
        )

    def _audit_convergence(
        self,
        *,
        previous_revision: int,
        new_revision: int,
        changes: list[dict[str, Any]],
    ) -> None:
        summary = [
            {
                key: value
                for key, value in change.items()
                if key
                in {
                    "resource",
                    "id",
                    "action",
                    "code",
                    "previous_node_type",
                    "node_type",
                    "parent_changed",
                    "relationship_type",
                }
            }
            for change in changes
        ]
        self._audit(
            resource_type="organization_structure.convergence",
            resource_id=str(self.organization_id),
            action="legacy_convergence_applied",
            before={"revision": previous_revision},
            after={
                "revision": new_revision,
                "result": "applied",
                "changes": summary,
            },
        )

    @staticmethod
    def _safe_audit_node(value: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        return {
            key: (str(item) if isinstance(item, uuid.UUID) else item)
            for key, item in value.items()
            if key
            in {
                "node_type",
                "code",
                "name",
                "description",
                "status",
                "parent_node_id",
            }
        }

    def _audit(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        self.repository.add(
            AuditEvent(
                organization_id=self.organization_id,
                actor_type="user",
                actor_id=self.actor_reference,
                resource_type=resource_type,
                resource_id=resource_id,
                summary=action,
                metadata_json={
                    "action": action,
                    "correlation_id": self.correlation_id,
                    "postgresql_source_of_truth": True,
                    "external_calls_performed": False,
                },
            )
        )
        self.repository.add(
            AuditHistory(
                organization_id=self.organization_id,
                entity_type=resource_type,
                entity_id=resource_id,
                action=action,
                before_state=before,
                after_state=after,
                actor_type="user",
                actor_id=self.actor_reference,
            )
        )

    def _require(self, permission: str) -> None:
        if permission not in self.actor_permissions:
            raise OrganizationStructureError(
                403,
                "organization_structure_permission_required",
            )
