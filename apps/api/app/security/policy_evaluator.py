from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.models.security import Policy
from app.security.resource_scope import ResourceScope, ResourceScopeType


@dataclass(frozen=True)
class PolicyEvaluationResult:
    granted_permissions: frozenset[str]
    denied_permissions: frozenset[str]
    matched_policy_codes: tuple[str, ...]


class PolicyEvaluator:
    """Evaluates generic persisted security policies for a resource scope."""

    def evaluate(
        self,
        *,
        policies: list[Policy],
        resource_scope: ResourceScope,
        principal_type: str,
        principal_id: str,
        assigned_permissions: frozenset[str],
    ) -> PolicyEvaluationResult:
        granted: set[str] = set()
        denied: set[str] = set()
        matched_codes: list[str] = []

        for policy in policies:
            rules = policy.rules if isinstance(policy.rules, dict) else {}
            if not self._policy_scope_matches(policy, rules, resource_scope):
                continue
            if not self._principal_matches(rules, principal_type=principal_type, principal_id=principal_id):
                continue
            targeted = self._target_permissions(rules)
            if not targeted:
                continue

            effect = str(policy.effect or "allow").strip().lower()
            matched_codes.append(str(policy.code))
            if effect == "deny":
                denied.update(self._expand_denies(targeted, assigned_permissions | frozenset(granted)))
            elif effect == "allow" and self._allow_can_grant(rules):
                granted.update(targeted)

        return PolicyEvaluationResult(
            granted_permissions=frozenset(granted - denied),
            denied_permissions=frozenset(denied),
            matched_policy_codes=tuple(dict.fromkeys(matched_codes)),
        )

    def _policy_scope_matches(self, policy: Policy, rules: dict[str, Any], resource_scope: ResourceScope) -> bool:
        explicit = self._scope_from_rules(rules, policy.organization_id)
        if explicit is not None:
            return resource_scope.is_within(explicit)
        if policy.organization_id is None:
            return resource_scope.scope_type is ResourceScopeType.PLATFORM
        return resource_scope.is_within(ResourceScope.organization(policy.organization_id))

    def _scope_from_rules(self, rules: dict[str, Any], organization_id: Any) -> ResourceScope | None:
        raw_scope = rules.get("scope")
        if not isinstance(raw_scope, dict):
            return None
        scope_type = raw_scope.get("type") or raw_scope.get("scope_type")
        if not scope_type:
            return None
        resolved_org_id = raw_scope.get("organization_id") or organization_id
        resource_id = raw_scope.get("resource_id") or raw_scope.get("scope_id")
        try:
            return ResourceScope.from_values(
                scope_type=str(scope_type),
                organization_id=self._as_uuid(resolved_org_id),
                resource_id=str(resource_id) if resource_id is not None else None,
            )
        except (TypeError, ValueError, AttributeError):
            return None

    def _principal_matches(self, rules: dict[str, Any], *, principal_type: str, principal_id: str) -> bool:
        principals = rules.get("principals")
        if not isinstance(principals, dict):
            return False
        ids = self._as_text_set(principals.get("ids") or principals.get("principal_ids"))
        types = self._as_text_set(principals.get("types") or principals.get("principal_types"))
        if ids and principal_id not in ids:
            return False
        if types and principal_type not in types:
            return False
        return bool(ids or types)

    def _target_permissions(self, rules: dict[str, Any]) -> frozenset[str]:
        explicit = self._as_text_set(rules.get("permissions"))
        if explicit:
            return frozenset(p for p in explicit if ":" in p)
        resources = self._as_text_set(rules.get("resources"))
        actions = self._as_text_set(rules.get("actions"))
        if not resources or not actions:
            return frozenset()
        return frozenset(f"{resource}:{action}" for resource in resources for action in actions)

    def _expand_denies(self, targets: frozenset[str], permissions: frozenset[str]) -> frozenset[str]:
        denied: set[str] = set()
        for target in targets:
            if target.endswith(":*"):
                prefix = target[:-1]
                denied.update(permission for permission in permissions if permission.startswith(prefix))
            elif target in permissions:
                denied.add(target)
        return frozenset(denied)

    def _allow_can_grant(self, rules: dict[str, Any]) -> bool:
        principals = rules.get("principals")
        if not isinstance(principals, dict):
            return False
        principal_ids = principals.get("ids") or principals.get("principal_ids")
        return bool(self._as_text_set(principal_ids))

    def _as_text_set(self, value: Any) -> frozenset[str]:
        if value is None:
            return frozenset()
        if isinstance(value, str):
            return frozenset({value.strip()}) if value.strip() else frozenset()
        if isinstance(value, list | tuple | set):
            return frozenset(str(item).strip() for item in value if str(item).strip())
        return frozenset({str(value).strip()}) if str(value).strip() else frozenset()

    def _as_uuid(self, value: Any) -> UUID | None:
        if value is None or isinstance(value, UUID):
            return value
        return UUID(str(value).strip())
