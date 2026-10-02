import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.models.documents import (
    Chunk,
    ClassificationRule,
    Collection,
    DocumentRecord,
    DocumentType,
    DocumentVersion,
    MetadataTemplate,
    RetentionPolicy,
)
from app.repositories.base import Repository
from app.schemas.documents import (
    CollectionCreate,
    CollectionRead,
    CollectionUpdate,
    DocumentRegistrationRequest,
    DocumentTypeCreate,
    DocumentTypeRead,
    DocumentTypeUpdate,
    MetadataTemplateCreate,
    MetadataTemplateRead,
    MetadataTemplateUpdate,
    PolicyRuleCreate,
    PolicyRuleRead,
    PolicyRuleUpdate,
)
from app.schemas.product_api import ChunkPersistenceRequest, ChunkPersistenceResponse, ChunkRead
from app.services.base import CRUDService
from app.services.data_classification import is_visible_product_data
from app.services.document_management_configuration import (
    build_document_configuration_catalog,
    build_document_configuration_contract,
    build_document_configuration_summary,
    build_document_configuration_validation,
    build_document_type_configuration_profile,
)
from app.services.document_registration import (
    build_document_registration_plan,
    build_document_registration_prevalidation,
)

router = APIRouter(prefix="/documents", tags=["documents"])

document_type_service = CRUDService(Repository(DocumentType))
metadata_template_service = CRUDService(Repository(MetadataTemplate))
retention_policy_service = CRUDService(Repository(RetentionPolicy))
classification_rule_service = CRUDService(Repository(ClassificationRule))
collection_service = CRUDService(Repository(Collection))


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")


def _require_document_configuration(context: RuntimeRequestContext, action: str) -> uuid.UUID:
    permitted = context.has_permission("reference_tenant", action)
    if action == "read":
        permitted = permitted or context.has_permission("document_configuration", "read")
    if context.organization_id is None or not permitted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="document configuration permission required")
    return context.organization_id


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_key(document_version_id: uuid.UUID, chunk_index: int) -> str:
    return f"{document_version_id}:{chunk_index:06d}"


def _read_chunk(chunk: Chunk) -> ChunkRead:
    return ChunkRead(
        id=chunk.id,
        created_at=chunk.created_at,
        updated_at=chunk.updated_at,
        organization_id=chunk.organization_id,
        document_record_id=chunk.document_record_id,
        document_version_id=chunk.document_version_id,
        artifact_id=chunk.artifact_id,
        collection_id=chunk.collection_id,
        chunk_index=chunk.chunk_index,
        chunk_key=chunk.chunk_key,
        content_hash=chunk.content_hash,
        semantic_hash=chunk.semantic_hash,
        text=chunk.text,
        content_type=chunk.content_type,
        section_ref=chunk.section_ref or {},
        provenance=chunk.provenance or {},
        quality=chunk.quality or {},
        metadata=chunk.metadata_json or {},
        status=chunk.status,
    )


