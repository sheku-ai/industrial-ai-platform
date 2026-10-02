from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.models.documents import Chunk
from app.services.visual_knowledge_records import VisualKnowledgeRecord


@dataclass(frozen=True)
class VisualChunkMaterializationResult:
    created: int = 0
    existing: int = 0


class VisualKnowledgeChunkMaterializer:
    """Materializes derived visual records into PostgreSQL lexical retrieval."""

    def materialize(
        self,
        session,
        *,
        organization_id: uuid.UUID,
        document_version_id: uuid.UUID,
        processing_revision_id: uuid.UUID | None,
        text_chunks: Sequence[Chunk],
        visual_records: Sequence[VisualKnowledgeRecord],
    ) -> VisualChunkMaterializationResult:
        if not visual_records or not text_chunks:
            return VisualChunkMaterializationResult()

        self._acquire_document_version_lock(
            session,
            organization_id=organization_id,
            document_version_id=document_version_id,
        )

        first = text_chunks[0]
        max_index = session.scalar(
            select(func.max(Chunk.chunk_index)).where(
                Chunk.organization_id == organization_id,
                Chunk.document_version_id == document_version_id,
            )
        )
        next_index = (int(max_index) if max_index is not None else -1) + 1
        created = 0
        existing = 0

        for record in visual_records:
            metadata = dict(record.metadata)
            image_hash = str(metadata.get("image_hash") or "").strip()
            if not image_hash:
                continue

            inserted = self._insert_if_missing(
                session,
                organization_id=organization_id,
                document_version_id=document_version_id,
                processing_revision_id=processing_revision_id,
                first=first,
                chunk_index=next_index,
                chunk_key=f"visual:{image_hash}",
                content=record.content,
                metadata=metadata,
            )
            if inserted:
                created += 1
                next_index += 1
            else:
                existing += 1

        session.flush()
        return VisualChunkMaterializationResult(created=created, existing=existing)

    @staticmethod
    def _insert_if_missing(
        session,
        *,
        organization_id: uuid.UUID,
        document_version_id: uuid.UUID,
        processing_revision_id: uuid.UUID | None,
        first: Chunk,
        chunk_index: int,
        chunk_key: str,
        content: str,
        metadata: dict,
    ) -> bool:
        get_bind = getattr(session, "get_bind", None)
        bind = get_bind() if get_bind is not None else None
        is_postgresql = bind is not None and bind.dialect.name == "postgresql"

        if not is_postgresql:
            conditions = [
                Chunk.organization_id == organization_id,
                Chunk.document_version_id == document_version_id,
                Chunk.chunk_key == chunk_key,
            ]
            if processing_revision_id is None:
                conditions.append(Chunk.processing_revision_id.is_(None))
            else:
                conditions.append(Chunk.processing_revision_id == processing_revision_id)
            if session.scalar(select(Chunk).where(*conditions)) is not None:
                return False
            session.add(
                Chunk(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    document_record_id=first.document_record_id,
                    document_version_id=document_version_id,
                    processing_revision_id=processing_revision_id,
                    artifact_id=None,
                    collection_id=first.collection_id,
                    chunk_index=chunk_index,
                    chunk_key=chunk_key,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    semantic_hash=None,
                    text=content,
                    content_type="text/plain",
                    section_ref=dict(metadata.get("source_locator") or {}),
                    provenance=dict(metadata.get("source_locator") or {}),
                    quality={
                        "derived_content": True,
                        "visual_status": metadata.get("visual_status"),
                        "confidence": metadata.get("confidence"),
                    },
                    metadata_json=metadata,
                    status="indexed",
                )
            )
            return True

        values = {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "document_record_id": first.document_record_id,
            "document_version_id": document_version_id,
            "processing_revision_id": processing_revision_id,
            "artifact_id": None,
            "collection_id": first.collection_id,
            "chunk_index": chunk_index,
            "chunk_key": chunk_key,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "semantic_hash": None,
            "text": content,
            "content_type": "text/plain",
            "section_ref": dict(metadata.get("source_locator") or {}),
            "provenance": dict(metadata.get("source_locator") or {}),
            "quality": {
                "derived_content": True,
                "visual_status": metadata.get("visual_status"),
                "confidence": metadata.get("confidence"),
            },
            "metadata": metadata,
            "status": "indexed",
        }
        statement = postgresql_insert(Chunk.__table__).values(values)
        if processing_revision_id is None:
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    Chunk.__table__.c.organization_id,
                    Chunk.__table__.c.document_version_id,
                    Chunk.__table__.c.chunk_key,
                ],
                index_where=Chunk.__table__.c.processing_revision_id.is_(None),
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    Chunk.__table__.c.organization_id,
                    Chunk.__table__.c.processing_revision_id,
                    Chunk.__table__.c.chunk_key,
                ],
                index_where=Chunk.__table__.c.processing_revision_id.is_not(None),
            )
        inserted_id = session.execute(statement.returning(Chunk.__table__.c.id)).scalar_one_or_none()
        return inserted_id is not None

    @staticmethod
    def _acquire_document_version_lock(
        session,
        *,
        organization_id: uuid.UUID,
        document_version_id: uuid.UUID,
    ) -> None:
        """Serialize chunk-index allocation for one document version in PostgreSQL."""

        get_bind = getattr(session, "get_bind", None)
        if get_bind is None:
            return
        bind = get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return

        lock_scope = f"visual-chunks:{organization_id}:{document_version_id}"
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_scope, 0))"),
            {"lock_scope": lock_scope},
        )
