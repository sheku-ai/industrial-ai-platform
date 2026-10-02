from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "app/api/dependencies/runtime_context.py"
RESOURCE_SCOPE = ROOT / "app/security/resource_scope.py"
POLICY_EVALUATOR = ROOT / "app/security/policy_evaluator.py"
AUTHORIZATION = ROOT / "app/services/authorization.py"
WORKERS = ROOT / "app/api/routes/runtime_workers.py"
HEALTH = ROOT / "app/api/routes/operational_health.py"


def has_function(source: str, name: str) -> bool:
    tree = ast.parse(source)
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in ast.walk(tree))


def main() -> int:
    context = CONTEXT.read_text(encoding="utf-8")
    resource_scope = RESOURCE_SCOPE.read_text(encoding="utf-8")
    policy_evaluator = POLICY_EVALUATOR.read_text(encoding="utf-8")
    authorization = AUTHORIZATION.read_text(encoding="utf-8")
    workers = WORKERS.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")

    checks = {
        "scope_header_present": 'alias="X-Authorization-Scope"' in context,
        "organization_header_compatible": 'alias="X-Organization-ID"' in context,
        "organization_scope_default": 'default="organization"' in context,
        "canonical_resource_scope_present": "class ResourceScope" in resource_scope,
        "resource_scope_factory_present": has_function(resource_scope, "from_values"),
        "resource_scope_has_ownership_guard": "platform-scoped resources cannot have organization ownership"
        in resource_scope,
        "workload_requires_resource_id": "workload-scoped resources require a workload resource identifier"
        in resource_scope,
        "workload_nested_under_organization": "ResourceScopeType.WORKLOAD" in resource_scope
        and "self.organization_id != candidate.organization_id" in resource_scope,
        "context_uses_scope_factory": "ResourceScope.from_values(" in context,
        "context_preserves_compatibility": "scope_type: str" in context and "organization_id: UUID | None" in context,
        "authorization_accepts_scope": has_function(authorization, "resolve_permissions_for_scope"),
        "authorization_uses_policy_evaluator": "PolicyEvaluator" in authorization
        and "_candidate_policies" in authorization,
        "authorization_supports_workload_scope": 'RoleAssignment.scope_type.in_(("organization", "workload"))'
        in authorization,
        "policy_evaluator_present": "class PolicyEvaluator" in policy_evaluator,
        "policy_deny_can_reduce_assignment_permissions": "denied_permissions" in policy_evaluator
        and "assigned_permissions" in policy_evaluator,
        "policy_allow_requires_explicit_principal": "_allow_can_grant" in policy_evaluator,
        "policy_scope_uses_canonical_scope": "ResourceScope.from_values(" in policy_evaluator,
        "context_forwards_scope": "resource_scope=resource_scope" in context,
        "workload_scope_not_request_scope": "workload scope is a resource scope" in context,
        "platform_assignment_explicit": 'RoleAssignment.scope_type == "platform"' in authorization,
        "platform_role_global": "Role.organization_id.is_(None)" in authorization,
        "platform_assignment_global": "RoleAssignment.organization_id.is_(None)" in authorization,
        "organization_assignment_explicit": 'RoleAssignment.scope_type == "organization"' in authorization,
        "workers_require_platform_scope": "_require_platform_scope(context)" in workers,
        "workers_declare_platform_scope": "WORKER_RESOURCE_SCOPE = ResourceScope.platform()" in workers,
        "worker_api_exposes_scope": "resource_scope=WORKER_RESOURCE_SCOPE.scope_type.value" in workers,
        "worker_audit_is_global": "AuditEvent.organization_id.is_(None)" in workers,
        "worker_history_is_global": "AuditHistory.organization_id.is_(None)" in workers,
        "worker_command_does_not_claim_tenant": "organization_id=WORKER_RESOURCE_SCOPE.organization_id" in workers,
        "health_requires_organization_scope": 'context.is_scope("organization")' in health,
        "health_does_not_mix_global_workers": "RuntimeWorker" not in health,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
