from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent, AuditHistory
from app.models.core import OrganizationNode, OrganizationNodeType
from app.models.documents import (
    DocumentOrganizationAssociation,
    DocumentOrganizationAssociationAggregate,
    DocumentRecord,
)
from app.repositories.document_organization_associations import (
    DocumentOrganizationAssociationRepository,
)
from app.schemas.document_organization_associations import (
    DocumentOrganizationAssociationProposal,
    DocumentOrganizationAssociationSaveRequest,
)

READ_DOCUMENT_PERMISSION = "documents:read"
ADMIN_DOCUMENT_PERMISSION = "documents:administer"
READ_STRUCTURE_PERMISSION = "reference_tenant:read"
ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
MAX_ASSOCIATIONS = 100
NON_ADMINISTRABLE_DOCUMENT_STATUSES = {"archived", "deleted"}


class DocumentOrganizationAssociationError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _payload_hash(payload: DocumentOrganizationAssociationSaveRequest) -> str:
    canonical = {
        "associations": sorted(
            (
                {
                    "organization_node_id": str(item.organization_node_id),
                    "intent": item.intent,
                }
                for item in payload.associations
            ),
            key=lambda item: (item["organization_node_id"], item["intent"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _document_read(document: DocumentRecord) -> dict[str, object]:
    return {
        "id": document.id,
        "title": document.title,
        "status": document.status,
    }


class DocumentOrganizationAssociationService:
    def __init__(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID,
        actor_reference: str,
        actor_permissions: frozenset[str],
        correlation_id: str | None = None,
    ) -> None:
        self.db = db
        self.organization_id = organization_id
        self.actor_reference = actor_reference
        self.actor_permissions = actor_permissions
        self.correlation_id = correlation_id or ""
        self.repository = DocumentOrganizationAssociationRepository(
            db,
            organization_id,
        )

    def runtime(
        self,
        document_id: uuid.UUID,
        *,
        replayed: bool = False,
        authorize: bool = True,
    ) -> dict[str, Any]:
        if authorize:
            self._require_read()
        document = self.repository.document(document_id)
        if document is None:
            raise DocumentOrganizationAssociationError(
                404,
                "document_organization_association_document_not_found",
            )
        aggregate = self.repository.aggregate(document_id)
        associations = self.repository.associations(document_id)
        node_ids = {item.organization_node_id for item in associations}
        associated_nodes = {
            item.id: item for item in self.repository.nodes(node_ids)
        }
        node_types = self.repository.node_types()
        all_nodes = self.repository.nodes()
        return self._runtime(
            document,
            aggregate,
            associations,
            associated_nodes,
            all_nodes,
            node_types,
            replayed=replayed,
        )

    def save(
        self,
        document_id: uuid.UUID,
        payload: DocumentOrganizationAssociationSaveRequest,
    ) -> dict[str, Any]:
        self._require_admin()
        document = self.repository.document(document_id, for_update=True)
        if document is None:
            raise DocumentOrganizationAssociationError(
                404,
                "document_organization_association_document_not_found",
            )
        if str(document.status).lower() in NON_ADMINISTRABLE_DOCUMENT_STATUSES:
            raise DocumentOrganizationAssociationError(
                409,
                "document_organization_association_document_not_administrable",
            )

        aggregate = self._aggregate(document, for_update=True)
        payload_hash = _payload_hash(payload)
        mutation_key = str(payload.mutation_key)
        if aggregate.last_mutation_key == mutation_key:
            if aggregate.last_payload_hash != payload_hash:
                raise DocumentOrganizationAssociationError(
                    409,
                    "document_organization_association_idempotency_conflict",
                )
            return self.runtime(
                document_id,
                replayed=True,
                authorize=False,
            )
        if payload.expected_revision != aggregate.revision:
            raise DocumentOrganizationAssociationError(
                409,
                "document_organization_association_revision_conflict",
            )

        associations = self.repository.associations(document_id, for_update=True)
        changes = self._apply(
            document,
            associations=associations,
            proposals=payload.associations,
        )
        if changes:
            previous_revision = aggregate.revision
            aggregate.revision += 1
            aggregate.last_mutation_key = mutation_key
            aggregate.last_payload_hash = payload_hash
            aggregate.updated_by = self.actor_reference
            self.repository.add(aggregate)
            self._audit_aggregate(
                document=document,
                previous_revision=previous_revision,
                new_revision=aggregate.revision,
                changes=changes,
            )
            self.repository.flush()
        return self.runtime(document_id, authorize=False)

    def apply_initial(
        self,
        document: DocumentRecord,
        *,
        organization_node_ids: list[uuid.UUID],
        mutation_key: str,
        document_created: bool,
    ) -> dict[str, Any]:
        self._require_document_admin()
        if organization_node_ids:
            self._require_admin()
        if document.organization_id != self.organization_id:
            raise DocumentOrganizationAssociationError(
                404,
                "document_organization_association_document_not_found",
            )
        if len(organization_node_ids) != len(set(organization_node_ids)):
            raise DocumentOrganizationAssociationError(
                422,
                "document_organization_association_duplicate_node",
            )
        if len(organization_node_ids) > MAX_ASSOCIATIONS:
            raise DocumentOrganizationAssociationError(
                422,
                "document_organization_association_limit",
            )

        aggregate = self._aggregate(document, for_update=True)
        existing = self.repository.associations(document.id, for_update=True)
        active_ids = {
            item.organization_node_id
            for item in existing
            if item.status == ACTIVE_STATUS
        }
        requested_ids = set(organization_node_ids)
        if not document_created:
            if active_ids != requested_ids:
                raise DocumentOrganizationAssociationError(
                    409,
                    "document_organization_association_initial_idempotency_conflict",
                )
            return self._initial_runtime(
                document,
                aggregate,
                replayed=True,
            )

        if not organization_node_ids:
            return self._initial_runtime(
                document,
                aggregate,
                replayed=False,
            )

        payload = DocumentOrganizationAssociationSaveRequest(
            expected_revision=aggregate.revision,
            mutation_key=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"document-organization-association:{mutation_key}",
            ),
            associations=[
                DocumentOrganizationAssociationProposal(
                    organization_node_id=node_id,
                    intent="add",
                )
                for node_id in organization_node_ids
            ],
        )
        result = self.save(document.id, payload)
        if organization_node_ids:
            self._audit(
                resource_type="document.organization_associations",
                resource_id=str(document.id),
                action="initial_associations_created",
                before={"revision": 0, "node_ids": []},
                after={
                    "revision": result["revision"],
                    "node_ids": sorted(str(item) for item in requested_ids),
                },
            )
            self.repository.flush()
        return result

    def _initial_runtime(
        self,
        document: DocumentRecord,
        aggregate: DocumentOrganizationAssociationAggregate,
        *,
        replayed: bool,
    ) -> dict[str, Any]:
        if READ_STRUCTURE_PERMISSION in self.actor_permissions:
            return self.runtime(
                document.id,
                replayed=replayed,
                authorize=False,
            )
        return {
            "document_organization_association_schema_version": "1",
            "document": _document_read(document),
            "revision": aggregate.revision,
            "active_associations": [],
            "archived_associations": [],
            "structure_options": [],
            "capabilities": {"read": False, "administer": False},
            "limits": {"max_associations_per_document": MAX_ASSOCIATIONS},
            "warnings": [{"code": "organization_structure_permission_required"}],
            "replayed": replayed,
            "postgresql_source_of_truth": True,
            "association_semantics": "organizational_relation_only",
        }

    def enrich_workspace(
        self,
        runtime: dict[str, Any],
    ) -> dict[str, Any]:
        registry = runtime.get("document_registry")
        if not isinstance(registry, list):
            return runtime
        if READ_STRUCTURE_PERMISSION not in self.actor_permissions:
            for item in registry:
                if isinstance(item, dict):
                    item["organization_associations"] = {
                        "visible": False,
                        "active_count": 0,
                        "active": [],
                        "active_node_ids": [],
                        "has_unavailable": False,
                    }
            runtime["organization_associations"] = {
                "capabilities": {"read": False, "administer": False},
                "structure_options": [],
                "warnings": [{"code": "organization_structure_permission_required"}],
                "limits": {"max_associations_per_document": MAX_ASSOCIATIONS},
                "association_semantics": "organizational_relation_only",
            }
            return runtime

        document_ids = [
            uuid.UUID(str(item["document_record_id"]))
            for item in registry
            if isinstance(item, dict) and item.get("document_record_id")
        ]
        associations = self.repository.associations_for_documents(document_ids)
        node_ids = {item.organization_node_id for item in associations}
        nodes_by_id = {
            item.id: item for item in self.repository.nodes(node_ids)
        }
        catalog = self.repository.node_types()
        catalog_by_code = {item.code: item for item in catalog}
        by_document: dict[uuid.UUID, list[DocumentOrganizationAssociation]] = (
            defaultdict(list)
        )
        for association in associations:
            by_document[association.document_id].append(association)
        for item in registry:
            if not isinstance(item, dict) or not item.get("document_record_id"):
                continue
            document_id = uuid.UUID(str(item["document_record_id"]))
            active = []
            active_node_ids: list[str] = []
            has_unavailable = False
            for association in by_document.get(document_id, []):
                if association.status != ACTIVE_STATUS:
                    continue
                node = nodes_by_id.get(association.organization_node_id)
                if node is None:
                    has_unavailable = True
                    continue
                node_type = catalog_by_code.get(node.node_type)
                unavailable = (
                    node.status != ACTIVE_STATUS
                    or node_type is None
                    or node_type.status != ACTIVE_STATUS
                )
                has_unavailable = has_unavailable or unavailable
                active_node_ids.append(str(association.organization_node_id))
                active.append(
                    {
                        "name": node.name,
                        "code": node.code,
                        "node_status": node.status,
                        "association_status": association.status,
                        "legacy": node_type is None,
                        "available": not unavailable,
                    }
                )
            item["organization_associations"] = {
                "visible": True,
                "active_count": len(active),
                "active": active[:3],
                "active_node_ids": active_node_ids,
                "has_more": len(active) > 3,
                "has_unavailable": has_unavailable,
            }
        runtime["organization_associations"] = {
            "capabilities": {
                "read": (
                    READ_DOCUMENT_PERMISSION in self.actor_permissions
                    and READ_STRUCTURE_PERMISSION in self.actor_permissions
                ),
                "administer": (
                    ADMIN_DOCUMENT_PERMISSION in self.actor_permissions
                    and READ_STRUCTURE_PERMISSION in self.actor_permissions
                ),
            },
            "structure_options": self._structure_options(
                self.repository.nodes(),
                catalog,
            ),
            "warnings": [],
            "limits": {"max_associations_per_document": MAX_ASSOCIATIONS},
            "association_semantics": "organizational_relation_only",
        }
        return runtime

    def _aggregate(
        self,
        document: DocumentRecord,
        *,
        for_update: bool,
    ) -> DocumentOrganizationAssociationAggregate:
        aggregate = self.repository.aggregate(
            document.id,
            for_update=for_update,
        )
        if aggregate is not None:
            return aggregate
        aggregate = DocumentOrganizationAssociationAggregate(
            organization_id=self.organization_id,
            document_id=document.id,
            revision=0,
            created_by=self.actor_reference,
            updated_by=self.actor_reference,
        )
        self.repository.add(aggregate)
        self.repository.flush()
        return aggregate

    def _apply(
        self,
        document: DocumentRecord,
        *,
        associations: list[DocumentOrganizationAssociation],
        proposals: list[DocumentOrganizationAssociationProposal],
    ) -> list[dict[str, Any]]:
        if len(proposals) > MAX_ASSOCIATIONS:
            raise DocumentOrganizationAssociationError(
                422,
                "document_organization_association_limit",
            )
        existing_by_node = {
            item.organization_node_id: item for item in associations
        }
        proposal_by_node = {
            item.organization_node_id: item for item in proposals
        }
        requested_node_ids = set(proposal_by_node)
        nodes_by_id = {
            item.id: item for item in self.repository.nodes(requested_node_ids)
        }
        if set(nodes_by_id) != requested_node_ids:
            raise DocumentOrganizationAssociationError(
                404,
                "document_organization_association_node_not_found",
            )
        catalog_by_code = {
            item.code: item for item in self.repository.node_types()
        }

        desired_active = {
            node_id
            for node_id, proposal in proposal_by_node.items()
            if proposal.intent != "archive"
        }
        for node_id in desired_active:
            proposal = proposal_by_node[node_id]
            existing = existing_by_node.get(node_id)
            if proposal.intent == "retain" and (
                existing is None or existing.status != ACTIVE_STATUS
            ):
                raise DocumentOrganizationAssociationError(
                    422,
                    "document_organization_association_retain_invalid",
                )
            if proposal.intent == "restore" and (
                existing is None or existing.status != ARCHIVED_STATUS
            ):
                raise DocumentOrganizationAssociationError(
                    422,
                    "document_organization_association_restore_invalid",
                )
            if (
                existing is None
                or existing.status == ARCHIVED_STATUS
                or proposal.intent in {"add", "restore"}
            ):
                self._validate_selectable_node(
                    nodes_by_id[node_id],
                    catalog_by_code,
                )

        changes: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for node_id in sorted(desired_active, key=str):
            existing = existing_by_node.get(node_id)
            if existing is None:
                association = DocumentOrganizationAssociation(
                    organization_id=self.organization_id,
                    document_id=document.id,
                    organization_node_id=node_id,
                    status=ACTIVE_STATUS,
                    created_by=self.actor_reference,
                    updated_by=self.actor_reference,
                )
                self.repository.add(association)
                self.repository.flush()
                self._audit_association(
                    association,
                    action="added",
                    before={},
                    after={"status": ACTIVE_STATUS},
                )
                changes.append(
                    {
                        "association_id": str(association.id),
                        "organization_node_id": str(node_id),
                        "action": "added",
                    }
                )
            elif existing.status == ARCHIVED_STATUS:
                existing.status = ACTIVE_STATUS
                existing.restored_at = now
                existing.restored_by = self.actor_reference
                existing.updated_by = self.actor_reference
                self.repository.add(existing)
                self._audit_association(
                    existing,
                    action="restored",
                    before={"status": ARCHIVED_STATUS},
                    after={"status": ACTIVE_STATUS},
                )
                changes.append(
                    {
                        "association_id": str(existing.id),
                        "organization_node_id": str(node_id),
                        "action": "restored",
                    }
                )

        for node_id, existing in existing_by_node.items():
            proposal = proposal_by_node.get(node_id)
            should_archive = (
                existing.status == ACTIVE_STATUS
                and (
                    node_id not in desired_active
                    or (proposal is not None and proposal.intent == "archive")
                )
            )
            if not should_archive:
                continue
            existing.status = ARCHIVED_STATUS
            existing.archived_at = now
            existing.archived_by = self.actor_reference
            existing.updated_by = self.actor_reference
            self.repository.add(existing)
            self._audit_association(
                existing,
                action="archived",
                before={"status": ACTIVE_STATUS},
                after={"status": ARCHIVED_STATUS},
            )
            changes.append(
                {
                    "association_id": str(existing.id),
                    "organization_node_id": str(node_id),
                    "action": "archived",
                }
            )
        return changes

    @staticmethod
    def _validate_selectable_node(
        node: OrganizationNode,
        catalog_by_code: dict[str, OrganizationNodeType],
    ) -> None:
        node_type = catalog_by_code.get(node.node_type)
        if node.status != ACTIVE_STATUS:
            raise DocumentOrganizationAssociationError(
                409,
                "document_organization_association_node_archived",
            )
        if (
            node_type is None
            or node_type.status != ACTIVE_STATUS
            or not node_type.available_for_new
        ):
            raise DocumentOrganizationAssociationError(
                409,
                "document_organization_association_node_type_unavailable",
            )

    def _runtime(
        self,
        document: DocumentRecord,
        aggregate: DocumentOrganizationAssociationAggregate | None,
        associations: list[DocumentOrganizationAssociation],
        associated_nodes: dict[uuid.UUID, OrganizationNode],
        all_nodes: list[OrganizationNode],
        node_types: list[OrganizationNodeType],
        *,
        replayed: bool,
    ) -> dict[str, Any]:
        catalog_by_code = {item.code: item for item in node_types}
        active: list[dict[str, object]] = []
        archived: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        for association in associations:
            node = associated_nodes.get(association.organization_node_id)
            item = self._association_read(
                association,
                node,
                catalog_by_code,
            )
            if association.status == ACTIVE_STATUS:
                active.append(item)
            else:
                archived.append(item)
            if node is None:
                warnings.append(
                    {
                        "code": "associated_organization_node_unavailable",
                        "association_id": association.id,
                    }
                )
            elif node.status == ARCHIVED_STATUS:
                warnings.append(
                    {
                        "code": "associated_organization_node_archived",
                        "association_id": association.id,
                    }
                )
            elif node.node_type not in catalog_by_code:
                warnings.append(
                    {
                        "code": "associated_organization_node_legacy",
                        "association_id": association.id,
                    }
                )
        return {
            "document_organization_association_schema_version": "1",
            "document": _document_read(document),
            "revision": aggregate.revision if aggregate else 0,
            "active_associations": active,
            "archived_associations": archived,
            "structure_options": self._structure_options(
                all_nodes,
                node_types,
            ),
            "capabilities": {
                "read": (
                    READ_DOCUMENT_PERMISSION in self.actor_permissions
                    and READ_STRUCTURE_PERMISSION in self.actor_permissions
                ),
                "administer": (
                    ADMIN_DOCUMENT_PERMISSION in self.actor_permissions
                    and READ_STRUCTURE_PERMISSION in self.actor_permissions
                    and str(document.status).lower()
                    not in NON_ADMINISTRABLE_DOCUMENT_STATUSES
                ),
            },
            "limits": {"max_associations_per_document": MAX_ASSOCIATIONS},
            "warnings": warnings,
            "replayed": replayed,
            "postgresql_source_of_truth": True,
            "association_semantics": "organizational_relation_only",
        }

    @staticmethod
    def _association_read(
        association: DocumentOrganizationAssociation,
        node: OrganizationNode | None,
        catalog_by_code: dict[str, OrganizationNodeType],
    ) -> dict[str, object]:
        node_type = catalog_by_code.get(node.node_type) if node else None
        return {
            "id": association.id,
            "organization_node_id": association.organization_node_id,
            "association_status": association.status,
            "node": {
                "name": node.name if node else "Unavailable organization node",
                "code": node.code if node else None,
                "node_type": node.node_type if node else None,
                "node_status": node.status if node else "unavailable",
                "legacy": node is not None and node_type is None,
                "available": (
                    node is not None
                    and node.status == ACTIVE_STATUS
                    and node_type is not None
                    and node_type.status == ACTIVE_STATUS
                    and node_type.available_for_new
                ),
            },
            "created_at": association.created_at,
            "updated_at": association.updated_at,
            "archived_at": association.archived_at,
            "restored_at": association.restored_at,
        }

    @staticmethod
    def _structure_options(
        nodes: list[OrganizationNode],
        node_types: list[OrganizationNodeType],
    ) -> list[dict[str, object]]:
        catalog_by_code = {item.code: item for item in node_types}
        return [
            {
                "id": node.id,
                "parent_node_id": node.parent_node_id,
                "name": node.name,
                "code": node.code,
                "node_type": node.node_type,
                "node_status": node.status,
                "legacy": node.node_type not in catalog_by_code,
                "selectable": bool(
                    node.status == ACTIVE_STATUS
                    and node.node_type in catalog_by_code
                    and catalog_by_code[node.node_type].status == ACTIVE_STATUS
                    and catalog_by_code[node.node_type].available_for_new
                ),
            }
            for node in nodes
        ]

    def _audit_association(
        self,
        association: DocumentOrganizationAssociation,
        *,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        self._audit(
            resource_type="document.organization_association",
            resource_id=str(association.id),
            action=action,
            before=before,
            after={
                **after,
                "document_id": str(association.document_id),
                "organization_node_id": str(association.organization_node_id),
            },
        )

    def _audit_aggregate(
        self,
        *,
        document: DocumentRecord,
        previous_revision: int,
        new_revision: int,
        changes: list[dict[str, Any]],
    ) -> None:
        self._audit(
            resource_type="document.organization_associations",
            resource_id=str(document.id),
            action="revision_committed",
            before={"revision": previous_revision},
            after={
                "revision": new_revision,
                "changes": changes,
            },
        )

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

    def _require_read(self) -> None:
        if (
            READ_DOCUMENT_PERMISSION not in self.actor_permissions
            or READ_STRUCTURE_PERMISSION not in self.actor_permissions
        ):
            raise DocumentOrganizationAssociationError(
                403,
                "document_organization_association_read_permission_required",
            )

    def _require_admin(self) -> None:
        self._require_document_admin()
        if READ_STRUCTURE_PERMISSION not in self.actor_permissions:
            raise DocumentOrganizationAssociationError(
                403,
                "document_organization_association_admin_permission_required",
            )

    def _require_document_admin(self) -> None:
        if (
            ADMIN_DOCUMENT_PERMISSION not in self.actor_permissions
        ):
            raise DocumentOrganizationAssociationError(
                403,
                "document_organization_association_admin_permission_required",
            )
