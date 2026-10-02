from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.models.documents import DocumentVersion, IngestionJob
from app.models.runtime import RuntimeExecution
from app.services.protected_document_review import DocumentReviewStatus, InvalidReviewTransition, validate_transition
from app.services.secret_store import SecretExpired, SecretNotFound, SecretStore, SecretValue


class DocumentReviewRuntimeError(RuntimeError):
    pass


class DocumentReviewRuntimeService:
    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    def supply_credentials(
        self,
        db: Session,
        *,
        review_case: DocumentReviewCase,
        secret_value: str,
        actor_subject: str,
        ttl_seconds: int,
    ) -> DocumentReviewCase:
        if not secret_value:
            raise DocumentReviewRuntimeError("credential value is required")
        if ttl_seconds < 1 or ttl_seconds > 3600:
            raise DocumentReviewRuntimeError("credential TTL must be between 1 and 3600 seconds")

        current = DocumentReviewStatus(review_case.status)
        try:
            validate_transition(current, DocumentReviewStatus.CREDENTIALS_SUPPLIED)
        except InvalidReviewTransition as exc:
            raise DocumentReviewRuntimeError(str(exc)) from exc

        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        reference = f"redis-secret://document-review/{review_case.id}/{uuid4()}"
        self._secret_store.put(
            reference,
            SecretValue(value=secret_value, expires_at=expires_at, single_use=True),
        )

        previous_status = review_case.status
        review_case.status = DocumentReviewStatus.CREDENTIALS_SUPPLIED.value
        review_case.secret_reference = reference
        review_case.secret_expires_at = expires_at
        review_case.secret_single_use = True
        review_case.updated_by = actor_subject
        db.add(
            DocumentReviewEvent(
                organization_id=review_case.organization_id,
                review_case_id=review_case.id,
                event_type="credentials_supplied",
                from_status=previous_status,
                to_status=review_case.status,
                action="provide_password",
                actor_subject=actor_subject,
                details={
                    "secret_reference_supplied": True,
                    "secret_single_use": True,
                    "secret_value_persisted": False,
                    "secret_ttl_seconds": ttl_seconds,
                },
            )
        )
        try:
            db.commit()
            db.refresh(review_case)
        except Exception:
            db.rollback()
            self._secret_store.revoke(reference)
            raise
        return review_case

    def expire_due_cases(self, db: Session, *, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        statement = select(DocumentReviewCase).where(
            DocumentReviewCase.status.in_(
                [
                    DocumentReviewStatus.PENDING_HUMAN_REVIEW.value,
                    DocumentReviewStatus.CREDENTIALS_SUPPLIED.value,
                    DocumentReviewStatus.APPROVED_FOR_PROCESSING.value,
                ]
            ),
            DocumentReviewCase.expires_at.is_not(None),
            DocumentReviewCase.expires_at <= current_time,
        )
        cases = list(db.scalars(statement).all())
        for case in cases:
            previous_status = case.status
            if case.secret_reference:
                self._secret_store.revoke(case.secret_reference)
            case.secret_reference = None
            case.secret_expires_at = None
            case.status = DocumentReviewStatus.EXPIRED.value
            case.resolved_at = current_time
            db.add(
                DocumentReviewEvent(
                    organization_id=case.organization_id,
                    review_case_id=case.id,
                    event_type="review_expired",
                    from_status=previous_status,
                    to_status=case.status,
                    actor_subject="system",
                    details={"secret_revoked": True},
                )
            )
        if cases:
            db.commit()
        return len(cases)

    def authorize_retry(
        self,
        db: Session,
        *,
        review_case: DocumentReviewCase,
        actor_subject: str,
    ) -> RuntimeExecution:
        current = DocumentReviewStatus(review_case.status)
        try:
            validate_transition(current, DocumentReviewStatus.APPROVED_FOR_PROCESSING)
        except InvalidReviewTransition as exc:
            raise DocumentReviewRuntimeError(str(exc)) from exc
        if not review_case.secret_reference or not review_case.secret_expires_at:
            raise DocumentReviewRuntimeError("review case has no active temporary secret")
        if review_case.secret_expires_at <= datetime.now(UTC):
            self._secret_store.revoke(review_case.secret_reference)
            raise DocumentReviewRuntimeError("temporary secret has expired")

        try:
            secret = self._secret_store.inspect(review_case.secret_reference)
        except SecretNotFound as exc:
            raise DocumentReviewRuntimeError("temporary secret reference was not found") from exc
        except SecretExpired as exc:
            raise DocumentReviewRuntimeError("temporary secret has expired") from exc

        version = db.get(DocumentVersion, review_case.document_version_id)
        if version is None:
            raise DocumentReviewRuntimeError("document version not found")

        previous_execution = None
        if review_case.ingestion_job_id is not None:
            job = db.get(IngestionJob, review_case.ingestion_job_id)
            if job is not None and job.runtime_execution_id is not None:
                previous_execution = db.get(RuntimeExecution, job.runtime_execution_id)
        if previous_execution is None:
            previous_execution = db.scalar(
                select(RuntimeExecution)
                .where(
                    RuntimeExecution.organization_id == review_case.organization_id,
                    RuntimeExecution.execution_type == "document.ingestion",
                    RuntimeExecution.subject_type == "document_version",
                    RuntimeExecution.subject_id == review_case.document_version_id,
                )
                .order_by(RuntimeExecution.created_at.desc())
                .limit(1)
            )
        if previous_execution is None:
            raise DocumentReviewRuntimeError("original ingestion execution not found")

        input_payload = dict(previous_execution.input_payload or {})
        input_payload["protected_document"] = True
        input_payload["review_case_id"] = str(review_case.id)
        input_payload["secret_reference"] = review_case.secret_reference
        options = dict(input_payload.get("options") or {})
        options["protected_document"] = True
        input_payload["options"] = options

        execution = RuntimeExecution(
            organization_id=review_case.organization_id,
            execution_type="document.ingestion",
            subject_type="document_version",
            subject_id=review_case.document_version_id,
            requested_by=actor_subject,
            correlation_id=f"document-review:{review_case.id}",
            idempotency_key=f"document-review-retry:{review_case.id}:{review_case.updated_at.isoformat()}",
            priority=50,
            status="pending",
            input_payload=input_payload,
            policy_snapshot={
                **dict(previous_execution.policy_snapshot or {}),
                "review_case_id": str(review_case.id),
                "single_use_secret": secret.single_use,
                "secret_expires_at": secret.expires_at.isoformat(),
                "previous_execution_id": str(previous_execution.id),
            },
            metrics={},
            created_by=actor_subject,
        )
        db.add(execution)
        db.flush()

        previous_status = review_case.status
        review_case.status = DocumentReviewStatus.APPROVED_FOR_PROCESSING.value
        review_case.updated_by = actor_subject
        db.add(
            DocumentReviewEvent(
                organization_id=review_case.organization_id,
                review_case_id=review_case.id,
                event_type="retry_authorized",
                from_status=previous_status,
                to_status=review_case.status,
                action="provide_password",
                actor_subject=actor_subject,
                details={
                    "runtime_execution_id": str(execution.id),
                    "secret_reference_used": True,
                    "secret_value_persisted": False,
                },
            )
        )
        db.commit()
        db.refresh(execution)
        return execution
