from __future__ import annotations

import boto3

from app.core.config import get_settings
from app.repositories.ingestion_profiles import SqlAlchemyIngestionProfileRepository
from app.repositories.runtime_ingestion import RuntimeDocumentContentRepository, RuntimeLexicalIndexRepository
from app.services.cached_visual_enrichment_producer import CachedVisualEnrichmentProducer
from app.services.document_content_persistence import DocumentContentPersistenceService
from app.services.document_ingestion_runtime_adapter import DocumentIngestionRuntimeAdapter
from app.services.document_ingestion_status import DocumentIngestionStatusAdapter, DocumentVersionStatusService
from app.services.ingestion_adapter_resolver import IngestionAdapterResolver
from app.services.ingestion_adapters.segmented_pdf import SegmentedPdfIngestionAdapter
from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
from app.services.ingestion_configuration import IngestionConfigurationService
from app.services.ingestion_post_processing import IngestionPostProcessingService
from app.services.knowledge_artifact_runtime_adapter import KnowledgeArtifactRuntimeAdapter
from app.services.lexical_indexing import LexicalIndexService
from app.services.ocr_transient_ingestion_pipeline import OcrTransientOptionIngestionPipelineCoordinator
from app.services.processing_manifest_publication import ProcessingManifestPublicationService
from app.services.processing_revision_runtime import ProcessingRevisionRuntime
from app.services.runtime_knowledge_artifact_publication import RuntimeKnowledgeArtifactPublicationService
from app.services.runtime_visual_chunk_indexing import RuntimeVisualChunkIndexingService
from app.services.runtime_visual_enrichment_producer import RuntimeVisualEnrichmentProducer
from app.services.s3_source_acquisition import S3SourceAcquisitionService
from app.services.s3_visual_record_source import S3VisualRecordSource
from app.services.segment_checkpoint_runtime import SegmentCheckpointRuntime
from app.services.segment_plan_runtime import SegmentPlanRuntime
from app.services.segment_plan_runtime_adapter import SegmentPlanRuntimeAdapter
from app.services.semantic_publication import OptionalSemanticPublicationService
from app.services.semantic_publication_runtime_adapter import SemanticPublicationRuntimeAdapter
from app.services.source_inspection import SourceInspectionService
from app.services.source_inspection_runtime_adapter import SourceInspectionRuntimeAdapter
from app.services.visual_enrichment_publication import VisualEnrichmentPublicationService
from app.services.visual_enrichment_runtime_adapter import VisualEnrichmentRuntimeAdapter


def _build_object_storage_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        use_ssl=settings.object_storage_secure,
    )


def build_document_ingestion_adapter(*, session_factory):
    profile_repository = SqlAlchemyIngestionProfileRepository(session_factory)
    content_repository = RuntimeDocumentContentRepository(session_factory)
    lexical_repository = RuntimeLexicalIndexRepository(session_factory)
    acquisition = S3SourceAcquisitionService()
    inspection = SourceInspectionService()

    delegate = DocumentIngestionRuntimeAdapter(
        acquisition=acquisition,
        configuration=IngestionConfigurationService(profile_repository),
        pipeline=OcrTransientOptionIngestionPipelineCoordinator(
            IngestionAdapterResolver(
                [
                    PlainTextIngestionAdapter(),
                    SegmentedPdfIngestionAdapter(),
                ]
            )
        ),
        post_processing=IngestionPostProcessingService(
            DocumentContentPersistenceService(content_repository),
            LexicalIndexService(lexical_repository),
        ),
        processing_revisions=ProcessingRevisionRuntime(session_factory),
        artifact_publication=ProcessingManifestPublicationService(session_factory),
    )
    delegate = SemanticPublicationRuntimeAdapter(
        delegate,
        session_factory,
        OptionalSemanticPublicationService(),
    )
    delegate = SourceInspectionRuntimeAdapter(
        delegate,
        acquisition,
        inspection,
    )
    delegate = SegmentPlanRuntimeAdapter(
        delegate,
        acquisition,
        inspection,
        SegmentPlanRuntime(session_factory),
        SegmentCheckpointRuntime(session_factory),
    )
    visual_producer = CachedVisualEnrichmentProducer(
        RuntimeVisualEnrichmentProducer.from_environment(acquisition),
        acquisition,
    )
    delegate = VisualEnrichmentRuntimeAdapter(
        delegate,
        visual_producer,
        VisualEnrichmentPublicationService(session_factory),
    )

    object_storage_client = _build_object_storage_client()
    visual_source = S3VisualRecordSource(object_storage_client)
    knowledge_publication_service = RuntimeKnowledgeArtifactPublicationService(
        session_factory,
        client=object_storage_client,
        visual_source=visual_source,
    )
    visual_chunk_indexing_service = RuntimeVisualChunkIndexingService(
        session_factory,
        visual_source,
    )
    delegate = KnowledgeArtifactRuntimeAdapter(
        delegate,
        knowledge_publication_service,
        visual_chunk_indexing_service,
    )
    return DocumentIngestionStatusAdapter(
        delegate,
        DocumentVersionStatusService(session_factory),
    )
