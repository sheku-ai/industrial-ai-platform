from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.models.document_review import DocumentReviewCase, DocumentReviewEvent
from app.services.protected_document_review import DocumentReviewStatus
from app.services.runtime_worker import RuntimeAdapterResult, RuntimeWorkItem
from app.services.secret_store import SecretExpired, SecretNotFound, SecretStore


class ProtectedDocumentRuntimeError(RuntimeError):
    pass


class ProtectedDocumentRuntimeAdapter:
    execution_type = "document.ingestion"

    def __init__(self, delegate, *, secret_store: SecretStore, session_factory) -> None:
        self._delegate = delegate
        self._secret_store = secret_store
        self._session_factory = session_factory

    def execute(self, item: RuntimeWorkItem, heartbeat) -> RuntimeAdapterResult:
        secret_reference = item.input_payload.get("secret_reference")
        review_case_id = item.input_payload.get("review_case_id")
        if not secret_reference and not review_case_id:
            return self._delegate.execute(item, heartbeat)
        if not isinstance(secret_reference, str) or not secret_reference:
            raise ProtectedDocumentRuntimeError("protected document retry is missing secret_reference")
        if not review_case_id:
            raise ProtectedDocumentRuntimeError("protected document retry is missing review_case_id")
        try:
            review_uuid = UUID(str(review_case_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ProtectedDocumentRuntimeError("review_case_id must be a UUID") from exc

        try:
            secret = self._secret_store.resolve(secret_reference)
        except SecretNotFound as exc:
            self._reopen(review_uuid, item.execution_id, "secret_not_found")
            raise ProtectedDocumentRuntimeError("temporary secret reference was not found") from exc
        except SecretExpired as exc:
            self._reopen(review_uuid, item.execution_id, "secret_expired")
            raise ProtectedDocumentRuntimeError("temporary secret has expired") from exc

        protected_payload = dict(item.input_payload)
        protected_payload.pop("secret_reference", None)
        options = dict(protected_payload.get("options") or {})
        options["document_password"] = secret.value
        options["protected_document"] = True
        options["review_case_id"] = str(review_uuid)
        protected_payload["options"] = options
        protected_item = replace(item, input_payload=protected_payload)

        try:
            result = self._delegate.execute(protected_item, heartbeat)
        except Exception:
            self._reopen(review_uuid, item.execution_id, "protected_retry_failed")
            raise
        else:
            self._resolve(review_uuid, item.execution_id)
            metrics = dict(result.metrics)
            metrics.update(
                {
                    "protected_document_retry": True,
                    "review_case_id": str(review_uuid),
                    "secret_value_persisted": False,
                    "secret_consumed": secret.single_use,
                }
            )
            return RuntimeAdapterResult(metrics=metrics)
        finally:
            self._secret_store.revoke(secret_reference)
            options["document_password"] = ""

    def _resolve(self, review_case_id: UUID, execution_id: UUID) -> None:
        session = self._session_factory()
        try:
            case = session.scalar(select(DocumentReviewCase).where(DocumentReviewCase.id == review_case_id))
            if case is None:
                raise ProtectedDocumentRuntimeError("document review case not found")
            previous_status = case.status
            case.status = DocumentReviewStatus.RESOLVED.value
            case.resolved_at = datetime.now(UTC)
            case.secret_reference = None
            case.secret_expires_at = None
            session.add(
                DocumentReviewEvent(
                    organization_id=case.organization_id,
                    review_case_id=case.id,
                    event_type="protected_retry_succeeded",
                    from_status=previous_status,
                    to_status=case.status,
                    actor_subject="worker",
                    details={
                        "runtime_execution_id": str(execution_id),
                        "secret_revoked": True,
                        "secret_value_persisted": False,
                    },
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _reopen(self, review_case_id: UUID, execution_id: UUID, reason: str) -> None:
        session = self._session_factory()
        try:
            case = session.scalar(select(DocumentReviewCase).where(DocumentReviewCase.id == review_case_id))
            if case is None:
                return
            previous_status = case.status
            case.status = DocumentReviewStatus.PENDING_HUMAN_REVIEW.value
            case.secret_reference = None
            case.secret_expires_at = None
            case.resolved_at = None
            session.add(
                DocumentReviewEvent(
                    organization_id=case.organization_id,
                    review_case_id=case.id,
                    event_type="protected_retry_reopened",
                    from_status=previous_status,
                    to_status=case.status,
                    actor_subject="worker",
                    details={
                        "runtime_execution_id": str(execution_id),
                        "reason": reason,
                        "secret_revoked": True,
                        "secret_value_persisted": False,
                    },
                )
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
