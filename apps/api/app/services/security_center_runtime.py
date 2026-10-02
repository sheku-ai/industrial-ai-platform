from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.security import Permission, Role, RolePermission
from app.services.governance_center_runtime import build_governance_center_runtime
from app.services.platform_administration_runtime import build_platform_administration_runtime
from app.services.reference_tenant import build_reference_tenant_readiness
from app.services.runtime_composition import compose_runtime_dependency
from app.services.security_acceptance_runtime import build_security_workspace_runtime
from app.services.security_management import (
    build_security_management_readiness,
    list_permissions,
    list_policies,
    list_role_assignments,
    list_roles,
)

SECURITY_CENTER_RUNTIME_SCHEMA_VERSION = "1"
SECURITY_CENTER_RUNTIME_NAME = "security_center_runtime"
RECENT_LIMIT = 20


def _listing(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _role_permissions(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> list[dict[str, Any]]:
    statement = (
        select(RolePermission, Role, Permission)
        .join(Role, Role.id == RolePermission.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .order_by(Role.code.asc(), Permission.resource.asc(), Permission.action.asc())
    )
    if not platform_scope:
        statement = statement.where(Role.organization_id == organization_id)
    rows = db.execute(statement).all()
    return [
        {
            "role_permission_id": role_permission.id,
            "role_id": role.id,
            "role_code": role.code,
            "role_status": role.status,
            "organization_id": role.organization_id,
            "permission_id": permission.id,
            "permission_key": f"{permission.resource}:{permission.action}",
            "resource": permission.resource,
            "action": permission.action,
        }
        for role_permission, role, permission in rows
    ]


def _roles_section(roles: list[dict[str, Any]], role_permissions: list[dict[str, Any]]) -> dict[str, Any]:
    permissions_by_role = Counter(str(item["role_id"]) for item in role_permissions)
    return {
        "count": len(roles),
        "active_count": len([role for role in roles if role.get("status") == "active"]),
        "system_count": len([role for role in roles if role.get("is_system")]),
        "roles": [
            {
                **role,
                "permission_count": permissions_by_role.get(str(role.get("id")), 0),
                "readiness": {
                    "status": "ready"
                    if role.get("status") == "active" and permissions_by_role.get(str(role.get("id")), 0) > 0
                    else "pending",
                },
            }
            for role in roles
        ],
    }


def _permissions_section(permissions: list[dict[str, Any]], role_permissions: list[dict[str, Any]]) -> dict[str, Any]:
    attached = {str(item["permission_id"]) for item in role_permissions}
    by_resource = Counter(str(permission.get("resource") or "unknown") for permission in permissions)
    return {
        "count": len(permissions),
        "attached_count": len(attached),
        "unattached_count": len(
            [permission for permission in permissions if str(permission.get("id")) not in attached]
        ),
        "by_resource": dict(by_resource),
        "permissions": [
            {
                **permission,
                "attached_to_role": str(permission.get("id")) in attached,
            }
            for permission in permissions
        ],
    }


def _policies_section(policies: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(policies),
        "active_count": len([policy for policy in policies if policy.get("status") == "active"]),
        "by_effect": dict(Counter(str(policy.get("effect") or "unknown") for policy in policies)),
        "policies": policies,
    }


def _assignments_section(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(assignments),
        "active_count": len([assignment for assignment in assignments if assignment.get("status") == "active"]),
        "by_principal_type": dict(Counter(str(item.get("principal_type") or "unknown") for item in assignments)),
        "by_scope_type": dict(Counter(str(item.get("scope_type") or "unspecified") for item in assignments)),
        "assignments": assignments,
    }


def _effective_permissions(
    roles: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    role_permissions: list[dict[str, Any]],
) -> dict[str, Any]:
    permissions_by_role: dict[str, set[str]] = defaultdict(set)
    for item in role_permissions:
        permissions_by_role[str(item["role_id"])].add(str(item["permission_key"]))
    active_role_ids = {str(role["id"]) for role in roles if role.get("status") == "active"}
    effective_by_principal: dict[str, set[str]] = defaultdict(set)
    role_count_by_principal: Counter[str] = Counter()
    for assignment in assignments:
        if assignment.get("status") != "active" or str(assignment.get("role_id")) not in active_role_ids:
            continue
        principal_key = f"{assignment.get('principal_type')}:{assignment.get('principal_id')}"
        role_count_by_principal[principal_key] += 1
        effective_by_principal[principal_key].update(permissions_by_role.get(str(assignment.get("role_id")), set()))
    principals = [
        {
            "principal": principal,
            "role_count": role_count_by_principal.get(principal, 0),
            "permission_count": len(permissions),
            "permissions": sorted(permissions),
            "readiness": "ready" if permissions else "pending",
        }
        for principal, permissions in sorted(effective_by_principal.items())
    ]
    return {
        "principal_count": len(principals),
        "principals_with_permissions": len([item for item in principals if item["permission_count"] > 0]),
        "role_permission_count": len(role_permissions),
        "access_management_ready": bool(principals) and any(item["permission_count"] > 0 for item in principals),
        "principals": principals,
    }


def _scopes(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    scope_items = [
        {
            "scope_type": assignment.get("scope_type") or "unspecified",
            "scope_id": assignment.get("scope_id"),
            "organization_id": assignment.get("organization_id"),
            "principal_type": assignment.get("principal_type"),
            "principal_id": assignment.get("principal_id"),
            "assignment_id": assignment.get("id"),
            "status": assignment.get("status"),
        }
        for assignment in assignments
    ]
    return {
        "scope_count": len(scope_items),
        "by_scope_type": dict(Counter(str(item["scope_type"]) for item in scope_items)),
        "organization_scoped_assignments": len([item for item in scope_items if item["organization_id"]]),
        "platform_scoped_assignments": len([item for item in scope_items if not item["organization_id"]]),
        "scopes": scope_items,
    }


def _policy_evaluation(policies: list[dict[str, Any]], effective_permissions: dict[str, Any]) -> dict[str, Any]:
    active_policies = [policy for policy in policies if policy.get("status") == "active"]
    return {
        "policy_engine_available": True,
        "policy_count": len(policies),
        "active_policy_count": len(active_policies),
        "deny_policy_count": len([policy for policy in active_policies if policy.get("effect") == "deny"]),
        "allow_policy_count": len([policy for policy in active_policies if policy.get("effect") == "allow"]),
        "effective_permissions_ready": bool(effective_permissions.get("access_management_ready")),
        "evaluation_mode": "read_only_summary",
        "side_effects_performed": False,
    }


def _security_audit(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    platform_scope: bool,
) -> dict[str, Any]:
    security_resources = {"role", "permission", "policy", "role_assignment", "security", "access"}
    statement = select(AuditEvent).where(AuditEvent.resource_type.in_(security_resources))
    if not platform_scope:
        statement = statement.where(AuditEvent.organization_id == organization_id)
    events = list(
        db.scalars(
            statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(RECENT_LIMIT)
        ).all()
    )
    return {
        "audit_event_count": len(events),
        "audit_by_resource_type": dict(Counter(str(event.resource_type or "unknown") for event in events)),
        "recent_events": [
            {
                "audit_event_id": event.id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "summary": event.summary,
                "actor_id": event.actor_id,
                "created_at": event.created_at,
                "trace_id": (event.metadata_json or {}).get("trace_id"),
                "correlation_id": (event.metadata_json or {}).get("correlation_id"),
            }
            for event in events
        ],
    }


def _access_diagnostics(
    readiness: dict[str, Any],
    roles: dict[str, Any],
    permissions: dict[str, Any],
    assignments: dict[str, Any],
    effective_permissions: dict[str, Any],
) -> dict[str, Any]:
    warnings = list(readiness.get("warnings") or [])
    recommendations: list[dict[str, Any]] = []
    if roles["count"] == 0:
        recommendations.append({"code": "configure_roles"})
    if permissions["count"] == 0:
        recommendations.append({"code": "configure_permissions"})
    if assignments["active_count"] == 0:
        recommendations.append({"code": "assign_roles_to_principals"})
    if not effective_permissions["access_management_ready"]:
        recommendations.append({"code": "review_effective_permissions"})
    return {
        "diagnostics_ready": True,
        "warnings": warnings,
        "blocking_issues": readiness.get("blocking_issues") or [],
        "recommendations": recommendations,
        "unattached_permissions": permissions["unattached_count"],
        "inactive_roles": roles["count"] - roles["active_count"],
        "inactive_assignments": assignments["count"] - assignments["active_count"],
    }


def _reference_tenant_security(readiness: dict[str, Any]) -> dict[str, Any]:
    domain_results = _mapping(readiness.get("domain_results"))
    security_domain = _mapping(domain_results.get("security"))
    return {
        "reference_tenant_ready": bool(readiness.get("reference_tenant_ready")),
        "security_ready": bool(readiness.get("security_ready")),
        "security_domain": security_domain,
        "organization_ready": bool(readiness.get("organization_ready")),
        "audit_ready": bool(readiness.get("audit_ready")),
        "feedback_ready": bool(readiness.get("feedback_ready")),
    }


def _scoped_management_readiness(
    base: dict[str, Any],
    *,
    roles: dict[str, Any],
    permissions: dict[str, Any],
    policies: dict[str, Any],
    assignments: dict[str, Any],
) -> dict[str, Any]:
    roles_count = int(roles["count"])
    permissions_count = int(permissions["count"])
    policies_count = int(policies["count"])
    assignments_count = int(assignments["count"])
    warnings: list[dict[str, Any]] = []
    if roles_count == 0:
        warnings.append({"code": "roles_not_configured", "message": "No organization roles are configured."})
    if permissions_count == 0:
        warnings.append(
            {"code": "permissions_not_configured", "message": "No organization permissions are configured."}
        )
    if assignments_count == 0:
        warnings.append(
            {"code": "assignments_not_configured", "message": "No organization role assignments are configured."}
        )
    return {
        **base,
        "roles_count": roles_count,
        "permissions_count": permissions_count,
        "policies_count": policies_count,
        "assignments_count": assignments_count,
        "active_roles_count": int(roles["active_count"]),
        "active_permissions_count": permissions_count,
        "active_policies_count": int(policies["active_count"]),
        "active_assignments_count": int(assignments["active_count"]),
        "has_roles": roles_count > 0,
        "has_permissions": permissions_count > 0,
        "has_assignments": assignments_count > 0,
        "security_management_ready": roles_count > 0 and permissions_count > 0,
        "warnings": warnings,
        "blocking_issues": [],
    }


def build_security_center_runtime(
    db: Session,
    *,
    organization_id: uuid.UUID | None = None,
    platform_scope: bool = True,
) -> dict[str, Any]:
    readiness = build_security_management_readiness(db) if platform_scope else {}
    security_acceptance, acceptance_dependency = compose_runtime_dependency(
        db,
        runtime=SECURITY_CENTER_RUNTIME_NAME,
        organization_id=organization_id,
        dependency="security_acceptance",
        required=platform_scope,
        builder=lambda: build_security_workspace_runtime(
            db,
            scope="platform" if platform_scope else "organization",
            organization_id=None if platform_scope else organization_id,
            refresh=False,
        ),
        optional_default=None,
    )
    administration = build_platform_administration_runtime(db) if platform_scope else {}
    governance = build_governance_center_runtime(db) if platform_scope else {}
    reference_tenant = build_reference_tenant_readiness(db) if platform_scope else {}
    scope_organization_id = None if platform_scope else organization_id
    all_roles = list_roles(
        db,
        organization_id=scope_organization_id,
        include_global=platform_scope,
        limit=10000,
    )
    all_permissions = list_permissions(db, limit=10000)
    all_policies = list_policies(
        db,
        organization_id=scope_organization_id,
        include_global=platform_scope,
        limit=10000,
    )
    all_assignments = list_role_assignments(
        db,
        organization_id=scope_organization_id,
        include_global=platform_scope,
        limit=10000,
    )
    validation_role_ids = {
        str(role.get("id"))
        for role in all_roles
        if str(_mapping(role.get("config")).get("external_ref") or "").startswith(
            "role:local-product-acceptance-"
        )
        or _mapping(role.get("config")).get("validation_generated") is True
        or _mapping(role.get("config")).get("smoke") is True
    }
    roles_list = [role for role in all_roles if str(role.get("id")) not in validation_role_ids]
    assignments_list = [
        assignment
        for assignment in all_assignments
        if assignment.get("principal_type") not in {"service", "system", "machine"}
        and str(assignment.get("role_id")) not in validation_role_ids
    ]
    policies_list = all_policies
    role_permissions = [
        item
        for item in _role_permissions(
            db,
            organization_id=organization_id,
            platform_scope=platform_scope,
        )
        if str(item.get("role_id")) in {str(role.get("id")) for role in roles_list}
    ]
    attached_permission_ids = {str(item.get("permission_id")) for item in role_permissions}
    if not platform_scope:
        all_permissions = [
            permission
            for permission in all_permissions
            if str(permission.get("id")) in attached_permission_ids
        ]
    technical_permissions = (
        [permission for permission in all_permissions if permission.get("resource") == "product_acceptance"]
        if platform_scope
        else []
    )
    permissions_list = [
        permission for permission in all_permissions if permission.get("resource") != "product_acceptance"
    ]

    roles = _roles_section(roles_list, role_permissions)
    permissions = _permissions_section(permissions_list, role_permissions)
    policies = _policies_section(policies_list)
    assignments = _assignments_section(assignments_list)
    if not platform_scope:
        readiness = _scoped_management_readiness(
            readiness,
            roles=roles,
            permissions=permissions,
            policies=policies,
            assignments=assignments,
        )
    effective_permissions = _effective_permissions(roles_list, assignments_list, role_permissions)
    scopes = _scopes(assignments_list)
    policy_evaluation = _policy_evaluation(policies_list, effective_permissions)
    audit = _security_audit(db, organization_id=organization_id, platform_scope=platform_scope)
    diagnostics = _access_diagnostics(readiness, roles, permissions, assignments, effective_permissions)
    diagnostics["dependencies"] = [acceptance_dependency]
    security_governance = _mapping(governance.get("policy_governance"))
    reference_security = _reference_tenant_security(reference_tenant)
    admin_security = _mapping(administration.get("security"))
    security_ready = (
        bool(readiness.get("security_management_ready"))
        and roles["active_count"] > 0
        and permissions["count"] > 0
        and assignments["active_count"] > 0
        and (
            bool(security_acceptance.readiness.security_ready)
            if platform_scope and security_acceptance is not None
            else True
        )
    )
    runtime_status = "ready" if security_ready and not diagnostics["blocking_issues"] else "degraded"
    pending_capabilities = [
        {
            "code": "external_identity_provider_not_configured",
            "status": "optional_not_configured",
            "reason": "Identity provider integration is optional for this PostgreSQL-backed security center.",
        },
        {
            "code": "jwt_runtime_not_required_for_center",
            "status": "skipped",
            "reason": "JWT execution is not required for read-only security posture inspection.",
        },
    ]
    return {
        "security_center_runtime_schema_version": SECURITY_CENTER_RUNTIME_SCHEMA_VERSION,
        "runtime_name": SECURITY_CENTER_RUNTIME_NAME,
        "runtime_status": runtime_status,
        "workspace_summary": {
            "runtime_status": runtime_status,
            "security_ready": security_ready,
            "identity_ready": bool(readiness.get("authentication_provider_ready")),
            "roles_ready": roles["active_count"] > 0,
            "permissions_ready": permissions["count"] > 0,
            "policies_ready": policies["active_count"] > 0,
            "assignments_ready": assignments["active_count"] > 0,
            "effective_permissions_ready": bool(effective_permissions["access_management_ready"]),
            "audit_traceability_ready": audit["audit_event_count"] >= 0,
            "postgresql_source_of_truth": True,
            "side_effects_performed": False,
            "external_calls_performed": False,
            "llm_used": False,
            "qdrant_used": False,
        },
        "security_readiness": readiness,
        "security_acceptance": (
            security_acceptance.readiness.model_dump(mode="json") if security_acceptance is not None else {}
        ),
        "security_findings": (
            [item.model_dump(mode="json") for item in security_acceptance.findings]
            if security_acceptance is not None
            else []
        ),
        "security_evidence": (
            [item.model_dump(mode="json") for item in security_acceptance.evidence]
            if security_acceptance is not None
            else []
        ),
        "security_policies": (
            [item.model_dump(mode="json") for item in security_acceptance.policies]
            if security_acceptance is not None
            else []
        ),
        "security_configuration": (
            security_acceptance.configuration_summary if security_acceptance is not None else {}
        ),
        "roles": roles,
        "permissions": permissions,
        "policies": policies,
        "role_assignments": assignments,
        "effective_permissions": effective_permissions,
        "scopes": scopes,
        "policy_evaluation": policy_evaluation,
        "access_diagnostics": diagnostics,
        "security_audit": audit,
        "security_governance": {
            **security_governance,
            "administration_security": admin_security,
        },
        "reference_tenant_security": reference_security,
        "advanced_security_records": {
            "validation_roles": (
                [role for role in all_roles if str(role.get("id")) in validation_role_ids]
                if platform_scope
                else []
            ),
            "technical_permissions": technical_permissions,
            "service_assignments": (
                [
                    assignment
                    for assignment in all_assignments
                    if assignment.get("principal_type") in {"service", "system", "machine"}
                    or str(assignment.get("role_id")) in validation_role_ids
                ]
                if platform_scope
                else []
            ),
        },
        "pending_capabilities": pending_capabilities,
        "warnings": [
            *diagnostics["warnings"],
            *(security_acceptance.warnings if security_acceptance is not None else []),
        ],
        "recommendations": [
            *diagnostics["recommendations"],
            *(security_acceptance.next_actions if security_acceptance is not None else []),
        ],
        "postgresql_source_of_truth": True,
        "side_effects_performed": False,
        "external_calls_performed": False,
        "llm_used": False,
        "qdrant_used": False,
    }
