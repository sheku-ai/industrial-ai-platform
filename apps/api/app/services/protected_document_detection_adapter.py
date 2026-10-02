from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.models.documents import DocumentVersion
from app.services.protected_document_review import (
    DocumentReviewReason,
    DocumentReviewStatus,
    default_actions,
)


class ProtectedDocumentReviewRequired(RuntimeError):
    code = "password_required"

    def __init__(self, review_case_id: UUID) -> None:
        self.review_case_id = review_case_id
        super().__init__("protected document requires human review")


class ProtectedDocumentDetectionAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, *, session_factory) -> None:
        self._delegate = delegate
        self._session_factory = session_factory

    def execute(self, item, heartbeat):
        try:
            return self._delegate.execute(item, heartbeat)
        except Exception as exc:
            if "password_required" not in str(exc):
                raise
            review_case_id = self._persist_detection(item)
            raise ProtectedDocumentReviewRequired(review_case_id) from exc

    def _persist_detection(self, item) -> UUID:
        try:
            document_id = UUID(str(item.input_payload.get("document_id")))
            document_version_id = UUID(str(item.input_payload.get("document_version_id")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError("protected document identifiers are invalid") from exc

        session = self._session_factory()
        try:
            review = session.scalar(
                select(DocumentReviewCase).where(
                    DocumentReviewCase.organization_id == item.organization_id,
                    DocumentReviewCase.document_version_id == document_version_id,
                    DocumentReviewCase.reason == DocumentReviewReason.PASSWORD_REQUIRED.value,
                    DocumentReviewCase.status == DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
                )
            )
            if review is None:
                review = DocumentReviewCase(
                    organization_id=item.organization_id,
                    document_record_id=document_id,
                    document_version_id=document_version_id,
                    status=DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
                    reason=DocumentReviewReason.PASSWORD_REQUIRED.value,
                    detected_format="pdf_encrypted",
                    detected_by="platform.pdf.text_layer",
                    encryption_type="pdf_standard_security",
                    allowed_actions=[
                        action.value for action in default_actions(DocumentReviewReason.PASSWORD_REQUIRED)
                    ],
                    metadata_json={
                        "runtime_execution_id": str(item.execution_id),
                        "credential_value_persisted": False,
                    },
                )
                session.add(review)
                session.flush()
                session.add(
                    DocumentReviewEvent(
                        organization_id=item.organization_id,
                        review_case_id=review.id,
                        event_type="protected_document_detected",
                        from_status=None,
                        to_status=DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
                        actor_subject="worker",
                        details={
                            "runtime_execution_id": str(item.execution_id),
                            "reason": DocumentReviewReason.PASSWORD_REQUIRED.value,
                            "credential_value_persisted": False,
                        },
                    )
                )

            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.organization_id == item.organization_id,
                    DocumentVersion.id == document_version_id,
                )
            )
            if version is not None:
                snapshot = dict(version.source_snapshot or {})
                snapshot.update(
                    {
                        "last_ingestion_execution_id": str(item.execution_id),
                        "last_ingestion_status": DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
                        "review_case_id": str(review.id),
                        "credential_value_persisted": False,
                    }
                )
                version.status = DocumentReviewStatus.PENDING_HUMAN_REVIEW.value
                version.source_snapshot = snapshot

            session.commit()
            return review.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
