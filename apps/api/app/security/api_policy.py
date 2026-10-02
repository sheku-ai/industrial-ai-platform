from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiPermissionRequirement:
    read: frozenset[str]
    administer: frozenset[str]

    def for_method(self, method: str) -> frozenset[str]:
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return self.read
        return self.administer


def _requirement(
    resource: str,
    *,
    read_alternatives: tuple[str, ...] = (),
    administer_alternatives: tuple[str, ...] = (),
) -> ApiPermissionRequirement:
    return ApiPermissionRequirement(
        read=frozenset((f"{resource}:read", *read_alternatives)),
        administer=frozenset((f"{resource}:administer", *administer_alternatives)),
    )


# This maps API capability surfaces to the configurable permission resources
# already persisted in platform-db. It contains no role names or grants.
API_PERMISSION_POLICY: tuple[tuple[str, ApiPermissionRequirement], ...] = (
    (
        "/api/platform/security",
        _requirement(
            "platform.security",
            read_alternatives=("platform.security:administer",),
        ),
    ),
    ("/api/security/organization-access", _requirement("organization.security")),
    ("/api/security/center", _requirement("organization.security")),
    (
        "/api/security",
        _requirement(
            "platform.security",
            read_alternatives=("platform.security:administer",),
        ),
    ),
    (
        "/api/platform/dashboard/capabilities",
        _requirement(
            "organization.dashboard",
            read_alternatives=("ai.configuration:read",),
        ),
    ),
    ("/api/platform/dashboard", _requirement("organization.dashboard")),
    ("/api/platform/capacity", _requirement("platform.capacity")),
    ("/api/platform/portal-acceptance", _requirement("platform.portal_acceptance")),
    ("/api/platform/production-acceptance", _requirement("platform.production_acceptance")),
    ("/api/platform/production-readiness", _requirement("platform.production_acceptance")),
    ("/api/platform/configuration/preflight", _requirement("platform.production_acceptance")),
    ("/api/production-acceptance", _requirement("platform.production_acceptance")),
    ("/api/platform/releases", _requirement("platform.release_governance")),
    ("/api/platform/builds", _requirement("platform.release_governance")),
    ("/api/platform/artifacts", _requirement("platform.release_governance")),
    ("/api/platform/release-operational-evidence", _requirement("platform.release_governance")),
    ("/api/platform/recovery", _requirement("platform.recovery")),
    ("/api/platform/observability", _requirement("platform.observability")),
    ("/api/control-plane/workers", _requirement("control_plane.workers")),
    ("/api/control-plane/scheduler", _requirement("control_plane.scheduler")),
    ("/api/control-plane/reconciliation", _requirement("control_plane.reconciliation")),
    ("/api/control-plane/health", _requirement("control_plane.health")),
    (
        "/api/documents",
        _requirement(
            "documents",
            read_alternatives=("document_configuration:read", "reference_tenant:read"),
            administer_alternatives=("reference_tenant:administer",),
        ),
    ),
    ("/api/document-reviews", _requirement("documents")),
    ("/api/document", _requirement("documents")),
    ("/api/storage", _requirement("documents")),
    ("/api/ingestion", _requirement("documents")),
    ("/api/indexing", _requirement("documents")),
    (
        "/api/knowledge/collections",
        _requirement(
            "knowledge_collections",
            read_alternatives=("reference_tenant:read",),
            administer_alternatives=("reference_tenant:administer",),
        ),
    ),
    ("/api/knowledge", _requirement("documents")),
    ("/api/enterprise-search", _requirement("documents")),
    ("/api/search", _requirement("documents")),
    ("/api/assistants", _requirement("platform.assistants")),
    ("/api/assistant", _requirement("platform.assistants")),
    ("/api/ai/provider-adapters", _requirement("ai.configuration")),
    ("/api/ai/configuration", _requirement("ai.configuration")),
    ("/api/ai/providers", _requirement("ai.configuration", administer_alternatives=("ai.providers:administer",))),
    ("/api/ai/models", _requirement("ai.configuration", administer_alternatives=("ai.models:administer",))),
    ("/api/ai", _requirement("platform.assistants")),
    ("/api/runtime", _requirement("documents")),
    ("/api/feedback-audit", _requirement("platform.operations")),
    ("/api/operations", _requirement("platform.operations")),
    ("/api/platform/operations", _requirement("platform.operations")),
    ("/api/platform/diagnostics", _requirement("platform.operations")),
    ("/api/platform/journey", _requirement("platform.operations")),
    ("/api/platform/release-candidate", _requirement("platform.release_governance")),
    ("/api/platform/governance", _requirement("reference_tenant")),
    ("/api/platform", _requirement("platform.operations")),
    (
        "/api/product-acceptance",
        _requirement(
            "product_acceptance",
            read_alternatives=("platform.production_acceptance:read",),
            administer_alternatives=(
                "product_acceptance:execute",
                "platform.production_acceptance:administer",
            ),
        ),
    ),
    ("/api/core", _requirement("reference_tenant")),
    ("/api/reference-tenant", _requirement("reference_tenant")),
    ("/api/connectors", _requirement("reference_tenant")),
    ("/api/connector", _requirement("reference_tenant")),
    ("/api/workflows", _requirement("reference_tenant")),
    ("/api/workflow", _requirement("reference_tenant")),
    ("/api/models/providers", _requirement("ai.configuration")),
    ("/api/enterprise/api-integration", _requirement("reference_tenant")),
    ("/api/governance", _requirement("reference_tenant")),
    ("/api/reporting", _requirement("organization.reporting")),
    ("/api/scheduler/background-services", _requirement("platform.operations")),
    ("/api/smoke", _requirement("platform.operations")),
)

