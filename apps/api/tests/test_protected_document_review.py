from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.protected_document_review import (
    DocumentReviewAction,
    DocumentReviewReason,
    DocumentReviewStatus,
    InvalidReviewTransition,
    ReviewDecision,
    TemporarySecretReference,
    create_review_case,
    validate_transition,
)


def test_encrypted_document_creates_pending_human_review_case() -> None:
    case = create_review_case(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        reason=DocumentReviewReason.PASSWORD_REQUIRED,
        detected_format="pdf",
        detected_by="native-pdf",
    )

    assert case.status == DocumentReviewStatus.PENDING_HUMAN_REVIEW
    assert DocumentReviewAction.PROVIDE_PASSWORD in case.allowed_actions
    assert DocumentReviewAction.QUARANTINE in case.allowed_actions


def test_password_action_requires_temporary_secret_reference() -> None:
    with pytest.raises(ValueError, match="requires a temporary secret"):
        ReviewDecision(
            action=DocumentReviewAction.PROVIDE_PASSWORD,
            reviewer_subject="reviewer-1",
            decided_at=datetime.now(UTC),
        )


def test_temporary_secret_must_expire_in_future() -> None:
    with pytest.raises(ValueError, match="expire in the future"):
        TemporarySecretReference(
            secret_reference="secret://review/1",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_valid_password_decision_uses_reference_not_plaintext() -> None:
    secret = TemporarySecretReference(
        secret_reference="secret://review/1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    decision = ReviewDecision(
        action=DocumentReviewAction.PROVIDE_PASSWORD,
        reviewer_subject="reviewer-1",
        decided_at=datetime.now(UTC),
        secret_reference=secret,
    )

    assert decision.secret_reference is not None
    assert decision.secret_reference.single_use is True


def test_review_transition_is_controlled() -> None:
    validate_transition(
        DocumentReviewStatus.PENDING_HUMAN_REVIEW,
        DocumentReviewStatus.CREDENTIALS_SUPPLIED,
    )
    with pytest.raises(InvalidReviewTransition):
        validate_transition(
            DocumentReviewStatus.REJECTED_BY_REVIEWER,
            DocumentReviewStatus.APPROVED_FOR_PROCESSING,
        )
