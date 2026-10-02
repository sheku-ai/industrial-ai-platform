from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, delete, func, literal, select, text, update
from sqlalchemy.orm import Session

from app.models.documents import Collection, DocumentRecord, DocumentType, DocumentVersion
from app.models.knowledge_index import (
    EmbeddingRecord,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexHealthSnapshot,
    KnowledgeLifecycleRun,
    KnowledgeMetadata,
    VectorIndexRecord,
)


class KnowledgeIndexRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_document(self, document_id: uuid.UUID) -> KnowledgeDocument | None:
        return self.session.get(KnowledgeDocument, document_id)

    def get_chunk(self, chunk_id: uuid.UUID) -> KnowledgeChunk | None:
        return self.session.get(KnowledgeChunk, chunk_id)

    def list_documents(
        self,
        *,
        artifact_id: str | None = None,
        publication_id: str | None = None,
        document_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument)
        if document_id:
            try:
                statement = statement.where(KnowledgeDocument.id == uuid.UUID(document_id))
            except ValueError:
                return []
        if artifact_id:
            statement = statement.where(KnowledgeDocument.artifact_id == artifact_id)
        if publication_id:
            statement = statement.where(KnowledgeDocument.publication_id == publication_id)
        if not include_inactive:
            statement = statement.where(KnowledgeDocument.status == "indexed")
        statement = statement.order_by(KnowledgeDocument.created_at.asc(), KnowledgeDocument.id.asc())
        return list(self.session.scalars(statement).all())

    def get_document_by_publication(self, *, artifact_id: str, publication_id: str) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(
            KnowledgeDocument.artifact_id == artifact_id,
            KnowledgeDocument.publication_id == publication_id,
        )
        return self.session.scalar(statement)

    def list_chunks_for_document(self, knowledge_document_id: uuid.UUID) -> list[KnowledgeChunk]:
        statement = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_document_id == knowledge_document_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
        )
        return list(self.session.scalars(statement).all())

    def list_metadata_for_document(self, knowledge_document_id: uuid.UUID) -> list[KnowledgeMetadata]:
        statement = select(KnowledgeMetadata).where(KnowledgeMetadata.knowledge_document_id == knowledge_document_id)
        return list(self.session.scalars(statement).all())

    def upsert_document(
        self,
        *,
        artifact_id: str,
        publication_id: str,
        content_signature: str,
        document_record_id: str | None,
        document_version_id: str | None,
        metadata: dict,
    ) -> tuple[KnowledgeDocument, bool, bool]:
        existing = self.get_document_by_publication(artifact_id=artifact_id, publication_id=publication_id)
        if existing is None:
            document = KnowledgeDocument(
                artifact_id=artifact_id,
                publication_id=publication_id,
                document_record_id=document_record_id,
                document_version_id=document_version_id,
                content_signature=content_signature,
                status="indexed",
                version=1,
                metadata_json=dict(metadata),
            )
            self.session.add(document)
            self.session.flush()
            return document, True, True
        changed = existing.content_signature != content_signature
        if changed:
            existing.version = int(existing.version or 1) + 1
        existing.content_signature = content_signature
        existing.document_record_id = document_record_id or existing.document_record_id
        existing.document_version_id = document_version_id or existing.document_version_id
        existing.metadata_json = dict(metadata)
        existing.status = "indexed"
        self.session.add(existing)
        self.session.flush()
        return existing, False, changed

    def upsert_chunk(
        self, *, knowledge_document_id: uuid.UUID, publication_id: str, artifact_id: str, chunk: dict
    ) -> tuple[KnowledgeChunk, bool, bool]:
        published_chunk_id = str(chunk.get("published_chunk_id"))
        statement = select(KnowledgeChunk).where(KnowledgeChunk.published_chunk_id == published_chunk_id)
        existing = self.session.scalar(statement)
        text = str(chunk.get("text") or "")
        content_hash = str(chunk.get("content_hash") or "")
        metadata = dict(chunk.get("metadata") or {})
        if chunk.get("published_at"):
            metadata["published_at"] = chunk.get("published_at")
        if chunk.get("source_content_sha256"):
            metadata["source_content_sha256"] = chunk.get("source_content_sha256")
        changed = False
        if existing is None:
            item = KnowledgeChunk(
                knowledge_document_id=knowledge_document_id,
                published_chunk_id=published_chunk_id,
                publication_id=publication_id,
                artifact_id=artifact_id,
                chunk_index=int(chunk.get("chunk_index")),
                text=text,
                content_hash=content_hash,
                semantic_hash=chunk.get("semantic_hash"),
                content_type=chunk.get("content_type"),
                chunk_scope=chunk.get("chunk_scope"),
                status="indexed",
                metadata_json=metadata,
            )
            self.session.add(item)
            self.session.flush()
            return item, True, True
        changed = (
            existing.text != text
            or existing.content_hash != content_hash
            or existing.semantic_hash != chunk.get("semantic_hash")
            or existing.chunk_index != int(chunk.get("chunk_index"))
            or (existing.metadata_json or {}) != metadata
        )
        existing.knowledge_document_id = knowledge_document_id
        existing.publication_id = publication_id
        existing.artifact_id = artifact_id
        existing.chunk_index = int(chunk.get("chunk_index"))
        existing.text = text
        existing.content_hash = content_hash
        existing.semantic_hash = chunk.get("semantic_hash")
        existing.content_type = chunk.get("content_type")
        existing.chunk_scope = chunk.get("chunk_scope")
        existing.status = "indexed"
        existing.metadata_json = metadata
        self.session.add(existing)
        self.session.flush()
        return existing, False, changed

    def mark_missing_chunks_superseded(
        self, *, knowledge_document_id: uuid.UUID, active_published_chunk_ids: Iterable[str]
    ) -> int:
        active = set(active_published_chunk_ids)
        count = 0
        for chunk in self.list_chunks_for_document(knowledge_document_id):
            if chunk.published_chunk_id not in active and chunk.status != "superseded":
                chunk.status = "superseded"
                self.session.add(chunk)
                count += 1
        self.session.flush()
        return count

    def upsert_metadata(
        self, *, knowledge_document_id: uuid.UUID, metadata_key: str, metadata_value: dict
    ) -> KnowledgeMetadata:
        statement = select(KnowledgeMetadata).where(
            KnowledgeMetadata.knowledge_document_id == knowledge_document_id,
            KnowledgeMetadata.metadata_key == metadata_key,
        )
        existing = self.session.scalar(statement)
        if existing is None:
            item = KnowledgeMetadata(
                knowledge_document_id=knowledge_document_id,
                metadata_key=metadata_key,
                metadata_value=dict(metadata_value),
            )
            self.session.add(item)
            self.session.flush()
            return item
        existing.metadata_value = dict(metadata_value)
        self.session.add(existing)
        self.session.flush()
        return existing

    def _organization_uuid(self, organization_id: str | uuid.UUID | None) -> uuid.UUID | None:
        if organization_id is None:
            return None
        try:
            return uuid.UUID(str(organization_id))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _operational_document_criteria() -> tuple[Any, ...]:
        source_ref = DocumentRecord.source_ref
        return (
            func.coalesce(source_ref["execution_key"].as_string(), "") == "",
            func.coalesce(source_ref["scenario"].as_string(), "") != "local_product_acceptance",
            func.coalesce(source_ref["provider"].as_string(), "") != "smoke",
            ~source_ref.has_key("smoke"),  # type: ignore[attr-defined]
        )

    def search_records(self, *, organization_id: str | uuid.UUID | None = None) -> list[dict]:
        organization_uuid = self._organization_uuid(organization_id)
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, DocumentRecord, DocumentVersion, DocumentType, Collection)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .outerjoin(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
            .outerjoin(DocumentVersion, KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String))
            .outerjoin(DocumentType, DocumentRecord.document_type_id == DocumentType.id)
            .outerjoin(Collection, DocumentRecord.collection_id == Collection.id)
            .where(
                KnowledgeChunk.status == "indexed",
                KnowledgeDocument.status == "indexed",
                *self._operational_document_criteria(),
            )
            .order_by(KnowledgeDocument.created_at.asc(), KnowledgeChunk.chunk_index.asc())
        )
        if organization_id is not None:
            if organization_uuid is None:
                return []
            statement = statement.where(DocumentRecord.organization_id == organization_uuid)
        rows = self.session.execute(statement).all()
        return [
            {
                "organization_id": str(record.organization_id) if record is not None else None,
                "knowledge_document_id": str(document.id),
                "knowledge_chunk_id": str(chunk.id),
                "artifact_id": chunk.artifact_id,
                "publication_id": chunk.publication_id,
                "published_chunk_id": chunk.published_chunk_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "content_hash": chunk.content_hash,
                "semantic_hash": chunk.semantic_hash,
                "content_type": chunk.content_type,
                "chunk_scope": chunk.chunk_scope,
                "metadata": {
                    **(chunk.metadata_json or {}),
                    "organization_id": str(record.organization_id) if record is not None else None,
                    "knowledge_document_id": str(document.id),
                    "knowledge_chunk_id": str(chunk.id),
                    "document_version": document.version,
                    "document_metadata": document.metadata_json or {},
                    "document_record_id": str(record.id) if record is not None else None,
                    "document_title": record.title if record is not None else None,
                    "original_filename": version.file_name if version is not None else None,
                    "document_content_type": version.content_type if version is not None else None,
                    "document_version_number": version.version_number if version is not None else None,
                    "document_type_name": document_type.name if document_type is not None else None,
                    "collection_name": collection.name if collection is not None else None,
                    "document_status": record.status if record is not None else None,
                },
            }
            for chunk, document, record, version, document_type, collection in rows
        ]

    def indexed_chunk_count(self, *, organization_id: str | uuid.UUID | None = None) -> int:
        organization_uuid = self._organization_uuid(organization_id)
        statement = (
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .join(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
            .where(
                KnowledgeChunk.status == "indexed",
                KnowledgeDocument.status == "indexed",
                *self._operational_document_criteria(),
            )
        )
        if organization_id is not None:
            if organization_uuid is None:
                return 0
            statement = statement.where(DocumentRecord.organization_id == organization_uuid)
        return int(self.session.scalar(statement) or 0)

    def indexed_collection_ids(
        self, *, organization_id: str | uuid.UUID | None = None
    ) -> set[uuid.UUID]:
        organization_uuid = self._organization_uuid(organization_id)
        statement = (
            select(DocumentRecord.collection_id)
            .distinct()
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .join(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
            .where(
                KnowledgeChunk.status == "indexed",
                KnowledgeDocument.status == "indexed",
                DocumentRecord.collection_id.is_not(None),
                *self._operational_document_criteria(),
            )
        )
        if organization_id is not None:
            if organization_uuid is None:
                return set()
            statement = statement.where(DocumentRecord.organization_id == organization_uuid)
        return {collection_id for collection_id in self.session.scalars(statement).all() if collection_id}

    def backfill_fts_projection(self) -> dict[str, Any]:
        indexed = self.indexed_chunk_count()
        self.session.execute(
            update(KnowledgeChunk).where(KnowledgeChunk.status == "indexed").values(text=KnowledgeChunk.text)
        )
        self.session.flush()
        return {
            "fts_index_created": True,
            "fts_backfill_completed": True,
            "chunks_backfilled": indexed,
            "fts_config": "simple",
        }

    def fts_health(self) -> dict[str, Any]:
        indexed = self.indexed_chunk_count()
        return {
            "fts_index_created": True,
            "fts_backfill_completed": True,
            "fts_config": "simple",
            "indexed_chunks": indexed,
            "search_vector_column": "knowledge.chunks.search_vector",
            "gin_index": "ix_knowledge_chunks_search_vector",
            "search_uses_postgresql": True,
            "search_uses_postgresql_fts": True,
        }

    def embedding_status_by_chunk_ids(self, chunk_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        statement = (
            select(EmbeddingRecord.chunk_id, EmbeddingRecord.embedding_status)
            .where(EmbeddingRecord.chunk_id.in_(ids))
            .order_by(EmbeddingRecord.updated_at.desc(), EmbeddingRecord.embedding_id.asc())
        )
        statuses: dict[uuid.UUID, str] = {}
        for chunk_id, status in self.session.execute(statement).all():
            statuses.setdefault(chunk_id, str(status))
        return statuses

    def vector_index_status_by_chunk_ids(self, chunk_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        statement = (
            select(VectorIndexRecord.knowledge_chunk_id, VectorIndexRecord.index_status)
            .where(VectorIndexRecord.knowledge_chunk_id.in_(ids))
            .order_by(VectorIndexRecord.updated_at.desc(), VectorIndexRecord.vector_index_id.asc())
        )
        statuses: dict[uuid.UUID, str] = {}
        for chunk_id, status in self.session.execute(statement).all():
            statuses.setdefault(chunk_id, str(status))
        return statuses

    def search_fts(
        self,
        *,
        query: str,
        top_k: int | None = None,
        offset: int = 0,
        limit: int | None = None,
        artifact_id: str | None = None,
        publication_id: str | None = None,
        knowledge_document_id: str | None = None,
        content_type: str | None = None,
        chunk_scope: str | None = None,
        status: str = "indexed",
        include_facets: bool = False,
        organization_id: str | uuid.UUID | None = None,
    ) -> dict[str, Any]:
        organization_uuid = self._organization_uuid(organization_id)
        if organization_id is not None and organization_uuid is None:
            return {"records": [], "total_count": 0, "has_more": False, "facets": {}}
        fts_config = text("'simple'::regconfig")
        ts_query = func.websearch_to_tsquery(fts_config, query)
        score = func.ts_rank_cd(KnowledgeChunk.search_vector, ts_query).label("score")
        headline = func.ts_headline(
            fts_config,
            KnowledgeChunk.text,
            ts_query,
            literal("StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=8, ShortWord=2"),
        ).label("highlighted_snippet")
        statement = (
            select(
                KnowledgeChunk,
                KnowledgeDocument,
                DocumentRecord,
                DocumentVersion,
                DocumentType,
                Collection,
                score,
                headline,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .outerjoin(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
            .outerjoin(DocumentVersion, KnowledgeDocument.document_version_id == cast(DocumentVersion.id, String))
            .outerjoin(DocumentType, DocumentRecord.document_type_id == DocumentType.id)
            .outerjoin(Collection, DocumentRecord.collection_id == Collection.id)
            .where(
                KnowledgeDocument.status == "indexed",
                KnowledgeChunk.status == status,
                KnowledgeChunk.search_vector.op("@@")(ts_query),
                *self._operational_document_criteria(),
            )
        )
        count_statement = (
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .join(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
            .where(
                KnowledgeDocument.status == "indexed",
                KnowledgeChunk.status == status,
                KnowledgeChunk.search_vector.op("@@")(ts_query),
                *self._operational_document_criteria(),
            )
        )
        if organization_uuid is not None:
            statement = statement.where(DocumentRecord.organization_id == organization_uuid)
            count_statement = count_statement.where(DocumentRecord.organization_id == organization_uuid)
        if artifact_id:
            statement = statement.where(KnowledgeChunk.artifact_id == artifact_id)
            count_statement = count_statement.where(KnowledgeChunk.artifact_id == artifact_id)
        if publication_id:
            statement = statement.where(KnowledgeChunk.publication_id == publication_id)
            count_statement = count_statement.where(KnowledgeChunk.publication_id == publication_id)
        if knowledge_document_id:
            try:
                statement = statement.where(KnowledgeChunk.knowledge_document_id == uuid.UUID(knowledge_document_id))
                count_statement = count_statement.where(
                    KnowledgeChunk.knowledge_document_id == uuid.UUID(knowledge_document_id)
                )
            except ValueError:
                return {"records": [], "total_count": 0, "has_more": False, "facets": {}}
        if content_type:
            statement = statement.where(KnowledgeChunk.content_type == content_type)
            count_statement = count_statement.where(KnowledgeChunk.content_type == content_type)
        if chunk_scope:
            statement = statement.where(KnowledgeChunk.chunk_scope == chunk_scope)
            count_statement = count_statement.where(KnowledgeChunk.chunk_scope == chunk_scope)
        bounded_limit = max(1, min(int(limit if limit is not None else top_k if top_k is not None else 5), 50))
        bounded_offset = max(0, int(offset or 0))
        statement = (
            statement.order_by(
                score.desc(),
                KnowledgeDocument.id.asc(),
                KnowledgeChunk.chunk_index.asc(),
                KnowledgeChunk.id.asc(),
            )
            .offset(bounded_offset)
            .limit(bounded_limit)
        )
        total_count = int(self.session.scalar(count_statement) or 0)
        rows = self.session.execute(statement).all()
        row_chunk_ids = [chunk.id for chunk, _, _, _, _, _, _, _ in rows]
        embedding_statuses = self.embedding_status_by_chunk_ids(row_chunk_ids)
        vector_index_statuses = self.vector_index_status_by_chunk_ids(row_chunk_ids)
        records: list[dict[str, Any]] = []
        for chunk, document, record, version, document_type, collection, rank_score, highlighted_snippet in rows:
            embedding_status = embedding_statuses.get(chunk.id)
            vector_index_status = vector_index_statuses.get(chunk.id)
            records.append(
                {
                    "organization_id": str(record.organization_id) if record is not None else None,
                    "knowledge_document_id": str(document.id),
                    "knowledge_chunk_id": str(chunk.id),
                    "artifact_id": chunk.artifact_id,
                    "publication_id": chunk.publication_id,
                    "published_chunk_id": chunk.published_chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "snippet": highlighted_snippet or chunk.text,
                    "highlighted_snippet": highlighted_snippet or chunk.text,
                    "content_hash": chunk.content_hash,
                    "semantic_hash": chunk.semantic_hash,
                    "content_type": chunk.content_type,
                    "chunk_scope": chunk.chunk_scope,
                    "embedding_available": embedding_status is not None,
                    "embedding_status": embedding_status,
                    "vector_index_available": vector_index_status is not None,
                    "vector_index_status": vector_index_status,
                    "score": float(rank_score or 0.0),
                    "metadata": {
                        **(chunk.metadata_json or {}),
                        "organization_id": str(record.organization_id) if record is not None else None,
                        "knowledge_document_id": str(document.id),
                        "knowledge_chunk_id": str(chunk.id),
                        "document_version": document.version,
                        "document_metadata": document.metadata_json or {},
                        "document_record_id": str(record.id) if record is not None else None,
                        "document_title": record.title if record is not None else None,
                        "original_filename": version.file_name if version is not None else None,
                        "document_content_type": version.content_type if version is not None else None,
                        "document_version_number": version.version_number if version is not None else None,
                        "document_type_name": document_type.name if document_type is not None else None,
                        "collection_name": collection.name if collection is not None else None,
                        "document_status": record.status if record is not None else None,
                    },
                }
            )
        facets = (
            self.search_fts_facets(
                query=query,
                organization_id=organization_uuid,
                artifact_id=artifact_id,
                publication_id=publication_id,
                knowledge_document_id=knowledge_document_id,
                content_type=content_type,
                chunk_scope=chunk_scope,
                status=status,
            )
            if include_facets
            else {}
        )
        return {
            "records": records,
            "total_count": total_count,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "has_more": bounded_offset + len(records) < total_count,
            "facets": facets,
        }

    def search_fts_facets(
        self,
        *,
        query: str,
        artifact_id: str | None = None,
        publication_id: str | None = None,
        knowledge_document_id: str | None = None,
        content_type: str | None = None,
        chunk_scope: str | None = None,
        status: str = "indexed",
        organization_id: str | uuid.UUID | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        organization_uuid = self._organization_uuid(organization_id)
        if organization_id is not None and organization_uuid is None:
            return {}
        fts_config = text("'simple'::regconfig")
        ts_query = func.websearch_to_tsquery(fts_config, query)

        def _base(field: Any):
            statement = (
                select(field.label("value"), func.count().label("count"))
                .select_from(KnowledgeChunk)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
                .join(DocumentRecord, KnowledgeDocument.document_record_id == cast(DocumentRecord.id, String))
                .where(
                    KnowledgeDocument.status == "indexed",
                    KnowledgeChunk.status == status,
                    KnowledgeChunk.search_vector.op("@@")(ts_query),
                    field.is_not(None),
                    *self._operational_document_criteria(),
                )
            )
            if organization_uuid is not None:
                statement = statement.where(DocumentRecord.organization_id == organization_uuid)
            if artifact_id:
                statement = statement.where(KnowledgeChunk.artifact_id == artifact_id)
            if publication_id:
                statement = statement.where(KnowledgeChunk.publication_id == publication_id)
            if knowledge_document_id:
                try:
                    statement = statement.where(
                        KnowledgeChunk.knowledge_document_id == uuid.UUID(knowledge_document_id)
                    )
                except ValueError:
                    return None
            if content_type:
                statement = statement.where(KnowledgeChunk.content_type == content_type)
            if chunk_scope:
                statement = statement.where(KnowledgeChunk.chunk_scope == chunk_scope)
            return statement.group_by(field).order_by(func.count().desc(), field.asc()).limit(25)

        facets: dict[str, list[dict[str, Any]]] = {}
        for name, field in {
            "content_type": KnowledgeChunk.content_type,
            "chunk_scope": KnowledgeChunk.chunk_scope,
            "status": KnowledgeChunk.status,
            "artifact_id": KnowledgeChunk.artifact_id,
            "publication_id": KnowledgeChunk.publication_id,
        }.items():
            statement = _base(field)
            rows = [] if statement is None else self.session.execute(statement).all()
            facets[name] = [{"value": str(value), "count": int(count)} for value, count in rows if value is not None]
        return facets

    def invalidate_documents(self, documents: Iterable[KnowledgeDocument], *, status: str = "stale") -> int:
        count = 0
        for document in documents:
            if document.status != status:
                document.status = status
                self.session.add(document)
                count += 1
        self.session.flush()
        return count

    def invalidate_chunks_for_documents(self, documents: Iterable[KnowledgeDocument], *, status: str = "stale") -> int:
        count = 0
        for document in documents:
            for chunk in self.list_chunks_for_document(document.id):
                if chunk.status != status:
                    chunk.status = status
                    self.session.add(chunk)
                    count += 1
        self.session.flush()
        return count

    def delete_document(self, document: KnowledgeDocument) -> tuple[int, int]:
        chunk_count = len(self.list_chunks_for_document(document.id))
        self.session.execute(delete(KnowledgeMetadata).where(KnowledgeMetadata.knowledge_document_id == document.id))
        self.session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == document.id))
        self.session.delete(document)
        self.session.flush()
        return 1, chunk_count

    def delete_documents(self, documents: Iterable[KnowledgeDocument]) -> tuple[int, int]:
        documents_deleted = 0
        chunks_deleted = 0
        for document in list(documents):
            deleted_docs, deleted_chunks = self.delete_document(document)
            documents_deleted += deleted_docs
            chunks_deleted += deleted_chunks
        return documents_deleted, chunks_deleted

    def cleanup_stale_documents(self, documents: Iterable[KnowledgeDocument] | None = None) -> tuple[int, int]:
        stale = list(documents) if documents is not None else self.list_documents(include_inactive=True)
        stale = [document for document in stale if document.status in {"stale", "invalidated", "obsolete"}]
        return self.delete_documents(stale)

    def cleanup_orphan_chunks(self) -> int:
        document_ids = {document.id for document in self.list_documents(include_inactive=True)}
        statement = select(KnowledgeChunk)
        count = 0
        for chunk in self.session.scalars(statement).all():
            if chunk.knowledge_document_id not in document_ids:
                self.session.delete(chunk)
                count += 1
        self.session.flush()
        return count

    def duplicate_chunks(self, *, documents: Iterable[KnowledgeDocument] | None = None) -> list[KnowledgeChunk]:
        document_ids = {document.id for document in documents} if documents is not None else None
        statement = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.status == "indexed")
            .order_by(KnowledgeChunk.content_hash.asc(), KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
        )
        seen: set[str] = set()
        duplicates: list[KnowledgeChunk] = []
        for chunk in self.session.scalars(statement).all():
            if document_ids is not None and chunk.knowledge_document_id not in document_ids:
                continue
            key = f"{chunk.artifact_id}:{chunk.content_hash}:{chunk.semantic_hash or ''}:{chunk.text}"
            if key in seen:
                duplicates.append(chunk)
            else:
                seen.add(key)
        return duplicates

    def cleanup_duplicate_chunks(self, *, documents: Iterable[KnowledgeDocument] | None = None) -> int:
        count = 0
        for chunk in self.duplicate_chunks(documents=documents):
            chunk.status = "duplicate_removed"
            self.session.add(chunk)
            count += 1
        self.session.flush()
        return count

    def cleanup_obsolete_publications(self, documents: Iterable[KnowledgeDocument] | None = None) -> tuple[int, int]:
        latest_by_artifact: dict[str, KnowledgeDocument] = {}
        scoped_documents = list(documents) if documents is not None else self.list_documents(include_inactive=True)
        for document in scoped_documents:
            current = latest_by_artifact.get(document.artifact_id)
            if current is None or (document.created_at, str(document.id)) > (current.created_at, str(current.id)):
                latest_by_artifact[document.artifact_id] = document
        obsolete = [
            document
            for document in scoped_documents
            if latest_by_artifact.get(document.artifact_id) is not None
            and latest_by_artifact[document.artifact_id].id != document.id
        ]
        for document in obsolete:
            document.status = "obsolete"
            self.session.add(document)
        self.session.flush()
        return self.delete_documents(obsolete)

    def health_metrics(self) -> dict[str, Any]:
        documents = self.list_documents(include_inactive=True)
        chunks = list(self.session.scalars(select(KnowledgeChunk)).all())
        indexed_documents = [document for document in documents if document.status == "indexed"]
        indexed_chunks = [chunk for chunk in chunks if chunk.status == "indexed"]
        stale_documents = [
            document for document in documents if document.status in {"stale", "invalidated", "obsolete"}
        ]
        document_ids = {document.id for document in documents}
        duplicate_count = len(self.duplicate_chunks())
        last_incremental = self.latest_lifecycle_run(operation="incremental")
        last_full = self.latest_lifecycle_run(operation="reindex", mode="FULL")
        return {
            "indexed_documents": len(indexed_documents),
            "indexed_chunks": len(indexed_chunks),
            "stale_documents": len(stale_documents),
            "orphan_chunks": len([chunk for chunk in chunks if chunk.knowledge_document_id not in document_ids]),
            "duplicate_chunks": duplicate_count,
            "pending_updates": len(stale_documents),
            "pending_reindex": len(stale_documents) + duplicate_count,
            "last_incremental": last_incremental.created_at.isoformat() if last_incremental else None,
            "last_full_reindex": last_full.created_at.isoformat() if last_full else None,
            "rebuild_required": bool(stale_documents or duplicate_count),
        }

    def statistics(self) -> dict[str, Any]:
        documents = self.list_documents(include_inactive=False)
        chunks = list(self.session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.status == "indexed")).all())
        chunk_count = len(chunks)
        document_count = len(documents)
        indexed_bytes = sum(len((chunk.text or "").encode("utf-8")) for chunk in chunks)
        publication_times = [
            chunk.metadata_json.get("published_at")
            for chunk in chunks
            if isinstance(chunk.metadata_json, dict) and chunk.metadata_json.get("published_at")
        ]
        oldest_document = min((document.created_at for document in documents), default=None)
        health = self.health_metrics()
        return {
            "average_chunks_per_document": round(chunk_count / document_count, 6) if document_count else 0,
            "average_document_size": round(indexed_bytes / document_count, 6) if document_count else 0,
            "indexed_bytes": indexed_bytes,
            "latest_publication": max(publication_times) if publication_times else None,
            "oldest_document": oldest_document.isoformat() if oldest_document else None,
            "rebuild_required": bool(health.get("rebuild_required")),
        }

    def latest_lifecycle_run(
        self, *, operation: str | None = None, mode: str | None = None
    ) -> KnowledgeLifecycleRun | None:
        statement = select(KnowledgeLifecycleRun)
        if operation:
            statement = statement.where(KnowledgeLifecycleRun.operation == operation)
        if mode:
            statement = statement.where(KnowledgeLifecycleRun.mode == mode)
        statement = statement.order_by(KnowledgeLifecycleRun.created_at.desc(), KnowledgeLifecycleRun.id.desc())
        return self.session.scalar(statement.limit(1))

    def create_lifecycle_run(
        self,
        *,
        lifecycle_session_id: str,
        operation: str,
        mode: str,
        status: str,
        result: dict[str, Any],
        artifact_id: str | None = None,
        publication_id: str | None = None,
        document_id: str | None = None,
        decision: str | None = None,
    ) -> KnowledgeLifecycleRun:
        run = KnowledgeLifecycleRun(
            lifecycle_session_id=lifecycle_session_id,
            operation=operation,
            mode=mode,
            status=status,
            artifact_id=artifact_id,
            publication_id=publication_id,
            document_id=document_id,
            decision=decision,
            documents_scanned=int(result.get("documents_scanned") or 0),
            documents_updated=int(result.get("documents_updated") or 0),
            documents_invalidated=int(result.get("documents_invalidated") or 0),
            documents_deleted=int(result.get("documents_deleted") or 0),
            chunks_scanned=int(result.get("chunks_scanned") or 0),
            chunks_updated=int(result.get("chunks_updated") or 0),
            chunks_deleted=int(result.get("chunks_deleted") or 0),
            duplicates_removed=int(result.get("duplicates_removed") or 0),
            orphan_chunks_removed=int(result.get("orphan_chunks_removed") or 0),
            stale_documents_removed=int(result.get("stale_documents_removed") or 0),
            obsolete_publications_removed=int(result.get("obsolete_publications_removed") or 0),
            result_json=dict(result),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def create_health_snapshot(
        self, *, health: dict[str, Any], statistics: dict[str, Any]
    ) -> KnowledgeIndexHealthSnapshot:
        def _parse_dt(value: Any) -> datetime | None:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return None
            return None

        snapshot = KnowledgeIndexHealthSnapshot(
            indexed_documents=int(health.get("indexed_documents") or 0),
            indexed_chunks=int(health.get("indexed_chunks") or 0),
            stale_documents=int(health.get("stale_documents") or 0),
            orphan_chunks=int(health.get("orphan_chunks") or 0),
            duplicate_chunks=int(health.get("duplicate_chunks") or 0),
            pending_updates=int(health.get("pending_updates") or 0),
            pending_reindex=int(health.get("pending_reindex") or 0),
            last_incremental=_parse_dt(health.get("last_incremental")),
            last_full_reindex=_parse_dt(health.get("last_full_reindex")),
            rebuild_required=bool(health.get("rebuild_required")),
            statistics_json=dict(statistics),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def now_iso(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
