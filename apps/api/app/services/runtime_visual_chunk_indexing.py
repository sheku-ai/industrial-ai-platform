from __future__ import annotations

from collections import Counter
from time import perf_counter

from sqlalchemy import select

from app.models.documents import Chunk
from app.services.visual_knowledge_chunk_materializer import VisualKnowledgeChunkMaterializer


class RuntimeVisualChunkIndexingService:
    def __init__(self, session_factory, visual_source):
        self.session_factory = session_factory
        self.visual_source = visual_source

    def run(self, *, organization_id, execution_id, document_version_id, processing_revision_id):
        started_at = perf_counter()
        session = self.session_factory()
        try:
            chunks = tuple(
                session.scalars(
                    select(Chunk)
                    .where(
                        Chunk.organization_id == organization_id,
                        Chunk.document_version_id == document_version_id,
                    )
                    .order_by(Chunk.chunk_index.asc())
                ).all()
            )
            text_chunks = tuple(
                chunk for chunk in chunks if (chunk.metadata_json or {}).get("content_modality") != "visual_description"
            )
            visual_records = self.visual_source.load(
                session,
                organization_id=organization_id,
                execution_id=execution_id,
            )
            result = VisualKnowledgeChunkMaterializer().materialize(
                session,
                organization_id=organization_id,
                document_version_id=document_version_id,
                processing_revision_id=processing_revision_id,
                text_chunks=text_chunks,
                visual_records=visual_records,
            )
            provider_counts = Counter(
                str((record.metadata or {}).get("provider_key") or "unconfigured") for record in visual_records
            )
            status_counts = Counter(
                str((record.metadata or {}).get("visual_status") or "unknown") for record in visual_records
            )
            session.commit()
            return {
                "visual_chunk_indexing_connected": True,
                "visual_chunk_indexing_failed": False,
                "visual_chunks_created": result.created,
                "visual_chunks_existing": result.existing,
                "visual_chunks_requested": len(visual_records),
                "visual_text_chunks_available": len(text_chunks),
                "visual_chunk_indexing_duration_ms": _elapsed_ms(started_at),
                "visual_chunk_provider_counts": dict(sorted(provider_counts.items())),
                "visual_chunk_status_counts": dict(sorted(status_counts.items())),
                "multimodal_processing_revision_id": (str(processing_revision_id) if processing_revision_id else None),
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
