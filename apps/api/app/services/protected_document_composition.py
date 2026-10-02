from __future__ import annotations

from app.services.protected_document_runtime_adapter import ProtectedDocumentRuntimeAdapter


def compose_protected_document_adapter(
    document_ingestion_adapter,
    *,
    secret_store,
    session_factory,
):
    return ProtectedDocumentRuntimeAdapter(
        document_ingestion_adapter,
        secret_store=secret_store,
        session_factory=session_factory,
    )
