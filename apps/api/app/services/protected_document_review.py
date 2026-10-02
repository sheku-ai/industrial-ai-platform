from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DocumentReviewStatus(StrEnum):
    PENDING_HUMAN_REVIEW = "pending_human_review"
    CREDENTIALS_SUPPLIED = "credentials_supplied"
    APPROVED_FOR_PROCESSING = "approved_for_processing"
    APPROVED_METADATA_ONLY = "approved_metadata_only"
    REJECTED_BY_REVIEWER = "rejected_by_reviewer"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"
    RESOLVED = "resolved"


class DocumentReviewReason(StrEnum):
    PASSWORD_REQUIRED = "password_required"
    ENCRYPTED_DOCUMENT = "encrypted_document"
    ENCRYPTED_CONTAINER = "encrypted_container"
    UNSUPPORTED_ENCRYPTION = "unsupported_encryption"
    CORRUPTED_OR_ENCRYPTED = "corrupted_or_encrypted"
    MALWARE_SCAN_REQUIRED = "malware_scan_required"
    MANUAL_CLASSIFICATION_REQUIRED = "manual_classification_required"


class DocumentReviewAction(StrEnum):
    PROVIDE_PASSWORD = "provide_password"
    APPROVE_METADATA_ONLY = "approve_metadata_only"
    APPROVE_EXTERNAL_DECRYPTION = "approve_external_decryption"
    REQUEST_NEW_COPY = "request_new_copy"
    REJECT_DOCUMENT = "reject_document"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class ProtectedDocumentDetection:
    protected: bool
    reason: DocumentReviewReason | None = None
    encryption_type: str | None = None
    password_required: bool = False
    detected_by: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.protected and self.reason is None:
            raise ValueError("protected detection requires a review reason")
        if not self.protected and self.reason is not None:
            raise ValueError("unprotected detection cannot include a review reason")


@dataclass(frozen=True)
class DocumentReviewCase:
    review_id: UUID
    organization_id: UUID
    document_id: UUID
    document_version_id: UUID
    status: DocumentReviewStatus
    reason: DocumentReviewReason
    detected_format: str
    detected_by: str
    allowed_actions: tuple[DocumentReviewAction, ...]
    created_at: datetime
    expires_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemporarySecretReference:
    secret_reference: str
    expires_at: datetime
    single_use: bool = True

    def __post_init__(self) -> None:
        if not self.secret_reference:
            raise ValueError("secret_reference is required")
        if self.expires_at <= datetime.now(UTC):
            raise ValueError("temporary secret must expire in the future")


@dataclass(frozen=True)
class ReviewDecision:
    action: DocumentReviewAction
    reviewer_subject: str
    decided_at: datetime
    secret_reference: TemporarySecretReference | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewer_subject:
            raise ValueError("reviewer_subject is required")
        if self.action == DocumentReviewAction.PROVIDE_PASSWORD and self.secret_reference is None:
            raise ValueError("provide_password requires a temporary secret reference")
        if self.action != DocumentReviewAction.PROVIDE_PASSWORD and self.secret_reference is not None:
            raise ValueError("temporary secret is only valid for provide_password")


class InvalidReviewTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[DocumentReviewStatus, frozenset[DocumentReviewStatus]] = {
    DocumentReviewStatus.PENDING_HUMAN_REVIEW: frozenset(
        {
            DocumentReviewStatus.CREDENTIALS_SUPPLIED,
            DocumentReviewStatus.APPROVED_METADATA_ONLY,
            DocumentReviewStatus.REJECTED_BY_REVIEWER,
            DocumentReviewStatus.QUARANTINED,
            DocumentReviewStatus.EXPIRED,
        }
    ),
    DocumentReviewStatus.CREDENTIALS_SUPPLIED: frozenset(
        {
            DocumentReviewStatus.APPROVED_FOR_PROCESSING,
            DocumentReviewStatus.PENDING_HUMAN_REVIEW,
            DocumentReviewStatus.QUARANTINED,
            DocumentReviewStatus.EXPIRED,
        }
    ),
    DocumentReviewStatus.APPROVED_FOR_PROCESSING: frozenset(
        {DocumentReviewStatus.RESOLVED, DocumentReviewStatus.PENDING_HUMAN_REVIEW}
    ),
    DocumentReviewStatus.APPROVED_METADATA_ONLY: frozenset({DocumentReviewStatus.RESOLVED}),
    DocumentReviewStatus.REJECTED_BY_REVIEWER: frozenset(),
    DocumentReviewStatus.QUARANTINED: frozenset(),
    DocumentReviewStatus.EXPIRED: frozenset(),
    DocumentReviewStatus.RESOLVED: frozenset(),
}


def validate_transition(current: DocumentReviewStatus, target: DocumentReviewStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidReviewTransition(f"invalid review transition: {current} -> {target}")


def default_actions(reason: DocumentReviewReason) -> tuple[DocumentReviewAction, ...]:
    if reason in {
        DocumentReviewReason.PASSWORD_REQUIRED,
        DocumentReviewReason.ENCRYPTED_DOCUMENT,
        DocumentReviewReason.ENCRYPTED_CONTAINER,
    }:
        return (
            DocumentReviewAction.PROVIDE_PASSWORD,
            DocumentReviewAction.APPROVE_METADATA_ONLY,
            DocumentReviewAction.APPROVE_EXTERNAL_DECRYPTION,
            DocumentReviewAction.REQUEST_NEW_COPY,
            DocumentReviewAction.REJECT_DOCUMENT,
            DocumentReviewAction.QUARANTINE,
        )
    return (
        DocumentReviewAction.APPROVE_METADATA_ONLY,
        DocumentReviewAction.REQUEST_NEW_COPY,
        DocumentReviewAction.REJECT_DOCUMENT,
        DocumentReviewAction.QUARANTINE,
    )


def create_review_case(
    *,
    organization_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    reason: DocumentReviewReason,
    detected_format: str,
    detected_by: str,
    metadata: Mapping[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> DocumentReviewCase:
    return DocumentReviewCase(
        review_id=uuid4(),
        organization_id=organization_id,
        document_id=document_id,
        document_version_id=document_version_id,
        status=DocumentReviewStatus.PENDING_HUMAN_REVIEW,
        reason=reason,
        detected_format=detected_format,
        detected_by=detected_by,
        allowed_actions=default_actions(reason),
        created_at=datetime.now(UTC),
        expires_at=expires_at,
        metadata=dict(metadata or {}),
    )
