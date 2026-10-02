from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.product_acceptance.capabilities import discover_capabilities, get_capability
from app.services.product_acceptance.classification import (
    classify_global_status,
    is_release_candidate_eligible,
    release_candidate_blockers,
    validate_gate_contract,
)
from app.services.product_acceptance.contracts import DOCUMENT_CONTENT, SCENARIO, SCENARIO_NAME
from app.services.product_acceptance.error_codes import error_payload
from app.services.product_acceptance.gate_registry import (
    GATE_CONTRACT_VERSION,
    gate_contract_payload,
    get_gate_definition,
    get_phase_gate_definitions,
)
from app.services.product_acceptance.gateway import AcceptanceHttpClient, HttpResult
from app.services.product_acceptance.idempotency import build_idempotency_report, idempotency_gate_results
from app.services.product_acceptance.identity import build_identity, idempotency_key
from app.services.product_acceptance.isolation import evaluate_search_isolation
from app.services.product_acceptance.persistence import AcceptanceEvidenceClient
from app.services.product_acceptance.summaries import build_gate_summary, build_phase_items, build_phase_summary

DOCUMENT_LIFECYCLE_COMPLETION_ATTEMPTS = 4
ACCEPTANCE_SEARCH_QUERY = "inspection"
ACCEPTANCE_PERMISSION_GRANTS = (
    ("product_acceptance", "execute"),
    ("reference_tenant", "read"),
    ("reference_tenant", "administer"),
    ("platform.assistants", "read"),
    ("platform.assistants", "administer"),
)

ACCEPTANCE_ORGANIZATION_ADMIN_GRANTS = (
    ("reference_tenant", "read"),
    ("reference_tenant", "administer"),
    ("organization.dashboard", "read"),
    ("organization.security", "read"),
    ("organization.security", "administer"),
    ("organization.reporting", "read"),
    ("product_acceptance", "read"),
    ("product_acceptance", "execute"),
    ("knowledge_collections", "read"),
    ("document_configuration", "read"),
    ("documents", "read"),
    ("documents", "administer"),
    ("control_plane.health", "read"),
    ("control_plane.reconciliation", "read"),
    ("control_plane.reconciliation", "administer"),
    ("control_plane.scheduler", "read"),
    ("control_plane.scheduler", "administer"),
    ("platform.assistants", "read"),
    ("platform.assistants", "administer"),
    ("ai.configuration", "read"),
)


@dataclass
class RuntimeOptions:
    api_base_url: str
    auth_email: str | None = field(default=None, repr=False)
    auth_password: str | None = field(default=None, repr=False)
    execution_key: str | None = None
    preserve: bool = False
    reuse: bool = False
    cleanup: bool = False
    timeout: float = 20.0


@dataclass
class RuntimeState:
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    phases: list[dict[str, Any]] = field(default_factory=list)
    gates: list[dict[str, Any]] = field(default_factory=list)
    persisted_gates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    capability_matrix: list[dict[str, Any]] = field(default_factory=list)
    public_paths: dict[str, set[str]] = field(default_factory=dict)
    idempotency: dict[str, Any] = field(default_factory=dict)


