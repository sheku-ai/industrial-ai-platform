from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.readiness import AuthoritativeReadinessEvidence, ReadinessGateEvidence

READINESS_CONTRACT_VERSION = "platform.readiness.evidence.v1"
READINESS_STATUSES = {"passed", "failed", "blocked", "not_evaluated", "expired", "stale", "interrupted"}


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def build_readiness_evidence(
    *,
    domain: str | None,
    status: str | None,
    gate_results: list[Any] | None,
    blockers: list[dict[str, Any]] | None,
    warnings: list[dict[str, Any]] | None,
    recommendations: list[dict[str, Any]] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
    runtime_version: str | None,
    evaluation_timestamp: datetime | None,
    expires_at: datetime | None,
    evidence_origin: str | None,
    evaluation_duration: int | None = 0,
    components_evaluated: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    reason: str | None = None,
    source_contract_version: str | None = None,
    supported_contract_versions: tuple[str, ...] = (),
    source_runtime_version: str | None = None,
    supported_runtime_versions: tuple[str, ...] = (),
    integrity_errors: list[dict[str, Any]] | None = None,
) -> AuthoritativeReadinessEvidence:
    normalized_status = status if status in READINESS_STATUSES else "failed"
    normalized_blockers = list(blockers or [])
    normalized_warnings = list(warnings or [])
    normalized_recommendations = list(recommendations or [])
    normalized_actions = list(next_actions or [])
    version_errors: list[dict[str, Any]] = []
    if supported_contract_versions and source_contract_version not in supported_contract_versions:
        version_errors.append(
            {
                "code": "unsupported_contract_version",
                "message": "Persisted evidence uses an unsupported contract version.",
                "observed_version": source_contract_version,
            }
        )
    if supported_runtime_versions and source_runtime_version not in supported_runtime_versions:
        version_errors.append(
            {
                "code": "incompatible_runtime_version",
                "message": "Persisted evidence uses an incompatible runtime version.",
                "observed_version": source_runtime_version,
            }
        )
    hardening_errors = version_errors + list(integrity_errors or [])
    normalized_domain = str(domain or "unknown")
    normalized_runtime_version = str(runtime_version or "unknown-runtime")
    normalized_origin = str(evidence_origin or "unknown")
    if (
        not domain
        or not str(domain).strip()
        or not runtime_version
        or not str(runtime_version).strip()
        or not evidence_origin
        or not str(evidence_origin).strip()
    ):
        hardening_errors.append(
            {
                "code": "incomplete_readiness_contract",
                "message": "Domain, runtime version and evidence origin are required.",
            }
        )
    normalized_duration = evaluation_duration if isinstance(evaluation_duration, int) else 0
    if not isinstance(evaluation_duration, int) or evaluation_duration < 0:
        hardening_errors.append(
            {"code": "invalid_evaluation_duration", "message": "Evaluation duration cannot be negative."}
        )
        normalized_duration = 0
    if status not in READINESS_STATUSES:
        hardening_errors.append(
            {"code": "invalid_readiness_status", "message": "Runtime returned an unsupported readiness status."}
        )
    timestamp = evaluation_timestamp or datetime.now(UTC)
    if not isinstance(timestamp, datetime):
        hardening_errors.append(
            {"code": "invalid_evaluation_timestamp", "message": "Evaluation timestamp must be a datetime."}
        )
        timestamp = datetime.now(UTC)
    elif timestamp.tzinfo is None:
        hardening_errors.append(
            {"code": "invalid_evaluation_timestamp", "message": "Evaluation timestamp must include a timezone."}
        )
        timestamp = timestamp.replace(tzinfo=UTC)
    normalized_expiry = expires_at
    if normalized_expiry is not None and not isinstance(normalized_expiry, datetime):
        hardening_errors.append(
            {"code": "invalid_expiration_timestamp", "message": "Expiration timestamp must be a datetime."}
        )
        normalized_expiry = None
    elif normalized_expiry is not None and normalized_expiry.tzinfo is None:
        hardening_errors.append(
            {"code": "invalid_expiration_timestamp", "message": "Expiration timestamp must include a timezone."}
        )
        normalized_expiry = normalized_expiry.replace(tzinfo=UTC)
    if (
        normalized_expiry is not None
        and normalized_expiry <= timestamp
        and normalized_status not in {"expired", "stale"}
    ):
        hardening_errors.append(
            {"code": "invalid_evidence_lifetime", "message": "Evidence expiration must be after evaluation."}
        )
    normalized: list[ReadinessGateEvidence] = []
    all_evidence_ids = [str(item) for item in (evidence_ids or []) if item is not None]
    all_components = [str(item) for item in (components_evaluated or []) if item is not None]
    if not gate_results:
        hardening_errors.append(
            {
                "code": "readiness_gate_results_missing",
                "message": "Readiness contract must contain governed gate results.",
            }
        )
    for item in gate_results or []:
        reference = _value(item, "evidence_reference")
        gate_code = str(_value(item, "gate_code", "unknown_gate"))
        ids = [str(reference)] if reference else []
        raw_components = _value(item, "components_evaluated", []) or [gate_code]
        components = (
            [str(value) for value in raw_components] if isinstance(raw_components, list | tuple | set) else [gate_code]
        )
        gate_status = str(_value(item, "status", "not_evaluated"))
        if gate_status not in READINESS_STATUSES:
            hardening_errors.append(
                {"code": "invalid_gate_status", "message": f"Gate {gate_code} returned an unsupported status."}
            )
            gate_status = "failed"
        normalized.append(
            ReadinessGateEvidence(
                gate_code=gate_code,
                status="failed" if hardening_errors else gate_status,
                summary=str(_value(item, "summary", "Persisted readiness evidence is unavailable.")),
                evidence_ids=ids,
                components_evaluated=components,
            )
        )
        all_evidence_ids.extend(ids)
        all_components.extend(components)
    if hardening_errors:
        normalized_status = "failed"
        normalized = [item.model_copy(update={"status": "failed"}) for item in normalized]
        normalized_blockers.extend(hardening_errors)
        normalized_recommendations.append(
            {"code": "replace_invalid_evidence", "message": "Register compatible, integrity-verified evidence."}
        )
        normalized_actions.append({"action": "register_valid_readiness_evidence"})
    return AuthoritativeReadinessEvidence(
        domain=normalized_domain,
        status=normalized_status,
        reason=("contract_hardening_failed" if hardening_errors else reason)
        or {
            "passed": "authoritative_evidence_passed",
            "blocked": "authoritative_evidence_blocked",
            "failed": "authoritative_evidence_failed",
            "not_evaluated": "authoritative_evidence_missing",
            "expired": "authoritative_evidence_expired",
            "stale": "authoritative_evidence_stale",
            "interrupted": "evaluation_interrupted",
        }[normalized_status],
        gate_results=normalized,
        blockers=normalized_blockers,
        warnings=normalized_warnings,
        recommendations=normalized_recommendations,
        next_actions=normalized_actions,
        contract_version=READINESS_CONTRACT_VERSION,
        runtime_version=normalized_runtime_version,
        evaluation_timestamp=timestamp,
        expires_at=normalized_expiry,
        evidence_origin=normalized_origin,
        evaluation_duration=normalized_duration,
        components_evaluated=sorted(set(all_components)),
        evidence_ids=sorted(set(all_evidence_ids)),
    )
