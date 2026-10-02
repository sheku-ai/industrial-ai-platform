import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.documents import (
    DocumentBinaryUploadExecuteRequest,
    DocumentBinaryUploadPlanRequest,
    DocumentChunkGenerationRequest,
    EnterpriseSearchRequest,
    KnowledgePublicationRequest,
)
from app.services.document_binary_upload_control_plane import build_upload_session_status
from app.services.document_binary_upload_execution import (
    build_document_binary_upload_execution,
)
from app.services.document_binary_upload_planning import build_document_binary_upload_plan
from app.services.document_processing_control_plane import (
    build_document_processing_chunks_generate,
    build_document_processing_enterprise_search,
    build_document_processing_execute,
    build_document_processing_handoff_prepare,
    build_document_processing_knowledge_publish,
    build_document_processing_status,
)

router = APIRouter(prefix="/documents", tags=["document-binary-uploads"])


@router.post("/versions/uploads/plan")
def plan_document_binary_upload(
    payload: DocumentBinaryUploadPlanRequest,
    db: Session = Depends(get_db),
):
    return build_document_binary_upload_plan(db, payload=payload)


@router.post("/versions/uploads/execute", status_code=status.HTTP_201_CREATED)
def execute_document_binary_upload(
    payload: DocumentBinaryUploadExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        result = build_document_binary_upload_execution(db, payload=payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="document binary upload execution conflict",
        ) from exc

    if result.get("execution_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    return result


@router.get("/versions/uploads/{artifact_id}/status")
def get_document_binary_upload_status(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_upload_session_status(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result


@router.get("/processing/{artifact_id}/status")
def get_document_processing_status(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_document_processing_status(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result


@router.post("/processing/{artifact_id}/handoff/prepare")
def prepare_document_processing_handoff(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_document_processing_handoff_prepare(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    return result


@router.post("/processing/{artifact_id}/execute")
def execute_document_processing(
    artifact_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    result = build_document_processing_execute(db, artifact_id=artifact_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    if result.get("processing_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.post("/processing/{artifact_id}/chunks/generate")
def generate_document_chunks(
    artifact_id: uuid.UUID,
    payload: DocumentChunkGenerationRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or DocumentChunkGenerationRequest()
    result = build_document_processing_chunks_generate(
        db,
        artifact_id=artifact_id,
        storage_execution_status=payload.storage_execution_status,
        chunker_config=payload.chunker_config,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    chunk_generation = result.get("chunk_generation") if isinstance(result.get("chunk_generation"), dict) else {}
    if chunk_generation.get("chunk_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.post("/processing/{artifact_id}/knowledge/publish")
def publish_document_knowledge(
    artifact_id: uuid.UUID,
    payload: KnowledgePublicationRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or KnowledgePublicationRequest()
    result = build_document_processing_knowledge_publish(
        db,
        artifact_id=artifact_id,
        storage_execution_status=payload.storage_execution_status,
        chunker_config=payload.chunker_config,
        publication_config=payload.publication_config,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    publication = result.get("knowledge_publication") if isinstance(result.get("knowledge_publication"), dict) else {}
    if publication.get("publication_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result


@router.post("/processing/{artifact_id}/search")
def search_document_knowledge(
    artifact_id: uuid.UUID,
    payload: EnterpriseSearchRequest,
    db: Session = Depends(get_db),
):
    result = build_document_processing_enterprise_search(
        db,
        artifact_id=artifact_id,
        query=payload.query,
        top_k=payload.top_k,
        storage_execution_status=payload.storage_execution_status,
        chunker_config=payload.chunker_config,
        publication_config=payload.publication_config,
        search_config=payload.search_config,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binary upload artifact not found")
    search = result.get("enterprise_search") if isinstance(result.get("enterprise_search"), dict) else {}
    if search.get("search_status") == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)
    return result
