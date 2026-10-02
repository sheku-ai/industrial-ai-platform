from __future__ import annotations

from dataclasses import dataclass

GATE_CONTRACT_VERSION = "local-product-acceptance/v2"

TERMINAL_STATUSES = {
    "PASSED",
    "PASSED_WITH_WARNINGS",
    "FAILED",
    "CAPABILITY_MISSING",
    "BLOCKED_BY_ENVIRONMENT",
    "SKIPPED",
}


@dataclass(frozen=True)
class GateDefinition:
    phase_code: str
    gate_code: str
    mandatory: bool
    allowed_statuses: frozenset[str]
    failure_behavior: str
    description: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.phase_code, self.gate_code)


GATE_DEFINITIONS: tuple[GateDefinition, ...] = (
    GateDefinition(
        "preflight",
        "mandatory_public_capabilities",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Public mandatory capability contract is available.",
    ),
    GateDefinition(
        "preflight",
        "postgres_fts_readiness",
        True,
        frozenset({"PASSED", "FAILED", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "PostgreSQL FTS readiness is available.",
    ),
    GateDefinition(
        "organization",
        "organization_hierarchy",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Organization and generic hierarchy are configured.",
    ),
    GateDefinition(
        "security",
        "security_configurable",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Security resources are configurable by public APIs.",
    ),
    GateDefinition(
        "document_configuration",
        "document_configuration_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Document configuration is ready.",
    ),
    GateDefinition(
        "document_registration",
        "document_lifecycle_orchestrated",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Document lifecycle is orchestrated end to end.",
    ),
    GateDefinition(
        "binary_upload",
        "binary_upload_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Binary upload and storage verification completed.",
    ),
    GateDefinition(
        "processing",
        "processing_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Processing readiness completed.",
    ),
    GateDefinition(
        "chunking",
        "chunking_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Chunking completed.",
    ),
    GateDefinition(
        "knowledge_publication",
        "knowledge_publication_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Knowledge publication completed.",
    ),
    GateDefinition(
        "knowledge_index",
        "knowledge_index_ready",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Knowledge index is available.",
    ),
    GateDefinition(
        "enterprise_search",
        "enterprise_search_query",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Enterprise Search returns expected evidence.",
    ),
    GateDefinition(
        "assistant",
        "assistant_configured",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Assistant can be configured through public APIs.",
    ),
    GateDefinition(
        "conversation",
        "conversation_turn_created",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Conversation and assistant response path are available.",
    ),
    GateDefinition(
        "audit",
        "audit_explorer_accessible",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Audit evidence can be inspected.",
    ),
    GateDefinition(
        "isolation",
        "negative_org_isolation",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Cross-organization search isolation is verified.",
    ),
    GateDefinition(
        "idempotency",
        "organization_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Organization identity is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "document_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Document identity is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "document_version_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Document version identity is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "storage_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Storage artifact identity is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "processing_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Processing evidence is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "knowledge_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Knowledge evidence is idempotent.",
    ),
    GateDefinition(
        "idempotency",
        "assistant_response_idempotent",
        True,
        frozenset({"PASSED", "FAILED", "CAPABILITY_MISSING", "BLOCKED_BY_ENVIRONMENT"}),
        "block_release_candidate",
        "Assistant/conversation evidence is idempotent.",
    ),
    GateDefinition(
        "cleanup",
        "cleanup_policy",
        False,
        frozenset({"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "CAPABILITY_MISSING", "SKIPPED"}),
        "warn_only",
        "Cleanup is skipped when preserve mode is active.",
    ),
    GateDefinition(
        "cleanup",
        "cleanup_attempted",
        False,
        frozenset({"PASSED", "PASSED_WITH_WARNINGS", "FAILED", "CAPABILITY_MISSING", "SKIPPED"}),
        "warn_only",
        "Cleanup was attempted through public APIs.",
    ),
)


GATE_REGISTRY: dict[tuple[str, str], GateDefinition] = {definition.key: definition for definition in GATE_DEFINITIONS}
PHASE_GATE_DEFINITIONS: dict[str, tuple[GateDefinition, ...]] = {
    phase_code: tuple(definition for definition in GATE_DEFINITIONS if definition.phase_code == phase_code)
    for phase_code in dict.fromkeys(definition.phase_code for definition in GATE_DEFINITIONS)
}
PHASES = tuple(PHASE_GATE_DEFINITIONS)
MANDATORY_PHASES = frozenset(definition.phase_code for definition in GATE_DEFINITIONS if definition.mandatory)
MANDATORY_GATE_COUNT = sum(definition.mandatory for definition in GATE_DEFINITIONS)


def get_gate_definition(phase_code: str, gate_code: str) -> GateDefinition | None:
    return GATE_REGISTRY.get((phase_code, gate_code))


def get_phase_gate_definitions(phase_code: str, *, mandatory_only: bool = False) -> tuple[GateDefinition, ...]:
    definitions = PHASE_GATE_DEFINITIONS.get(phase_code, ())
    if mandatory_only:
        return tuple(definition for definition in definitions if definition.mandatory)
    return definitions


def gate_contract_payload() -> dict[str, object]:
    return {
        "contract_version": GATE_CONTRACT_VERSION,
        "mandatory_gate_count": MANDATORY_GATE_COUNT,
        "phase_mapping": {
            phase_code: [definition.gate_code for definition in definitions]
            for phase_code, definitions in PHASE_GATE_DEFINITIONS.items()
        },
    }


def validate_gate_registry() -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for definition in GATE_DEFINITIONS:
        if definition.key in seen:
            errors.append(
                {
                    "error": "duplicate_gate_definition",
                    "phase_code": definition.phase_code,
                    "gate_code": definition.gate_code,
                }
            )
        seen.add(definition.key)
        if not definition.allowed_statuses <= TERMINAL_STATUSES:
            errors.append(
                {
                    "error": "invalid_allowed_status",
                    "phase_code": definition.phase_code,
                    "gate_code": definition.gate_code,
                }
            )
        if definition.mandatory and "SKIPPED" in definition.allowed_statuses:
            errors.append(
                {
                    "error": "mandatory_gate_allows_skipped",
                    "phase_code": definition.phase_code,
                    "gate_code": definition.gate_code,
                }
            )
    return errors