READ_ONLY_POST_PATHS = frozenset(
    {
        "/api/control-plane/reconciliation/artifacts/preview",
        "/api/documents/registration/prevalidate",
        "/api/documents/registration/plan",
        "/api/enterprise-search/search",
        "/api/knowledge/search",
        "/api/knowledge/search/fts",
        "/api/knowledge/semantic-search",
        "/api/knowledge/hybrid-search",
        "/api/knowledge/context",
        "/api/knowledge/retrieve",
        "/api/knowledge/answer",
    }
)

MEMBERSHIP_DISCOVERY_PATHS = frozenset(
    {
        "/api/core/organizations",
    }
)


def required_permissions(path: str, method: str) -> frozenset[str]:
    normalized_method = method.upper()
    if path == "/api/core/organizations" and normalized_method == "POST":
        return frozenset({"platform.organization_lifecycle:administer"})
    if path.startswith("/api/security/management/global-"):
        if normalized_method in {"GET", "HEAD", "OPTIONS"}:
            return frozenset(
                {
                    "platform.security:read",
                    "platform.security:administer",
                }
            )
        return frozenset({"platform.security:administer"})
    if path.startswith("/api/security/management"):
        action = "read" if normalized_method in {"GET", "HEAD", "OPTIONS"} else "administer"
        return frozenset(
            {
                f"organization.security:{action}",
                f"platform.security:{action}",
            }
        )
    if (
        method.upper() == "POST"
        and path.startswith(("/api/ai/providers/", "/api/ai/models/"))
        and path.endswith("/validate")
    ):
        return frozenset({"ai.validation:execute"})
    effective_method = "GET" if method.upper() == "POST" and path in READ_ONLY_POST_PATHS else method
    for prefix, requirement in API_PERMISSION_POLICY:
        if path == prefix or path.startswith(f"{prefix}/"):
            return requirement.for_method(effective_method)
    return frozenset()


def is_membership_discovery(path: str, method: str) -> bool:
    return method.upper() in {"GET", "HEAD", "OPTIONS"} and path in MEMBERSHIP_DISCOVERY_PATHS
