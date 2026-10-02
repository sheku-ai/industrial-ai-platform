from datetime import UTC, datetime, timedelta

import pytest

from app.api.routes.document_reviews import router
from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.schemas.document_review import DocumentReviewDecisionRequest


def test_review_models_use_documents_schema() -> None:
    assert DocumentReviewCase.__table__.schema == "documents"
    assert DocumentReviewEvent.__table__.schema == "documents"


def test_review_case_never_defines_plaintext_password_column() -> None:
    columns = {column.name for column in DocumentReviewCase.__table__.columns}

    assert "password" not in columns
    assert "secret" not in columns
    assert "secret_reference" in columns
    assert "secret_expires_at" in columns


def test_review_event_is_auditable_without_secret_value() -> None:
    columns = {column.name for column in DocumentReviewEvent.__table__.columns}

    assert {"event_type", "from_status", "to_status", "action", "actor_subject", "details"}.issubset(columns)
    assert "password" not in columns


def test_secret_reference_must_look_like_external_reference() -> None:
    with pytest.raises(ValueError, match="external secret-store reference"):
        DocumentReviewDecisionRequest(
            action="provide_password",
            reviewer_subject="reviewer",
            target_status="credentials_supplied",
            secret_reference="plaintext-value",
            secret_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )


def test_document_review_router_exposes_queue_and_decisions() -> None:
    paths = {route.path for route in router.routes}

    assert "/document-reviews" in paths
    assert "/document-reviews/{review_id}" in paths
    assert "/document-reviews/{review_id}/events" in paths
    assert "/document-reviews/{review_id}/decisions" in paths
