from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    CAPABILITY = "CAPABILITY"
    ENVIRONMENT = "ENVIRONMENT"
    FUNCTIONAL = "FUNCTIONAL"
    CONTRACT = "CONTRACT"
    PERSISTENCE = "PERSISTENCE"
    REPORTING = "REPORTING"


@dataclass(frozen=True)
class AcceptanceError:
    error_code: str
    error_category: str
    error_message: str
    retryable: bool
    environment_related: bool
    capability_related: bool
    functional_defect: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "environment_related": self.environment_related,
            "capability_related": self.capability_related,
            "functional_defect": self.functional_defect,
        }


def _capability(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.CAPABILITY, message, False, False, True, False)


def _environment(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.ENVIRONMENT, message, True, True, False, False)


def _functional(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.FUNCTIONAL, message, False, False, False, True)


def _contract(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.CONTRACT, message, False, False, False, True)


def _persistence(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.PERSISTENCE, message, True, True, False, False)


def _reporting(code: str, message: str) -> AcceptanceError:
    return AcceptanceError(code, ErrorCategory.REPORTING, message, False, False, False, True)


ERRORS: dict[str, AcceptanceError] = {
    "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE": _capability(
        "ORGANIZATION_SCOPED_SEARCH_NOT_AVAILABLE",
        (
            "Enterprise Search does not expose an organization-scoped public contract required "
            "to verify cross-organization isolation."
        ),
    ),
    "ORGANIZATION_ISOLATION_NOT_VERIFIABLE": _capability(
        "ORGANIZATION_ISOLATION_NOT_VERIFIABLE",
        "Organization isolation cannot be verified with the available public contracts.",
    ),
    "CROSS_ORGANIZATION_ACCESS_DETECTED": _functional(
        "CROSS_ORGANIZATION_ACCESS_DETECTED",
        "Enterprise Search returned resources outside the requested organization scope.",
    ),
    "ENTERPRISE_SEARCH_CAPABILITY_NOT_AVAILABLE": _capability(
        "ENTERPRISE_SEARCH_CAPABILITY_NOT_AVAILABLE",
        "Enterprise Search is not available through the public API contract.",
    ),
    "ENTERPRISE_SEARCH_SCOPE_NOT_ENFORCED": _functional(
        "ENTERPRISE_SEARCH_SCOPE_NOT_ENFORCED",
        "Enterprise Search accepted scope but did not enforce organization isolation.",
    ),
    "PUBLIC_CLEANUP_API_NOT_AVAILABLE": _capability(
        "PUBLIC_CLEANUP_API_NOT_AVAILABLE",
        "A public cleanup API is not available for the governed resource.",
    ),
    "PUBLIC_READ_API_NOT_AVAILABLE": _capability(
        "PUBLIC_READ_API_NOT_AVAILABLE",
        "A public read API is not available for the governed resource.",
    ),
    "PUBLIC_WRITE_API_NOT_AVAILABLE": _capability(
        "PUBLIC_WRITE_API_NOT_AVAILABLE",
        "A public write API is not available for the governed resource.",
    ),
    "REQUIRED_RUNTIME_NOT_AVAILABLE": _environment(
        "REQUIRED_RUNTIME_NOT_AVAILABLE",
        "A required runtime is not available in the current environment.",
    ),
    "REQUIRED_ENDPOINT_NOT_AVAILABLE": _capability(
        "REQUIRED_ENDPOINT_NOT_AVAILABLE",
        "A required public endpoint is not available in the OpenAPI contract.",
    ),
    "AUTHENTICATION_NOT_AVAILABLE": _capability(
        "AUTHENTICATION_NOT_AVAILABLE",
        "Authentication evidence is not available through the public contract.",
    ),
    "ACCEPTANCE_AUTHENTICATION_FAILED": _environment(
        "ACCEPTANCE_AUTHENTICATION_FAILED",
        "Local Product Acceptance could not establish an authenticated operator session.",
    ),
    "DATABASE_NOT_READY": _environment("DATABASE_NOT_READY", "The PostgreSQL database is not ready."),
    "OBJECT_STORAGE_NOT_READY": _environment("OBJECT_STORAGE_NOT_READY", "Object storage is not ready."),
    "POSTGRESQL_FTS_NOT_READY": _environment("POSTGRESQL_FTS_NOT_READY", "PostgreSQL FTS is not ready."),
    "DETERMINISTIC_LLM_NOT_READY": _environment(
        "DETERMINISTIC_LLM_NOT_READY",
        "The deterministic local LLM/provider path is not ready.",
    ),
    "MIGRATION_STATE_INCOMPATIBLE": _environment(
        "MIGRATION_STATE_INCOMPATIBLE",
        "The database migration state is incompatible with product acceptance.",
    ),
    "EVIDENCE_PERSISTENCE_FAILED": _persistence(
        "EVIDENCE_PERSISTENCE_FAILED",
        "Acceptance evidence could not be persisted through the public API.",
    ),
    "REPORT_WRITE_FAILED": _reporting("REPORT_WRITE_FAILED", "The acceptance report could not be written."),
    "IDEMPOTENCY_VIOLATION": _functional(
        "IDEMPOTENCY_VIOLATION",
        "A governed resource was duplicated or changed identity during idempotency verification.",
    ),
    "DUPLICATE_GOVERNED_RESOURCE_DETECTED": _functional(
        "DUPLICATE_GOVERNED_RESOURCE_DETECTED",
        "Duplicate governed resources were detected for the same external reference.",
    ),
    "RESOURCE_LINEAGE_INCOMPLETE": _functional(
        "RESOURCE_LINEAGE_INCOMPLETE",
        "A governed resource lineage is incomplete.",
    ),
    "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED": _functional(
        "ORGANIZATION_HIERARCHY_PERSISTENCE_FAILED",
        "The governed organization hierarchy could not be persisted or verified.",
    ),
    "CHUNK_PERSISTENCE_NOT_COMPLETED": _functional(
        "CHUNK_PERSISTENCE_NOT_COMPLETED",
        "Chunk generation did not produce completed chunk evidence.",
    ),
    "KNOWLEDGE_PUBLICATION_NOT_COMPLETED": _functional(
        "KNOWLEDGE_PUBLICATION_NOT_COMPLETED",
        "Knowledge publication did not complete successfully.",
    ),
    "KNOWLEDGE_INDEX_NOT_COMPLETED": _functional(
        "KNOWLEDGE_INDEX_NOT_COMPLETED",
        "Knowledge indexing did not complete successfully.",
    ),
    "CITATION_VERIFICATION_FAILED": _functional(
        "CITATION_VERIFICATION_FAILED",
        "Citation verification did not complete successfully.",
    ),
    "AUDIT_TRACE_INCOMPLETE": _functional("AUDIT_TRACE_INCOMPLETE", "Audit trace evidence is incomplete."),
    "ACCEPTANCE_GATE_CONTRACT_INVALID": _contract(
        "ACCEPTANCE_GATE_CONTRACT_INVALID",
        "The product acceptance gate contract is invalid.",
    ),
}


def get_error(error_code: str | None) -> AcceptanceError | None:
    if not error_code:
        return None
    return ERRORS.get(error_code)


def error_payload(error_code: str | None) -> dict[str, object]:
    error = get_error(error_code)
    return error.to_dict() if error else {}