class LocalProductAcceptanceRuntime:
    def __init__(self, options: RuntimeOptions) -> None:
        self.options = options
        self.identity = build_identity(options.execution_key)
        self.http = AcceptanceHttpClient(options.api_base_url, self.identity.correlation_id, timeout=options.timeout)
        self.evidence = AcceptanceEvidenceClient(self.http, self.identity)
        self.state = RuntimeState()
        self.started_at = datetime.now(UTC).isoformat()

    def run(self) -> dict[str, Any]:
        authentication = self.http.authenticate(
            self.options.auth_email,
            self.options.auth_password,
        )
        if not authentication.ok:
            self.state.blockers.append(
                {
                    **error_payload("ACCEPTANCE_AUTHENTICATION_FAILED"),
                    "details": {
                        "status_code": authentication.status_code,
                        "error": authentication.error,
                    },
                }
            )
            return self._build_report(
                forced_status="BLOCKED_BY_ENVIRONMENT",
                validate_contract=False,
            )

        report: dict[str, Any] | None = None
        try:
            if self.options.cleanup:
                self._run_cleanup_only()
            else:
                self._run_acceptance()
            report = self._build_report()
        except Exception as exc:
            self.state.blockers.append(
                {
                    **error_payload("ACCEPTANCE_GATE_CONTRACT_INVALID"),
                    "details": {"error": str(exc)},
                }
            )
            report = self._build_report(forced_status="FAILED")
        finally:
            if report is None:
                report = self._build_report(forced_status="FAILED")
            if self.evidence.failures:
                report["blockers"].append(
                    {
                        **error_payload("EVIDENCE_PERSISTENCE_FAILED"),
                        "details": {"failures": self.evidence.failures},
                    }
                )
                report["final_status"] = "FAILED"
                report["status"] = "FAILED"
                report["passed"] = False
                report["release_candidate_eligible"] = False
            self.evidence.finalize_execution_best_effort(
                {
                    "status": report["final_status"],
                    "completed_at": report["completed_at"],
                    "organization_id": self._resource_id("organization"),
                    "report": report,
                    "warnings": report["warnings"],
                    "blockers": report["blockers"],
                }
            )
            self.http.logout_best_effort()
        return report

    def _run_acceptance(self) -> None:
        self._bootstrap_organizations()
        self._phase("preflight", self._preflight)
        self._phase("security", self._security)
        self._phase("organization", self._organization)
        self.evidence.create_execution(
            preserve=self.options.preserve,
            reuse=self.options.reuse,
            cleanup=self.options.cleanup,
        )
        self._persist_accumulated_evidence()
        for phase, handler in (
            ("document_configuration", self._document_configuration),
            ("document_registration", self._document_lifecycle),
            ("binary_upload", self._document_lifecycle_assertions),
            ("processing", self._document_lifecycle_assertions),
            ("chunking", self._document_lifecycle_assertions),
            ("knowledge_publication", self._document_lifecycle_assertions),
            ("knowledge_index", self._knowledge_index),
            ("enterprise_search", self._enterprise_search),
            ("assistant", self._assistant),
            ("conversation", self._conversation),
            ("audit", self._audit),
            ("isolation", self._isolation),
            ("idempotency", self._idempotency),
        ):
            self._phase(phase, handler)
        if self.options.cleanup and not self.options.preserve:
            self._phase("cleanup", self._cleanup)
        else:
            self._gate("cleanup", "cleanup_policy", "SKIPPED", {"preserve_requested": self.options.preserve})

    def _persist_accumulated_evidence(self) -> None:
        if not self.evidence.available:
            return
        for gate in self.state.gates:
            if self.evidence.gate(gate):
                self.state.persisted_gates.append(gate)
        for resource_type, resource in self.state.resources.items():
            self.evidence.resource(
                {
                    "resource_type": resource_type,
                    "resource_id": _extract_id(resource),
                    "external_ref": resource.get("external_ref")
                    or f"{resource_type}:{_extract_id(resource) or 'unknown'}",
                    "created_by_execution": bool(resource.get("created_by_execution")),
                    "reused": bool(resource.get("reused")),
                    "cleanup_status": "preserved" if self.options.preserve else "not_requested",
                    "details": resource,
                }
            )

    def _run_cleanup_only(self) -> None:
        self._phase("preflight", self._preflight)
        self._load_persisted_resources()
        self._phase("cleanup", self._cleanup)

    def _preflight(self, phase: str) -> None:
        matrix, paths = discover_capabilities(self.http)
        self.state.capability_matrix = matrix
        self.state.public_paths = paths
        missing = [item for item in matrix if item["required"] and item["status"] == "CAPABILITY_MISSING"]
        if missing:
            self._gate(
                phase,
                "mandatory_public_capabilities",
                "CAPABILITY_MISSING",
                {"missing_capabilities": missing},
                error_code="REQUIRED_ENDPOINT_NOT_AVAILABLE",
                error_message="one or more required public APIs are not exposed",
            )
        else:
            self._gate(phase, "mandatory_public_capabilities", "PASSED", {"capability_count": len(matrix)})
        health = self.http.get("/enterprise-search/health")
        if health.ok and isinstance(health.data, dict) and health.data.get("search_uses_postgresql_fts"):
            self._gate(phase, "postgres_fts_readiness", "PASSED", {"response": health.data})
        else:
            self._gate(
                phase,
                "postgres_fts_readiness",
                "BLOCKED_BY_ENVIRONMENT" if health.status_code == 0 else "FAILED",
                {"status_code": health.status_code, "response": health.data, "error": health.error},
                error_code="POSTGRESQL_FTS_NOT_READY",
            )

    def _bootstrap_organizations(self) -> None:
        self.http.set_platform_scope()
        organization = self._create_or_reuse(
            "organization",
            "/core/organizations",
            lambda item: _config(item).get("external_ref") == self.identity.organization_external_ref,
            {
                "slug": f"local-acceptance-{self.identity.short_id}",
                "name": f"Local Acceptance Organization {self.identity.short_id}",
                "description": "Local product acceptance organization",
                "status": "active",
                "config": {
                    "external_ref": self.identity.organization_external_ref,
                    "scenario": SCENARIO,
                    "execution_key": self.identity.execution_key,
                },
            },
            self.identity.organization_external_ref,
        )
        org_id = _extract_id(organization)
        if not org_id:
            return
        isolation = self._create_or_reuse(
            "isolation_probe_organization",
            "/core/organizations",
            lambda item: (
                _config(item).get("external_ref") == f"{self.identity.organization_external_ref}:isolation-probe"
            ),
            {
                "slug": f"local-acceptance-probe-{self.identity.short_id}",
                "name": f"Local Acceptance Isolation Probe {self.identity.short_id}",
                "description": "Local product acceptance isolation probe organization",
                "status": "active",
                "config": {
                    "external_ref": f"{self.identity.organization_external_ref}:isolation-probe",
                    "scenario": SCENARIO,
                    "execution_key": self.identity.execution_key,
                },
            },
            f"{self.identity.organization_external_ref}:isolation-probe",
        )
        isolation_id = _extract_id(isolation)
        if not isolation_id:
            return
        self._provision_operator_membership(org_id, "primary")
        self._provision_operator_membership(isolation_id, "isolation")
        self.http.set_organization_scope(org_id)

    def _provision_operator_membership(self, organization_id: str, suffix: str) -> None:
        principal_id = self.http.principal_id
        if not principal_id:
            raise RuntimeError("authenticated_principal_id_missing")
        role_code = f"acceptance-administrator-{self.identity.short_id}"
        role = self._create_or_reuse(
            f"bootstrap_role:{suffix}",
            "/security/management/roles",
            lambda item: item.get("organization_id") == organization_id and item.get("code") == role_code,
            {
                "organization_id": organization_id,
                "code": role_code,
                "name": "Acceptance Organization Administrator",
                "description": "Governed administrator role for an isolated acceptance organization",
                "status": "active",
                "config": {
                    "validation_generated": True,
                    "execution_key": self.identity.execution_key,
                },
            },
            f"bootstrap-role:{self.identity.execution_key}:{suffix}",
        )
        role_id = _extract_id(role)
        if not role_id:
            raise RuntimeError(f"acceptance_bootstrap_role_missing:{organization_id}")

        for resource, action in ACCEPTANCE_ORGANIZATION_ADMIN_GRANTS:
            permission = self._create_or_reuse(
                f"bootstrap_permission:{resource}:{action}",
                "/security/management/permissions",
                lambda item, resource=resource, action=action: (
                    item.get("resource") == resource and item.get("action") == action
                ),
                {
                    "resource": resource,
                    "action": action,
                    "description": f"Organization administrator {resource} {action}",
                },
                f"bootstrap-permission:{resource}:{action}",
            )
            permission_id = _extract_id(permission)
            if not permission_id:
                raise RuntimeError(f"acceptance_bootstrap_permission_missing:{resource}:{action}")
            attached = self.http.post(
                f"/security/management/roles/{role_id}/permissions/{permission_id}"
            )
            if not attached.ok and attached.status_code != 409:
                raise RuntimeError(
                    f"acceptance_bootstrap_permission_attach_failed:{resource}:{action}:{attached.status_code}"
                )

        membership = self.http.put(
            f"/security/management/global-users/{principal_id}/memberships/{organization_id}",
            {"role_id": role_id},
        )
        if not membership.ok:
            raise RuntimeError(
                f"acceptance_operator_membership_failed:{organization_id}:{membership.status_code}:{membership.error}"
            )
        self._resource(
            f"operator_membership:{suffix}",
            _extract_id(membership.data or {}, preferred="membership_id"),
            f"operator-membership:{self.identity.execution_key}:{suffix}",
            True,
            False,
            membership.data if isinstance(membership.data, dict) else {},
        )

    def _organization(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        if not org_id:
            self._functional_failure(phase, "organization_missing_id", {})
            return

        runtime = self.http.get("/core/organization-structure/runtime")
        if not runtime.ok or not isinstance(runtime.data, dict):
            self._functional_failure(
                phase,
                "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED",
                {
                    "operation": "organization_structure.read",
                    "organization_id": org_id,
                    "status_code": runtime.status_code,
                    "error": runtime.error,
                    "response": runtime.data,
                },
            )
            return

        current_nodes = [
            item
            for item in runtime.data.get("nodes", [])
            if isinstance(item, dict) and _extract_id(item)
        ]
        proposals = [
            {
                "ref": str(_extract_id(item)),
                "node_id": str(_extract_id(item)),
                "intent": "restore" if item.get("status") == "archived" else "retain",
                "node_type": item.get("node_type"),
                "code": item.get("code"),
                "name": item.get("name"),
                "description": item.get("description"),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                "position": item.get("position") if isinstance(item.get("position"), dict) else {},
            }
            for item in current_nodes
        ]
        nodes_by_code = {
            str(item.get("code")): item
            for item in current_nodes
            if item.get("code")
        }
        catalog = [
            item
            for item in runtime.data.get("node_type_catalog", [])
            if isinstance(item, dict)
            and item.get("status") == "active"
            and item.get("available_for_new") is True
            and item.get("code")
        ]
        catalog.sort(key=lambda item: (int(item.get("display_order") or 0), str(item["code"])))
        type_chain: tuple[str, str, str] | None = None
        for root_type in catalog:
            if not root_type.get("allows_children"):
                continue
            root_allowed = set(root_type.get("allowed_child_types") or [])
            for unit_type in catalog:
                if root_allowed and unit_type["code"] not in root_allowed:
                    continue
                if not unit_type.get("allows_children"):
                    continue
                unit_allowed = set(unit_type.get("allowed_child_types") or [])
                for team_type in catalog:
                    if unit_allowed and team_type["code"] not in unit_allowed:
                        continue
                    type_chain = (
                        str(root_type["code"]),
                        str(unit_type["code"]),
                        str(team_type["code"]),
                    )
                    break
                if type_chain:
                    break
            if type_chain:
                break
        if not type_chain:
            self._functional_failure(
                phase,
                "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED",
                {
                    "operation": "organization_structure.resolve_node_types",
                    "organization_id": org_id,
                    "available_node_types": [str(item["code"]) for item in catalog],
                },
            )
            return
        root_type, unit_type, team_type = type_chain
        desired = (
            (
                f"root-{self.identity.short_id}",
                root_type,
                "Root Node",
                f"{self.identity.organization_external_ref}:root",
                {"x": 0.0, "y": 0.0},
            ),
            (
                f"unit-{self.identity.short_id}",
                unit_type,
                "Functional Unit",
                f"{self.identity.organization_external_ref}:functional-unit",
                {"x": 0.0, "y": 160.0},
            ),
            (
                f"team-{self.identity.short_id}",
                team_type,
                "Organizational Unit",
                f"{self.identity.organization_external_ref}:team",
                {"x": 0.0, "y": 320.0},
            ),
        )
        refs_by_code: dict[str, str] = {}
        for code, node_type, name, external_ref, position in desired:
            existing = nodes_by_code.get(code)
            if existing:
                refs_by_code[code] = str(_extract_id(existing))
                continue
            local_ref = f"local:{code}"
            refs_by_code[code] = local_ref
            proposals.append(
                {
                    "ref": local_ref,
                    "node_id": None,
                    "intent": "create",
                    "node_type": node_type,
                    "code": code,
                    "name": name,
                    "description": None,
                    "metadata": {"external_ref": external_ref},
                    "position": position,
                }
            )

        hierarchy = [
            {
                "parent_ref": str(item.get("parent_node_id")),
                "child_ref": str(item.get("child_node_id")),
            }
            for item in runtime.data.get("hierarchy", [])
            if isinstance(item, dict)
            and item.get("parent_node_id")
            and item.get("child_node_id")
        ]
        desired_edges = (
            (
                refs_by_code[f"root-{self.identity.short_id}"],
                refs_by_code[f"unit-{self.identity.short_id}"],
            ),
            (
                refs_by_code[f"unit-{self.identity.short_id}"],
                refs_by_code[f"team-{self.identity.short_id}"],
            ),
        )
        existing_edges = {
            (item["parent_ref"], item["child_ref"])
            for item in hierarchy
        }
        for parent_ref, child_ref in desired_edges:
            if (parent_ref, child_ref) not in existing_edges:
                hierarchy.append({"parent_ref": parent_ref, "child_ref": child_ref})

        saved = self.http.put(
            "/core/organization-structure/runtime",
            {
                "expected_revision": int(runtime.data.get("revision") or 0),
                "mutation_key": self.identity.execution_id,
                "nodes": proposals,
                "hierarchy": hierarchy,
                "additional_relationships": [],
                "normalize_legacy_contains": True,
            },
        )
        if not saved.ok or not isinstance(saved.data, dict):
            self._functional_failure(
                phase,
                "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED",
                {
                    "operation": "organization_structure.save",
                    "organization_id": org_id,
                    "status_code": saved.status_code,
                    "error": saved.error,
                    "response": saved.data,
                },
            )
            return

        persisted_nodes = {
            str(item.get("code")): item
            for item in saved.data.get("nodes", [])
            if isinstance(item, dict) and item.get("code")
        }
        root = persisted_nodes.get(f"root-{self.identity.short_id}") or {}
        unit = persisted_nodes.get(f"unit-{self.identity.short_id}") or {}
        team = persisted_nodes.get(f"team-{self.identity.short_id}") or {}
        root_id, unit_id, team_id = (_extract_id(root), _extract_id(unit), _extract_id(team))
        persisted_edges = {
            (str(item.get("parent_node_id")), str(item.get("child_node_id")))
            for item in saved.data.get("hierarchy", [])
            if isinstance(item, dict)
        }
        expected_edges = {(str(root_id), str(unit_id)), (str(unit_id), str(team_id))}
        structure_org_id = _extract_id(saved.data.get("organization") or {})
        if (
            structure_org_id != org_id
            or not all((root_id, unit_id, team_id))
            or not expected_edges.issubset(persisted_edges)
        ):
            self._functional_failure(
                phase,
                "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED",
                {
                    "operation": "organization_structure.read_after_write",
                    "organization_id": org_id,
                    "structure_organization_id": structure_org_id,
                    "node_ids": [item for item in (root_id, unit_id, team_id) if item],
                    "expected_edges": sorted(expected_edges),
                    "persisted_edges": sorted(persisted_edges),
                    "revision": saved.data.get("revision"),
                },
            )
            return

        for resource_type, node, external_ref in (
            ("organization_node", root, f"{self.identity.organization_external_ref}:root"),
            ("organization_node_unit", unit, f"{self.identity.organization_external_ref}:functional-unit"),
            ("organization_node_team", team, f"{self.identity.organization_external_ref}:team"),
        ):
            self._resource(resource_type, _extract_id(node), external_ref, True, False, node)
        self._resource(
            "organization_hierarchy_edge",
            f"{root_id}:{unit_id}",
            f"{self.identity.organization_external_ref}:root-unit",
            True,
            False,
            {"parent_node_id": root_id, "child_node_id": unit_id},
        )
        self._resource(
            "organization_hierarchy_edge_team",
            f"{unit_id}:{team_id}",
            f"{self.identity.organization_external_ref}:unit-team",
            True,
            False,
            {"parent_node_id": unit_id, "child_node_id": team_id},
        )
        self._gate(
            phase,
            "organization_hierarchy",
            "PASSED",
            {
                "organization_id": org_id,
                "node_ids": sorted((root_id, unit_id, team_id)),
                "hierarchy_edges": sorted(expected_edges),
                "node_count": 3,
                "relationship_count": 2,
                "revision": saved.data.get("revision"),
                "evidence_origin": "governed_organization_structure_read_after_write",
            },
        )

    def _security(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        if not org_id:
            self._functional_failure(phase, "organization_required", {})
            return
        role = self._create_or_reuse(
            "role",
            "/security/management/roles",
            lambda item: (
                item.get("organization_id") == org_id
                and item.get("code") == f"acceptance-role-{self.identity.short_id}"
            ),
            {
                "organization_id": org_id,
                "code": f"acceptance-role-{self.identity.short_id}",
                "name": "Acceptance Runtime Role",
                "description": "Role used by local product acceptance",
                "status": "active",
                "config": {"external_ref": f"role:{self.identity.execution_key}"},
            },
            f"role:{self.identity.execution_key}",
        )
        permission_ids: list[str] = []
        for resource, action in ACCEPTANCE_PERMISSION_GRANTS:
            permission = self._create_or_reuse(
                f"permission:{resource}:{action}",
                "/security/management/permissions",
                lambda item, resource=resource, action=action: (
                    item.get("resource") == resource and item.get("action") == action
                ),
                {
                    "resource": resource,
                    "action": action,
                    "description": f"Local product acceptance {resource} {action}",
                },
                f"permission:{resource}:{action}",
            )
            permission_id = _extract_id(permission)
            if permission_id:
                permission_ids.append(permission_id)
                if _extract_id(role):
                    self.http.post(f"/security/management/roles/{_extract_id(role)}/permissions/{permission_id}")
        assignment = self._create_or_reuse(
            "role_assignment",
            "/security/management/role-assignments",
            lambda item: (
                item.get("organization_id") == org_id and item.get("principal_id") == self.identity.correlation_id
            ),
            {
                "organization_id": org_id,
                "role_id": _extract_id(role),
                "principal_type": "service",
                "principal_id": self.identity.correlation_id,
                "scope_type": "organization",
                "scope_id": org_id,
                "status": "active",
            },
            f"assignment:{self.identity.execution_key}",
        )
        self._gate(
            phase,
            "security_configurable",
            "PASSED" if _extract_id(assignment) else "FAILED",
            {
                "role_id": _extract_id(role),
                "permission_ids": permission_ids,
                "assignment_id": _extract_id(assignment),
            },
        )

    def _document_configuration(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        doc_type = self._create_or_reuse(
            "document_type",
            "/documents/document-types",
            lambda item: item.get("organization_id") == org_id and item.get("code") == "acceptance-reference",
            {
                "organization_id": org_id,
                "code": "acceptance-reference",
                "name": "Acceptance Reference Document",
                "description": "Reference document type for product acceptance",
                "version": "1.0",
                "status": "active",
                "config": {"external_ref": f"document-type:{self.identity.execution_key}"},
            },
            f"document-type:{self.identity.execution_key}",
        )
        collection = self._create_or_reuse(
            "collection",
            "/knowledge/collections",
            lambda item: (
                item.get("organization_id") == org_id and item.get("code") == f"acceptance-{self.identity.short_id}"
            ),
            {
                "organization_id": org_id,
                "code": f"acceptance-{self.identity.short_id}",
                "name": "Acceptance Knowledge Collection",
                "description": "Knowledge collection for product acceptance",
                "config": {"external_ref": self.identity.collection_external_ref},
                "status": "active",
            },
            self.identity.collection_external_ref,
        )
        self._create_or_reuse(
            "metadata_template",
            "/documents/metadata-templates",
            lambda item: (
                item.get("organization_id") == org_id
                and item.get("code") == f"acceptance-template-{self.identity.short_id}"
            ),
            {
                "organization_id": org_id,
                "document_type_id": _extract_id(doc_type),
                "code": f"acceptance-template-{self.identity.short_id}",
                "name": "Acceptance Metadata Template",
                "schema_definition": {
                    "reference_code": "string",
                    "effective_date": "date",
                    "document_owner": "string",
                    "review_cycle_days": "integer",
                },
                "status": "active",
            },
            f"metadata-template:{self.identity.execution_key}",
        )
        self._create_or_reuse(
            "retention_policy",
            "/documents/retention-policies",
            lambda item: (
                item.get("organization_id") == org_id
                and item.get("code") == f"acceptance-retention-{self.identity.short_id}"
            ),
            {
                "organization_id": org_id,
                "code": f"acceptance-retention-{self.identity.short_id}",
                "name": "Acceptance Retention",
                "rules": {"retention_period_days": 365, "disposition": "review"},
                "status": "active",
            },
            f"retention:{self.identity.execution_key}",
        )
        self._create_or_reuse(
            "classification_rule",
            "/documents/classification-rules",
            lambda item: (
                item.get("organization_id") == org_id
                and item.get("code") == f"acceptance-internal-{self.identity.short_id}"
            ),
            {
                "organization_id": org_id,
                "code": f"acceptance-internal-{self.identity.short_id}",
                "name": "Internal",
                "rules": {"classification": "Internal"},
                "status": "active",
            },
            f"classification:{self.identity.execution_key}",
        )
        self._gate(
            phase,
            "document_configuration_ready",
            "PASSED" if _extract_id(doc_type) and _extract_id(collection) else "FAILED",
            {"document_type_id": _extract_id(doc_type), "collection_id": _extract_id(collection)},
        )

    def _document_lifecycle(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        doc_type_id = self._resource_id("document_type")
        if not org_id or not doc_type_id:
            self._functional_failure(phase, "document_configuration_required", {})
            return
        result = self._post_document_lifecycle_until_complete(self._document_lifecycle_payload(phase))
        if not result.ok:
            fallback_error = (
                "REQUIRED_RUNTIME_NOT_AVAILABLE" if result.status_code == 0 else "RESOURCE_LINEAGE_INCOMPLETE"
            )
            data = result.data if isinstance(result.data, dict) else {}
            self._gate(
                phase,
                "document_lifecycle_orchestrated",
                "BLOCKED_BY_ENVIRONMENT" if result.status_code == 0 else "FAILED",
                {
                    "status_code": result.status_code,
                    "response": result.data,
                    "error": result.error,
                    "functional_error": _functional_error_from_response(result.data, fallback_error),
                    "document_record_id": _nested_get(data, "document_record_id"),
                    "document_version_id": _nested_get(data, "document_version_id"),
                    "storage_verified": _truthy(data, "storage_verified"),
                },
                error_code=_functional_error_from_response(result.data, fallback_error),
            )
            return
        data = result.data or {}
        self.state.resources["document_lifecycle"] = data | {
            "id": _nested_get(data, "processing_job_id") or _nested_get(data, "document_version_id"),
            "external_ref": self.identity.document_external_ref,
            "reused": bool(data.get("storage_reused") or data.get("document_version_reused")),
        }
        for resource_type, key in (
            ("document_record", "document_record_id"),
            ("document_version", "document_version_id"),
            ("artifact", "artifact_id"),
        ):
            resource_id = _nested_get(data, key)
            if resource_id:
                self._resource(resource_type, str(resource_id), self.identity.document_external_ref, False, True, data)
        self._gate(
            phase,
            "document_lifecycle_orchestrated",
            "PASSED" if _truthy(data, "storage_verified") else "FAILED",
            {
                "storage_verified": _truthy(data, "storage_verified"),
                "document_record_id": _nested_get(data, "document_record_id"),
                "document_version_id": _nested_get(data, "document_version_id"),
                "knowledge_indexed": _truthy(data, "knowledge_indexed"),
                "enterprise_search_visible": _truthy(data, "enterprise_search_visible"),
                "chat_ready": _truthy(data, "chat_ready"),
            },
        )

    def _document_lifecycle_payload(self, phase: str) -> dict[str, Any]:
        return {
            "registration": {
                "organization_id": self._resource_id("organization"),
                "title": "Acceptance Reference Document",
                "source_type": "text",
                "document_type_id": self._resource_id("document_type"),
                "collection_id": self._resource_id("collection"),
                "external_reference": self.identity.document_external_ref,
                "description": "Local product acceptance reference document",
                "source_ref": {
                    "provider": "product_acceptance",
                    "reference": self.identity.document_external_ref,
                },
                "metadata": {
                    "reference_code": "ACC-REF-001",
                    "effective_date": "2026-07-10",
                    "document_owner": "Functional Unit",
                    "review_cycle_days": 365,
                },
                "classification": {"classification": "Internal"},
                "requested_by": "local-product-acceptance",
            },
            "version_label": "1.0",
            "file_name": "acceptance-reference.txt",
            "content_type": "text/plain",
            "content_text": DOCUMENT_CONTENT,
            "size_bytes": len(DOCUMENT_CONTENT.encode("utf-8")),
            "storage_provider": {"provider": "filesystem"},
            "chunker_config": {"strategy": "paragraph"},
            "publication_config": {"mode": "controlled"},
            "search_query": ACCEPTANCE_SEARCH_QUERY,
            "search_config": {},
            "top_k": 5,
            "requested_by": "local-product-acceptance",
            "idempotency_key": idempotency_key(
                self.identity.execution_key,
                phase,
                "orchestrate",
                self.identity.document_external_ref,
            ),
            "lifecycle_metadata": {
                "scenario": SCENARIO,
                "execution_key": self.identity.execution_key,
                "external_ref": self.identity.document_external_ref,
            },
        }

    def _post_document_lifecycle_until_complete(self, payload: dict[str, Any]) -> HttpResult:
        latest = self.http.post("/documents/lifecycle/orchestrate", payload)
        for _ in range(1, DOCUMENT_LIFECYCLE_COMPLETION_ATTEMPTS):
            if not latest.ok:
                return latest
            data = latest.data if isinstance(latest.data, dict) else {}
            if _document_lifecycle_complete(data) or _document_lifecycle_blocked(data):
                return latest
            if not _truthy(data, "worker_execution_pending"):
                return latest
            latest = self.http.post("/documents/lifecycle/orchestrate", payload)
        return latest

    def _document_lifecycle_assertions(self, phase: str) -> None:
        data = self.state.resources.get("document_lifecycle") or {}
        if phase == "chunking":
            evidence = _chunking_evidence(data)
            self._gate(
                phase,
                "chunking_ready",
                "PASSED" if evidence["chunking_ready"] else "FAILED",
                evidence,
                error_code=None if evidence["chunking_ready"] else evidence["error_code"],
            )
            return
        flag_by_phase = {
            "binary_upload": "file_uploaded",
            "processing": "processing_ready",
            "knowledge_publication": "knowledge_published",
        }
        flag = flag_by_phase.get(phase)
        passed = bool(_truthy(data, flag)) if flag else bool(data)
        self._gate(
            phase,
            f"{phase}_ready",
            "PASSED" if passed else "FAILED",
            {"flag": flag, "value": _nested_get(data, flag)},
            error_code=None if passed else _lifecycle_phase_error_code(phase, data),
        )

    def _knowledge_index(self, phase: str) -> None:
        data = self.state.resources.get("document_lifecycle") or {}
        passed = _truthy(data, "knowledge_indexed") or int(_nested_get(data, "knowledge_records", default=0) or 0) > 0
        self._gate(phase, "knowledge_index_ready", "PASSED" if passed else "FAILED", {"lifecycle": data})

    def _enterprise_search(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        result = self.http.post(
            "/enterprise-search/search",
            {
                "organization_id": org_id,
                "query": ACCEPTANCE_SEARCH_QUERY,
                "top_k": 5,
                "include_debug": True,
            },
        )
        data = result.data or {}
        results = _nested_get(data, "results", default=[]) or _nested_get(data, "items", default=[]) or []
        passed = result.ok and bool(results)
        self._gate(
            phase,
            "enterprise_search_query",
            "PASSED" if passed else "FAILED",
            {"response": data},
            error_code=None if passed else _functional_error_from_response(data, "RESOURCE_LINEAGE_INCOMPLETE"),
        )

    def _assistant(self, phase: str) -> None:
        assistant = self._create_or_reuse(
            "assistant",
            "/assistants",
            lambda item: item.get("assistant_key") == f"acceptance-{self.identity.short_id}",
            {
                "assistant_name": "Acceptance Assistant",
                "assistant_key": f"acceptance-{self.identity.short_id}",
                "assistant_version": "1.0",
                "assistant_type": "knowledge_assistant",
                "description": "Assistant for local product acceptance",
                "default_search_mode": "enterprise_search",
                "allowed_runtime_domains": ["enterprise_search"],
                "guardrail_profile": {"mode": "deterministic"},
                "requested_by": "local-product-acceptance",
                "requested_query": "What is the inspection interval?",
                "runtime_metadata": {"external_ref": self.identity.assistant_external_ref, "scenario": SCENARIO},
            },
            self.identity.assistant_external_ref,
        )
        self._gate(
            phase, "assistant_configured", "PASSED" if _extract_id(assistant, "assistant_id") else "FAILED", assistant
        )

    def _conversation(self, phase: str) -> None:
        assistant_id = self._resource_id("assistant")
        if not assistant_id:
            self._functional_failure(phase, "assistant_required", {})
            return
        result = self.http.post(
            "/assistants/chat",
            {
                "assistant_id": assistant_id,
                "message": "What is the inspection interval and governing reference code?",
                "requested_by": "local-product-acceptance",
                "runtime_context": {"organization_id": self._resource_id("organization")},
                "runtime_metadata": {
                    "organization_id": self._resource_id("organization"),
                    "scenario": SCENARIO,
                    "execution_key": self.identity.execution_key,
                },
            },
        )
        data = result.data or {}
        conversation_id = _nested_get(data, "conversation_id") or _nested_get(data, "conversation.conversation_id")
        assistant_response_id = _nested_get(data, "assistant_response_id") or _nested_get(
            data, "assistant_response.assistant_response_id"
        )
        if conversation_id:
            self._resource(
                "conversation",
                str(assistant_response_id or conversation_id),
                f"conversation:{self.identity.execution_key}",
                True,
                False,
                {**data, "conversation_id": str(conversation_id), "assistant_response_id": assistant_response_id},
            )
        self._gate(
            phase,
            "conversation_turn_created",
            "PASSED" if result.ok and conversation_id else "FAILED",
            {"response": data, "error": result.error},
            error_code=None
            if result.ok and conversation_id
            else _functional_error_from_response(data, "RESOURCE_LINEAGE_INCOMPLETE"),
        )

    def _audit(self, phase: str) -> None:
        org_id = self._resource_id("organization")
        result = self.http.get("/feedback-audit/audit/events", {"organization_id": org_id, "limit": 20})
        self._record_http_gate(phase, "audit_explorer_accessible", result, required=True)

    def _isolation(self, phase: str) -> None:
        result = evaluate_search_isolation(
            self.http,
            get_capability(self.state.capability_matrix, "enterprise_search"),
            self._resource_id("organization"),
            self._resource_id("isolation_probe_organization"),
            ACCEPTANCE_SEARCH_QUERY,
        )
        self._gate(
            phase,
            "negative_org_isolation",
            result["status"],
            result.get("details", {}),
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
        )

    def _idempotency(self, phase: str) -> None:
        before = self._inventory_counts()
        resources_before = dict(self.state.resources)
        resources_after = self._read_after_write_resources(resources_before)
        after = self._inventory_counts()
        self.state.idempotency = build_idempotency_report(resources_before, resources_after, before, after)
        for gate in idempotency_gate_results(self.state.idempotency):
            self._gate(
                phase,
                gate["gate_code"],
                gate["status"],
                gate.get("details", {}),
                error_code=gate.get("error_code"),
                error_message=gate.get("error_message"),
            )

    def _read_after_write_resources(
        self,
        resources_before: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        resources_after: dict[str, dict[str, Any]] = {}
        for resource_type, path in (
            ("organization", "/core/organizations/{id}"),
            ("collection", "/knowledge/collections/{id}"),
        ):
            before = resources_before.get(resource_type) or {}
            resource_id = _extract_id(before)
            if not resource_id:
                continue
            result = self.http.get(path.format(id=resource_id))
            resources_after[resource_type] = self._verification_resource(before, result, resource_id)

        lifecycle_before = resources_before.get("document_lifecycle") or {}
        if lifecycle_before and self._resource_id("document_type"):
            result = self._post_document_lifecycle_until_complete(
                self._document_lifecycle_payload("document_registration")
            )
            data = result.data if result.ok and isinstance(result.data, dict) else {}
            resources_after["document_lifecycle"] = {
                **data,
                "id": _nested_get(data, "processing_job_id") or _nested_get(data, "document_version_id"),
                "external_ref": lifecycle_before.get("external_ref"),
                "verification_status_code": result.status_code,
                "verification_error": result.error,
            }
            for resource_type, key in (
                ("document_record", "document_record_id"),
                ("document_version", "document_version_id"),
                ("artifact", "artifact_id"),
            ):
                before = resources_before.get(resource_type) or {}
                if before:
                    resources_after[resource_type] = {
                        **data,
                        "id": _nested_get(data, key),
                        "external_ref": before.get("external_ref"),
                        "verification_status_code": result.status_code,
                        "verification_error": result.error,
                    }

        conversation_before = resources_before.get("conversation") or {}
        assistant_response_id = _nested_get(conversation_before, "assistant_response_id")
        conversation_id = _nested_get(conversation_before, "conversation_id")
        verification_id = assistant_response_id or conversation_id or _extract_id(conversation_before)
        if verification_id:
            path = (
                f"/assistants/responses/{assistant_response_id}"
                if assistant_response_id
                else f"/assistants/conversations/{verification_id}"
            )
            result = self.http.get(path)
            resources_after["conversation"] = self._verification_resource(
                conversation_before,
                result,
                str(verification_id),
            )
        return resources_after

    @staticmethod
    def _verification_resource(before: dict[str, Any], result: HttpResult, resource_id: str) -> dict[str, Any]:
        data = result.data if result.ok and isinstance(result.data, dict) else {}
        reported_ids = {
            str(data[key])
            for key in ("id", "organization_id", "collection_id", "conversation_id", "assistant_response_id")
            if data.get(key)
        }
        identity_matches = resource_id in reported_ids
        return {
            **data,
            "id": resource_id if result.ok and identity_matches else None,
            "external_ref": before.get("external_ref"),
            "expected_resource_id": resource_id,
            "reported_resource_ids": sorted(reported_ids),
            "identity_matches": identity_matches,
            "verification_status_code": result.status_code,
            "verification_error": result.error,
        }

    def _cleanup(self, phase: str) -> None:
        cleanup_results: list[dict[str, Any]] = []
        for resource_type in (
            "organization_relationship",
            "organization_node",
            "role_assignment",
            "metadata_template",
            "retention_policy",
            "classification_rule",
            "document_type",
            "collection",
            "organization",
        ):
            resource = self.state.resources.get(resource_type)
            if not resource:
                continue
            result = self._delete_resource(resource_type, _extract_id(resource))
            cleanup_results.append({"resource_type": resource_type, "result": result})
        self._gate(phase, "cleanup_attempted", "PASSED_WITH_WARNINGS", {"cleanup_results": cleanup_results})

    def _load_persisted_resources(self) -> None:
        result = self.http.get(f"/product-acceptance/executions/{self.identity.execution_key}")
        if not result.ok or not isinstance(result.data, dict):
            self.state.warnings.append(
                {
                    "code": "cleanup_execution_not_found",
                    "execution_key": self.identity.execution_key,
                    "details": result.data or result.error,
                }
            )
            return
        for resource in result.data.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            resource_type = resource.get("resource_type")
            if not resource_type:
                continue
            details = resource.get("details") if isinstance(resource.get("details"), dict) else {}
            self.state.resources[resource_type] = details | {"id": resource.get("resource_id")}
        organization_id = self._resource_id("organization")
        if organization_id:
            self.http.set_organization_scope(organization_id)

    def _phase(self, phase: str, handler: Callable[[str], None]) -> None:
        started = datetime.now(UTC).isoformat()
        try:
            handler(phase)
        except Exception as exc:
            self._functional_failure(phase, "unexpected_phase_error", {"error": str(exc)})
        self._ensure_phase_gate_contract(phase)
        completed = datetime.now(UTC).isoformat()
        self.state.phases.append({"phase_code": phase, "started_at": started, "completed_at": completed})

    def _gate(
        self,
        phase: str,
        gate: str,
        status: str,
        details: dict[str, Any],
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        definition = get_gate_definition(phase, gate)
        if definition is None:
            raise ValueError(f"unregistered acceptance gate: {phase}/{gate}")
        payload = {
            "phase_code": phase,
            "gate_code": gate,
            "status": status,
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "details": self._gate_details(phase, gate, details, error_code),
            "error_code": error_code,
            "error_message": error_message,
        }
        self.state.gates.append(payload)
        if self.evidence.gate(payload):
            self.state.persisted_gates.append(payload)
        if status in {"FAILED", "CAPABILITY_MISSING"}:
            self.state.blockers.append({"phase": phase, "gate": gate, "code": error_code or status, "details": details})

    def _gate_details(
        self,
        phase: str,
        gate: str,
        details: dict[str, Any],
        error_code: str | None,
    ) -> dict[str, Any]:
        definition = get_gate_definition(phase, gate)
        error = error_payload(error_code)
        return {
            **details,
            "mandatory": definition.mandatory if definition else False,
            "error_category": error.get("error_category"),
            "retryable": error.get("retryable", False),
            "environment_related": error.get("environment_related", False),
            "capability_related": error.get("capability_related", False),
            "functional_defect": error.get("functional_defect", False),
        }

    def _record_http_gate(self, phase: str, gate: str, result: HttpResult, required: bool) -> None:
        if result.ok:
            self._gate(phase, gate, "PASSED", {"status_code": result.status_code, "response": result.data})
        else:
            if required:
                status = "BLOCKED_BY_ENVIRONMENT" if result.status_code == 0 else "FAILED"
            else:
                status = "PASSED_WITH_WARNINGS"
            self._gate(
                phase,
                gate,
                status,
                {"status_code": result.status_code, "error": result.error, "response": result.data},
                error_code="REQUIRED_RUNTIME_NOT_AVAILABLE" if status == "BLOCKED_BY_ENVIRONMENT" else None,
            )

    def _functional_failure(self, phase: str, code: str, details: dict[str, Any]) -> None:
        error_code = code if error_payload(code) else "ACCEPTANCE_GATE_CONTRACT_INVALID"
        emitted = {gate["gate_code"] for gate in self.state.gates if gate["phase_code"] == phase}
        for definition in get_phase_gate_definitions(phase, mandatory_only=True):
            if definition.gate_code in emitted:
                continue
            self._gate(
                phase,
                definition.gate_code,
                "FAILED",
                {**details, "failure_reason": code},
                error_code=error_code,
                error_message="functional acceptance gate failed",
            )

    def _ensure_phase_gate_contract(self, phase: str) -> None:
        emitted = {gate["gate_code"] for gate in self.state.gates if gate["phase_code"] == phase}
        for definition in get_phase_gate_definitions(phase, mandatory_only=True):
            if definition.gate_code not in emitted:
                self._gate(
                    phase,
                    definition.gate_code,
                    "FAILED",
                    {"failure_reason": "mandatory_gate_not_emitted_by_phase_handler"},
                    error_code="ACCEPTANCE_GATE_CONTRACT_INVALID",
                    error_message="mandatory acceptance gate was not emitted by its phase handler",
                )

    def _create_or_reuse(
        self,
        resource_type: str,
        collection_path: str,
        matcher: Callable[[dict[str, Any]], bool],
        payload: dict[str, Any],
        external_ref: str,
    ) -> dict[str, Any]:
        listed = self.http.get(collection_path)
        if listed.ok:
            for item in _as_list(listed.data):
                if isinstance(item, dict) and matcher(item):
                    self._resource(resource_type, str(_extract_id(item) or ""), external_ref, False, True, item)
                    return item
        created = self.http.post(
            collection_path,
            payload,
            idempotency_key=idempotency_key(self.identity.execution_key, resource_type, "create", external_ref),
        )
        if created.ok and isinstance(created.data, dict):
            self._resource(resource_type, str(_extract_id(created.data) or ""), external_ref, True, False, created.data)
            return created.data
        relisted = self.http.get(collection_path)
        if relisted.ok:
            for item in _as_list(relisted.data):
                if isinstance(item, dict) and matcher(item):
                    self._resource(resource_type, str(_extract_id(item) or ""), external_ref, False, True, item)
                    return item
        self._resource(
            resource_type,
            None,
            external_ref,
            False,
            False,
            {"status_code": created.status_code, "error": created.error, "response": created.data},
        )
        return {}

    def _resource(
        self,
        resource_type: str,
        resource_id: str | None,
        external_ref: str,
        created: bool,
        reused: bool,
        details: dict[str, Any],
    ) -> None:
        payload = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "external_ref": external_ref,
            "created_by_execution": created,
            "reused": reused,
            "cleanup_status": "preserved" if self.options.preserve else "not_requested",
            "details": details,
        }
        self.state.resources[resource_type] = details | {
            "id": resource_id,
            "external_ref": external_ref,
            "created_by_execution": created,
            "reused": reused,
        }
        self.evidence.resource(payload)

    def _delete_resource(self, resource_type: str, resource_id: str | None) -> dict[str, Any]:
        path_by_type = {
            "organization": "/core/organizations/{id}",
            "organization_node": "/core/organization-nodes/{id}",
            "organization_relationship": "/core/organization-relationships/{id}",
            "document_type": "/documents/document-types/{id}",
            "metadata_template": "/documents/metadata-templates/{id}",
            "retention_policy": "/documents/retention-policies/{id}",
            "classification_rule": "/documents/classification-rules/{id}",
            "collection": "/documents/collections/{id}",
        }
        path = path_by_type.get(resource_type)
        if not path or not resource_id:
            warning = {**error_payload("PUBLIC_CLEANUP_API_NOT_AVAILABLE"), "resource_type": resource_type}
            self.state.warnings.append(warning)
            return warning
        result = self.http.delete(path.format(id=resource_id))
        return {"status_code": result.status_code, "ok": result.ok, "error": result.error}

    def _inventory_counts(self) -> dict[str, int]:
        endpoints = {
            "organizations": "/core/organizations",
            "roles": "/security/management/roles",
            "permissions": "/security/management/permissions",
            "role_assignments": "/security/management/role-assignments",
            "collections": "/knowledge/collections",
            "document_types": "/documents/document-types",
            "assistants": "/assistants",
        }
        counts: dict[str, int] = {}
        for key, path in endpoints.items():
            result = self.http.get(path)
            counts[key] = len(_as_list(result.data)) if result.ok else -1
        return counts

    def _resource_id(self, resource_type: str) -> str | None:
        return _extract_id(self.state.resources.get(resource_type) or {})

    def _build_report(
        self,
        forced_status: str | None = None,
        *,
        validate_contract: bool = True,
    ) -> dict[str, Any]:
        contract_errors = (
            validate_gate_contract(
                self.state.gates,
                self.state.phases,
                self.state.persisted_gates if self.evidence.available else None,
            )
            if validate_contract
            else []
        )
        release_blockers = release_candidate_blockers(self.state.gates, contract_errors)
        final_status = forced_status or classify_global_status(self.state.gates, self.state.warnings, contract_errors)
        lifecycle = self.state.resources.get("document_lifecycle") or {}
        completed_at = datetime.now(UTC).isoformat()
        duration_ms = int(
            (datetime.fromisoformat(completed_at) - datetime.fromisoformat(self.started_at)).total_seconds() * 1000
        )
        gate_summary = build_gate_summary(self.state.gates)
        phase_summary = build_phase_summary(self.state.phases, self.state.gates)
        release_candidate_eligible = is_release_candidate_eligible(
            final_status,
            self.state.gates,
            release_blockers,
            self.state.idempotency,
        )
        report = {
            "report_contract_version": GATE_CONTRACT_VERSION,
            "gate_contract": gate_contract_payload(),
            "scenario": SCENARIO,
            "scenario_name": SCENARIO_NAME,
            "execution_id": self.identity.execution_id,
            "execution_key": self.identity.execution_key,
            "correlation_id": self.identity.correlation_id,
            "started_at": self.started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "status": final_status,
            "final_status": final_status,
            "passed": final_status in {"PASSED", "PASSED_WITH_WARNINGS"},
            "release_candidate_eligible": release_candidate_eligible,
            "gate_summary": gate_summary,
            "phase_summary": {key: value for key, value in phase_summary.items() if key != "items"},
            "release_candidate_blockers": release_blockers,
            "capabilities": self.state.capability_matrix,
            "organization": {
                "external_ref": self.identity.organization_external_ref,
                "id": self._resource_id("organization"),
            },
            "document": {
                "external_ref": self.identity.document_external_ref,
                "record_id": self._resource_id("document_record"),
                "version_id": self._resource_id("document_version"),
                "storage_verified": _truthy(lifecycle, "storage_verified"),
            },
            "knowledge": {
                "collection_external_ref": self.identity.collection_external_ref,
                "collection_id": self._resource_id("collection"),
                "knowledge_indexed": _truthy(lifecycle, "knowledge_indexed"),
            },
            "search": {
                "enterprise_search_visible": _truthy(lifecycle, "enterprise_search_visible"),
                "postgresql_fts_required": True,
            },
            "assistant": {
                "external_ref": self.identity.assistant_external_ref,
                "assistant_id": self._resource_id("assistant"),
            },
            "audit": {"audit_phase_present": any(gate["phase_code"] == "audit" for gate in self.state.gates)},
            "isolation": self._isolation_report(),
            "idempotency": self.state.idempotency,
            "execution_contract": {
                "postgresql_source_of_truth": True,
                "object_storage_bytes_only": True,
                "llm_required": False,
                "llm_used": False,
                "embeddings_required": False,
                "embeddings_used": False,
                "qdrant_required": False,
                "qdrant_used": False,
            },
            "phases": build_phase_items(self.state.phases, self.state.gates),
            "gates": self.state.gates,
            "capability_matrix": self.state.capability_matrix,
            "warnings": self.state.warnings,
            "blockers": self.state.blockers + contract_errors,
            "created_resources": self.state.resources,
        }
        return report

    def _isolation_report(self) -> dict[str, Any]:
        gate = next(
            (
                item
                for item in self.state.gates
                if item.get("phase_code") == "isolation" and item.get("gate_code") == "negative_org_isolation"
            ),
            {},
        )
        return {
            "checked": gate.get("status") == "PASSED",
            "status": gate.get("status"),
            "error_code": gate.get("error_code"),
            "details": gate.get("details") or {},
        }


def _extract_id(item: dict[str, Any] | None, preferred: str = "id") -> str | None:
    if not isinstance(item, dict):
        return None
    for key in (
        preferred,
        "id",
        "organization_id",
        "document_record_id",
        "document_version_id",
        "artifact_id",
        "assistant_id",
    ):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _functional_error_from_response(data: Any, default: str) -> str:
    def _walk(value: Any) -> list[str]:
        if isinstance(value, dict):
            codes = [str(value["code"])] if value.get("code") else []
            return codes + [code for nested in value.values() for code in _walk(nested)]
        if isinstance(value, list):
            return [code for nested in value for code in _walk(nested)]
        if isinstance(value, str):
            return [value]
        return []

    codes = set(_walk(data))
    if "CROSS_ORGANIZATION_ACCESS_DETECTED" in codes:
        return "CROSS_ORGANIZATION_ACCESS_DETECTED"
    if "RESOURCE_LINEAGE_INCOMPLETE" in codes or "knowledge_chunks_missing" in codes or "fts_results_empty" in codes:
        return "RESOURCE_LINEAGE_INCOMPLETE"
    if "citation_verification_failed" in codes or "CITATION_VERIFICATION_FAILED" in codes:
        return "CITATION_VERIFICATION_FAILED"
    return default


def _config(item: dict[str, Any]) -> dict[str, Any]:
    config = item.get("config") or item.get("metadata") or item.get("metadata_json") or {}
    return config if isinstance(config, dict) else {}


def _as_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "assistants", "conversations", "executions"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _nested_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in data:
        return data[key]
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _truthy(data: dict[str, Any], key: str | None) -> bool:
    if not key:
        return False
    value = _nested_get(data, key)
    return value is True or value == "true" or value == "ready" or value == "completed"


def _document_lifecycle_complete(data: dict[str, Any]) -> bool:
    return bool(
        _truthy(data, "storage_verified")
        and _truthy(data, "processing_ready")
        and _chunk_result_completed(_chunk_result_from_lifecycle(data))
        and _truthy(data, "knowledge_published")
        and _truthy(data, "knowledge_indexed")
        and _truthy(data, "enterprise_search_visible")
        and _truthy(data, "chat_ready")
    )


def _document_lifecycle_blocked(data: dict[str, Any]) -> bool:
    return str(_nested_get(data, "lifecycle_status") or "").lower() == "blocked" or bool(
        _nested_get(data, "blocking_issues") or []
    )


def _lifecycle_phase_error_code(phase: str, data: dict[str, Any]) -> str | None:
    if phase == "knowledge_publication":
        return "KNOWLEDGE_PUBLICATION_NOT_COMPLETED"
    if phase == "knowledge_index":
        return "KNOWLEDGE_INDEX_NOT_COMPLETED"
    if phase == "chunking":
        return _chunking_evidence(data)["error_code"]
    return None


def _chunk_result_from_lifecycle(data: dict[str, Any]) -> dict[str, Any]:
    candidates = (
        _nested_get(data, "chunk_result"),
        _nested_get(data, "stages.processing_publication_search.chunk_result"),
        _nested_get(data, "stages.processing_publication_search.chunk_generation.chunk_result"),
        _nested_get(data, "stages.processing_publication_search.processing_publication_execution.chunk_result"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _chunk_result_completed(chunk_result: dict[str, Any]) -> bool:
    chunks = chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else []
    return bool(
        chunk_result.get("chunk_status") == "completed"
        and chunk_result.get("chunk_generation_completed") is True
        and _first_int(chunk_result.get("chunk_count")) > 0
        and chunks
    )


def _chunking_evidence(data: dict[str, Any]) -> dict[str, Any]:
    chunk_result = _chunk_result_from_lifecycle(data)
    chunks = chunk_result.get("chunks") if isinstance(chunk_result.get("chunks"), list) else []
    chunk_count = _first_int(chunk_result.get("chunk_count")) if chunk_result else 0
    chunking_ready = _chunk_result_completed(chunk_result)
    knowledge_chunk_ids = [
        str(chunk.get("content_hash") or chunk.get("chunk_index"))
        for chunk in chunks
        if isinstance(chunk, dict) and (chunk.get("content_hash") or chunk.get("chunk_index") is not None)
    ]
    return {
        "chunk_count": chunk_count,
        "knowledge_chunk_ids": knowledge_chunk_ids,
        "chunk_result_present": bool(chunk_result),
        "chunk_status": chunk_result.get("chunk_status") if chunk_result else None,
        "chunk_generation_completed": chunk_result.get("chunk_generation_completed") if chunk_result else None,
        "chunks_present": bool(chunks),
        "evidence_source": "chunk_result",
        "chunking_ready": chunking_ready,
        "error_code": None if chunking_ready else "CHUNK_PERSISTENCE_NOT_COMPLETED",
    }


def _extract_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, tuple):
        return [str(item) for item in value if item]
    return []


def _first_int(*values: Any) -> int:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0
