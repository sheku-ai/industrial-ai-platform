from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

SCENARIO = "local_product_acceptance"
SCENARIO_NAME = "Local Product Acceptance Tenant"


class AcceptanceStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    BLOCKED_BY_ENVIRONMENT = "BLOCKED_BY_ENVIRONMENT"
    FAILED = "FAILED"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    SKIPPED = "SKIPPED"


DOCUMENT_CONTENT = (
    "The inspection interval for the reference equipment is 45 days.\n"
    "The responsible organizational unit must record the inspection result in the controlled register.\n"
    "The escalation threshold is three consecutive incomplete inspections.\n"
    "The governing reference code is ACC-REF-001.\n"
)


REQUIRED_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "capability": "openapi",
        "required": True,
        "phase_code": "preflight",
        "method": "GET",
        "endpoint": "/openapi.json",
    },
    {
        "capability": "organizations",
        "required": True,
        "phase_code": "organization",
        "method": "POST",
        "endpoint": "/core/organizations",
    },
    {
        "capability": "organization_structure_read",
        "required": True,
        "phase_code": "organization",
        "method": "GET",
        "endpoint": "/core/organization-structure/runtime",
    },
    {
        "capability": "organization_structure_write",
        "required": True,
        "phase_code": "organization",
        "method": "PUT",
        "endpoint": "/core/organization-structure/runtime",
    },
    {
        "capability": "security_roles",
        "required": True,
        "phase_code": "security",
        "method": "POST",
        "endpoint": "/security/management/roles",
    },
    {
        "capability": "security_permissions",
        "required": True,
        "phase_code": "security",
        "method": "POST",
        "endpoint": "/security/management/permissions",
    },
    {
        "capability": "security_role_assignments",
        "required": True,
        "phase_code": "security",
        "method": "POST",
        "endpoint": "/security/management/role-assignments",
    },
    {
        "capability": "document_types",
        "required": True,
        "phase_code": "document_configuration",
        "method": "POST",
        "endpoint": "/documents/document-types",
    },
    {
        "capability": "metadata_templates",
        "required": True,
        "phase_code": "document_configuration",
        "method": "POST",
        "endpoint": "/documents/metadata-templates",
    },
    {
        "capability": "retention_policies",
        "required": True,
        "phase_code": "document_configuration",
        "method": "POST",
        "endpoint": "/documents/retention-policies",
    },
    {
        "capability": "classification_rules",
        "required": True,
        "phase_code": "document_configuration",
        "method": "POST",
        "endpoint": "/documents/classification-rules",
    },
    {
        "capability": "knowledge_collections",
        "required": True,
        "phase_code": "document_configuration",
        "method": "POST",
        "endpoint": "/knowledge/collections",
    },
    {
        "capability": "document_lifecycle_orchestrator",
        "required": True,
        "phase_code": "document_registration",
        "method": "POST",
        "endpoint": "/documents/lifecycle/orchestrate",
    },
    {
        "capability": "enterprise_search",
        "required": True,
        "phase_code": "enterprise_search",
        "method": "POST",
        "endpoint": "/enterprise-search/search",
    },
    {
        "capability": "assistant_definition",
        "required": True,
        "phase_code": "assistant",
        "method": "POST",
        "endpoint": "/assistants",
    },
    {
        "capability": "assistant_chat",
        "required": True,
        "phase_code": "conversation",
        "method": "POST",
        "endpoint": "/assistants/chat",
    },
    {
        "capability": "audit_explorer",
        "required": True,
        "phase_code": "audit",
        "method": "GET",
        "endpoint": "/feedback-audit/audit/events",
    },
    {
        "capability": "acceptance_persistence",
        "required": True,
        "phase_code": "preflight",
        "method": "POST",
        "endpoint": "/product-acceptance/executions",
    },
)


@dataclass(frozen=True)
class AcceptanceIdentity:
    execution_id: str
    execution_key: str
    correlation_id: str
    organization_external_ref: str
    document_external_ref: str
    collection_external_ref: str
    assistant_external_ref: str
    short_id: str


@dataclass
class GateResult:
    phase_code: str
    gate_code: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None

    def finish(self, status: str, details: dict[str, Any] | None = None) -> None:
        self.status = status
        if details:
            self.details.update(details)
        self.completed_at = datetime.now(UTC).isoformat()

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase_code": self.phase_code,
            "gate_code": self.gate_code,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "details": self.details,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