@router.get("/configuration/catalog")
def get_document_configuration_catalog(
    organization_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    return build_document_configuration_catalog(db, organization_id=organization_id)


@router.get("/configuration/summary")
def get_document_configuration_summary(
    organization_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    catalog = build_document_configuration_catalog(db, organization_id=organization_id)
    return build_document_configuration_summary(catalog)


@router.get("/configuration/validation")
def get_document_configuration_validation(
    organization_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    catalog = build_document_configuration_catalog(db, organization_id=organization_id)
    return build_document_configuration_validation(catalog)


@router.get("/configuration/contract")
def get_document_configuration_contract(
    organization_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    return build_document_configuration_contract(db, organization_id=organization_id)


@router.get("/configuration/document-types/{document_type_id}/profile")
def get_document_type_configuration_profile(
    document_type_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    profile = build_document_type_configuration_profile(
        db,
        document_type_id=document_type_id,
        organization_id=organization_id,
    )
    if not profile["found"]:
        raise _not_found("document type")
    return profile


@router.post("/registration/prevalidate")
def prevalidate_document_registration(
    payload: DocumentRegistrationRequest,
    db: Session = Depends(get_db),
):
    return build_document_registration_prevalidation(db, payload=payload)


@router.post("/registration/plan")
def plan_document_registration(
    payload: DocumentRegistrationRequest,
    db: Session = Depends(get_db),
):
    return build_document_registration_plan(db, payload=payload)


@router.get("/document-types", response_model=list[DocumentTypeRead])
def list_document_types(
    operational_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_document_configuration(context, "read")
    statement = select(DocumentType).where(DocumentType.organization_id == organization_id)
    if operational_only:
        visible = [
            item
            for item in db.scalars(statement.order_by(DocumentType.code.asc())).all()
            if is_visible_product_data(item.config)
        ]
        return visible[skip : skip + limit]
    return list(db.scalars(statement.offset(skip).limit(limit)).all())


@router.post("/document-types", response_model=DocumentTypeRead, status_code=status.HTTP_201_CREATED)
def create_document_type(
    payload: DocumentTypeCreate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_document_configuration(context, "administer")
    data = payload.model_dump()
    data["organization_id"] = organization_id
    return document_type_service.create(db, data)


@router.get("/document-types/{document_type_id}", response_model=DocumentTypeRead)
def get_document_type(
    document_type_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_document_configuration(context, "read")
    item = document_type_service.get(db, document_type_id)
    if item is None or item.organization_id != organization_id:
        raise _not_found("document type")
    return item


@router.patch("/document-types/{document_type_id}", response_model=DocumentTypeRead)
def update_document_type(
    document_type_id: uuid.UUID,
    payload: DocumentTypeUpdate,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_document_configuration(context, "administer")
    item = document_type_service.get(db, document_type_id)
    if item is None or item.organization_id != organization_id:
        raise _not_found("document type")
    return document_type_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.delete("/document-types/{document_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_type(
    document_type_id: uuid.UUID,
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    organization_id = _require_document_configuration(context, "administer")
    item = document_type_service.get(db, document_type_id)
    if item is None or item.organization_id != organization_id:
        raise _not_found("document type")
    document_type_service.delete(db, item)


@router.get("/metadata-templates", response_model=list[MetadataTemplateRead])
def list_metadata_templates(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return metadata_template_service.list(db, skip=skip, limit=limit)


@router.post("/metadata-templates", response_model=MetadataTemplateRead, status_code=status.HTTP_201_CREATED)
def create_metadata_template(payload: MetadataTemplateCreate, db: Session = Depends(get_db)):
    return metadata_template_service.create(db, payload.model_dump())


@router.get("/metadata-templates/{template_id}", response_model=MetadataTemplateRead)
def get_metadata_template(template_id: uuid.UUID, db: Session = Depends(get_db)):
    item = metadata_template_service.get(db, template_id)
    if item is None:
        raise _not_found("metadata template")
    return item


@router.patch("/metadata-templates/{template_id}", response_model=MetadataTemplateRead)
def update_metadata_template(template_id: uuid.UUID, payload: MetadataTemplateUpdate, db: Session = Depends(get_db)):
    item = metadata_template_service.get(db, template_id)
    if item is None:
        raise _not_found("metadata template")
    return metadata_template_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.delete("/metadata-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metadata_template(template_id: uuid.UUID, db: Session = Depends(get_db)):
    item = metadata_template_service.get(db, template_id)
    if item is None:
        raise _not_found("metadata template")
    metadata_template_service.delete(db, item)


@router.get("/retention-policies", response_model=list[PolicyRuleRead])
def list_retention_policies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return retention_policy_service.list(db, skip=skip, limit=limit)


@router.post("/retention-policies", response_model=PolicyRuleRead, status_code=status.HTTP_201_CREATED)
def create_retention_policy(payload: PolicyRuleCreate, db: Session = Depends(get_db)):
    return retention_policy_service.create(db, payload.model_dump())


@router.get("/retention-policies/{policy_id}", response_model=PolicyRuleRead)
def get_retention_policy(policy_id: uuid.UUID, db: Session = Depends(get_db)):
    item = retention_policy_service.get(db, policy_id)
    if item is None:
        raise _not_found("retention policy")
    return item


@router.patch("/retention-policies/{policy_id}", response_model=PolicyRuleRead)
def update_retention_policy(policy_id: uuid.UUID, payload: PolicyRuleUpdate, db: Session = Depends(get_db)):
    item = retention_policy_service.get(db, policy_id)
    if item is None:
        raise _not_found("retention policy")
    return retention_policy_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.delete("/retention-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_retention_policy(policy_id: uuid.UUID, db: Session = Depends(get_db)):
    item = retention_policy_service.get(db, policy_id)
    if item is None:
        raise _not_found("retention policy")
    retention_policy_service.delete(db, item)


@router.get("/classification-rules", response_model=list[PolicyRuleRead])
def list_classification_rules(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return classification_rule_service.list(db, skip=skip, limit=limit)


@router.post("/classification-rules", response_model=PolicyRuleRead, status_code=status.HTTP_201_CREATED)
def create_classification_rule(payload: PolicyRuleCreate, db: Session = Depends(get_db)):
    return classification_rule_service.create(db, payload.model_dump())


@router.get("/classification-rules/{rule_id}", response_model=PolicyRuleRead)
def get_classification_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    item = classification_rule_service.get(db, rule_id)
    if item is None:
        raise _not_found("classification rule")
    return item


@router.patch("/classification-rules/{rule_id}", response_model=PolicyRuleRead)
def update_classification_rule(rule_id: uuid.UUID, payload: PolicyRuleUpdate, db: Session = Depends(get_db)):
    item = classification_rule_service.get(db, rule_id)
    if item is None:
        raise _not_found("classification rule")
    return classification_rule_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.delete("/classification-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_classification_rule(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    item = classification_rule_service.get(db, rule_id)
    if item is None:
        raise _not_found("classification rule")
    classification_rule_service.delete(db, item)


@router.get("/collections", response_model=list[CollectionRead])
def list_collections(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return collection_service.list(db, skip=skip, limit=limit)


@router.post("/collections", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)):
    return collection_service.create(db, payload.model_dump())


@router.get("/collections/{collection_id}", response_model=CollectionRead)
def get_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    item = collection_service.get(db, collection_id)
    if item is None:
        raise _not_found("collection")
    return item


@router.patch("/collections/{collection_id}", response_model=CollectionRead)
def update_collection(collection_id: uuid.UUID, payload: CollectionUpdate, db: Session = Depends(get_db)):
    item = collection_service.get(db, collection_id)
    if item is None:
        raise _not_found("collection")
    return collection_service.update(db, item, payload.model_dump(exclude_unset=True))


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    item = collection_service.get(db, collection_id)
    if item is None:
        raise _not_found("collection")
    collection_service.delete(db, item)


@router.post("/chunks/persist", response_model=ChunkPersistenceResponse, status_code=status.HTTP_201_CREATED)
def persist_chunks(payload: ChunkPersistenceRequest, db: Session = Depends(get_db)):
    document_version = db.get(DocumentVersion, payload.document_version_id)
    if document_version is None:
        raise _not_found("document version")
    if document_version.organization_id != payload.organization_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document version does not belong to organization"
        )

    document_record = db.get(DocumentRecord, document_version.document_record_id)
    if document_record is None:
        raise _not_found("document record")

    collection_id = payload.collection_id or document_record.collection_id
    chunks: list[Chunk] = []

    try:
        for item in payload.chunks:
            chunk = Chunk(
                organization_id=payload.organization_id,
                document_record_id=document_record.id,
                document_version_id=document_version.id,
                artifact_id=payload.artifact_id,
                collection_id=collection_id,
                chunk_index=item.chunk_index,
                chunk_key=item.chunk_key or _chunk_key(document_version.id, item.chunk_index),
                content_hash=item.content_hash or _content_hash(item.text),
                semantic_hash=item.semantic_hash,
                text=item.text,
                content_type=item.content_type,
                section_ref=item.section_ref,
                provenance={
                    **item.provenance,
                    "persistence_contract": "chunk_persistence_v1",
                    "source": "controlled_input",
                },
                quality=item.quality,
                metadata_json=item.metadata,
                status=item.status,
            )
            db.add(chunk)
            chunks.append(chunk)

        db.flush()
        for chunk in chunks:
            db.execute(
                sql_text(
                    "update documents.chunks "
                    "set fts_vector = to_tsvector('simple', coalesce(text, '')) "
                    "where id = :chunk_id"
                ),
                {"chunk_id": str(chunk.id)},
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="chunk persistence violates a database constraint"
        ) from exc
    except Exception:
        db.rollback()
        raise

    for chunk in chunks:
        db.refresh(chunk)

    return ChunkPersistenceResponse(
        organization_id=payload.organization_id,
        document_record_id=document_record.id,
        document_version_id=document_version.id,
        collection_id=collection_id,
        chunk_count=len(chunks),
        chunks=tuple(_read_chunk(chunk) for chunk in chunks),
        metrics={
            "status": "persisted",
            "chunk_count": len(chunks),
            "fts_vector_populated": True,
            "embedding_generated": False,
            "vector_indexed": False,
            "llm_used": False,
        },
    )


@router.get("/chunks", response_model=list[ChunkRead])
def list_chunks(
    organization_id: uuid.UUID,
    document_version_id: uuid.UUID | None = None,
    document_record_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Chunk).filter(Chunk.organization_id == organization_id)
    if document_version_id is not None:
        query = query.filter(Chunk.document_version_id == document_version_id)
    if document_record_id is not None:
        query = query.filter(Chunk.document_record_id == document_record_id)
    chunks = query.order_by(Chunk.created_at.desc(), Chunk.chunk_index.asc()).offset(skip).limit(limit).all()
    return [_read_chunk(chunk) for chunk in chunks]
