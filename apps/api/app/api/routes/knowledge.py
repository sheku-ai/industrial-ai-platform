import contextlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.schemas.documents import (
    EmbeddingRuntimeRequest,
    HybridSearchHealthResponse,
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeFtsSearchRequest,
    KnowledgeIndexRequest,
    KnowledgeLifecycleRequest,
    QdrantProviderHealthResponse,
    QdrantProviderResponse,
    SemanticSearchHealthResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    VectorIndexPrepareRequest,
    VectorIndexPrepareResponse,
)
from app.schemas.product_api import (
    KnowledgeAnswerRequest,
    KnowledgeAnswerResponse,
    KnowledgeCandidateRead,
    KnowledgeCitationRead,
    KnowledgeContextItemRead,
    KnowledgeContextRequest,
    KnowledgeContextResponse,
    KnowledgeFeedbackRequest,
    KnowledgeFeedbackResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    ProductApiStatus,
)
from app.services.embedding_provider_registry import get_embedding_provider_registry
from app.services.embedding_runtime import build_embedding_health, build_embedding_runtime, read_embedding_record
from app.services.guardrails import resolve_guardrail_ref
from app.services.hybrid_search_runtime import build_hybrid_search_health, build_hybrid_search_runtime
from app.services.inference import InferenceRequest, resolve_inference_provider
from app.services.knowledge_fts_runtime import build_knowledge_fts_health, build_knowledge_fts_search
from app.services.knowledge_index_runtime import (
    build_knowledge_index,
    build_knowledge_index_from_publication_evidence,
    read_knowledge_chunk,
    read_knowledge_document,
)
from app.services.knowledge_lifecycle_runtime import (
    build_knowledge_index_health,
    build_knowledge_index_statistics,
    build_knowledge_lifecycle,
)
from app.services.prompting import resolve_prompt_ref
from app.services.qdrant_provider_registry import get_qdrant_provider_registry
from app.services.retrieval import (
    ContentAwareDiversitySelector,
    DeterministicCitationBuilder,
    MergedRetrievalCandidate,
    PostgresFtsRetriever,
    RetrievalFilters,
    RetrievalQuery,
    TokenBudgetContextBuilder,
    WeightedHybridMerger,
)
from app.services.retrieval.extractive_answer import build_extractive_answer, evidence_as_metrics
from app.services.retrieval.facets import facets_as_metrics
from app.services.retrieval.highlighting import build_highlight
from app.services.retrieval.query_metrics import build_feedback_receipt, build_query_metrics
from app.services.retrieval.query_normalization import QueryNormalizationResult, normalize_query_text
from app.services.retrieval.rule_rerank import rerank_candidates, rerank_metrics
from app.services.semantic_search_runtime import build_semantic_search_health, build_semantic_search_runtime
from app.services.vector import VectorProviderRequest, resolve_vector_provider
from app.services.vector_index_runtime import (
    build_vector_index_health,
    build_vector_index_runtime,
    read_vector_index_record,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/status", response_model=ProductApiStatus)
def knowledge_status():
    return ProductApiStatus()


@router.post("/index")
def index_knowledge(
    payload: KnowledgeIndexRequest,
    db: Session = Depends(get_db),
    context: RuntimeRequestContext = Depends(get_runtime_context),
):
    if context.organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="organization_scope_required")
    if payload.publication_evidence_id is not None:
        return build_knowledge_index_from_publication_evidence(
            db,
            evidence_id=payload.publication_evidence_id,
            organization_id=context.organization_id,
        )
    return build_knowledge_index(db, payload.publication_result, organization_id=context.organization_id)


@router.post("/index/reindex")
def reindex_knowledge(payload: KnowledgeLifecycleRequest, db: Session = Depends(get_db)):
    return build_knowledge_lifecycle(
        db,
        operation="reindex",
        mode=payload.mode,
        artifact_id=payload.artifact_id,
        publication_id=payload.publication_id,
        document_id=payload.document_id,
        publication_result=payload.publication_result,
    )


@router.post("/index/incremental")
def incremental_knowledge_index(payload: KnowledgeLifecycleRequest, db: Session = Depends(get_db)):
    return build_knowledge_lifecycle(
        db,
        operation="incremental",
        mode=payload.mode,
        artifact_id=payload.artifact_id,
        publication_id=payload.publication_id,
        document_id=payload.document_id,
        publication_result=payload.publication_result,
    )


@router.post("/index/cleanup")
def cleanup_knowledge_index(payload: KnowledgeLifecycleRequest, db: Session = Depends(get_db)):
    return build_knowledge_lifecycle(
        db,
        operation="cleanup",
        mode=payload.mode,
        artifact_id=payload.artifact_id,
        publication_id=payload.publication_id,
        document_id=payload.document_id,
        publication_result=payload.publication_result,
    )


@router.get("/index/health")
def get_knowledge_index_health(db: Session = Depends(get_db)):
    return build_knowledge_index_health(db)


@router.get("/index/statistics")
def get_knowledge_index_statistics(db: Session = Depends(get_db)):
    return build_knowledge_index_statistics(db)


@router.post("/search/fts")
def search_knowledge_fts(payload: KnowledgeFtsSearchRequest, db: Session = Depends(get_db)):
    return build_knowledge_fts_search(
        db,
        query=payload.query,
        top_k=payload.top_k,
        offset=payload.offset,
        limit=payload.limit,
        filters={
            "artifact_id": payload.artifact_id,
            "publication_id": payload.publication_id,
            "knowledge_document_id": payload.knowledge_document_id,
            "content_type": payload.content_type,
            "chunk_scope": payload.chunk_scope,
            "status": payload.status,
        },
        include_facets=payload.include_facets,
        include_debug=payload.include_debug,
    )


@router.get("/search/fts/health")
def get_knowledge_fts_health(db: Session = Depends(get_db)):
    return build_knowledge_fts_health(db)


@router.post("/embeddings")
def create_knowledge_embedding(payload: EmbeddingRuntimeRequest, db: Session = Depends(get_db)):
    return build_embedding_runtime(
        db,
        chunk_id=payload.chunk_id,
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        model_version=payload.model_version,
        embedding_dimensions=payload.embedding_dimensions,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("/embedding-providers")
def list_embedding_providers():
    registry = get_embedding_provider_registry()
    return {
        "embedding_provider_registry_schema_version": "1",
        "provider_registry_loaded": True,
        "providers": registry.list_providers(),
    }


@router.get("/embedding-providers/health")
def get_embedding_providers_health():
    return get_embedding_provider_registry().health()


@router.get("/qdrant-providers", response_model=QdrantProviderResponse)
def list_qdrant_providers():
    registry = get_qdrant_provider_registry()
    return {
        "qdrant_provider_registry_schema_version": "1",
        "qdrant_provider_registry_loaded": True,
        "providers": registry.list_providers(),
        "qdrant_called": False,
        "network_call_attempted": False,
        "semantic_search_enabled": False,
        "hybrid_search_enabled": False,
    }


@router.get("/qdrant-providers/health", response_model=QdrantProviderHealthResponse)
def get_qdrant_providers_health():
    return get_qdrant_provider_registry().health()


@router.get("/embeddings/health")
def get_knowledge_embeddings_health(db: Session = Depends(get_db)):
    return build_embedding_health(db)


@router.get("/embeddings/{embedding_id}")
def get_knowledge_embedding(embedding_id: str, db: Session = Depends(get_db)):
    result = read_embedding_record(db, embedding_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="embedding record not found")
    return result


@router.post("/vector-indexes", response_model=VectorIndexPrepareResponse)
def prepare_knowledge_vector_index(payload: VectorIndexPrepareRequest, db: Session = Depends(get_db)):
    return build_vector_index_runtime(
        db,
        embedding_id=payload.embedding_id,
        index_name=payload.index_name,
        index_provider=payload.index_provider,
        index_provider_type=payload.index_provider_type,
        index_version=payload.index_version,
        qdrant_provider_name=payload.qdrant_provider_name,
        qdrant_collection_name=payload.qdrant_collection_name,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("/vector-indexes/health")
def get_knowledge_vector_indexes_health(db: Session = Depends(get_db)):
    return build_vector_index_health(db)


@router.get("/vector-indexes/{vector_index_id}")
def get_knowledge_vector_index(vector_index_id: str, db: Session = Depends(get_db)):
    result = read_vector_index_record(db, vector_index_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vector index record not found")
    return result


@router.post("/semantic-search", response_model=SemanticSearchResponse)
def prepare_semantic_search(payload: SemanticSearchRequest, db: Session = Depends(get_db)):
    return build_semantic_search_runtime(
        db,
        query=payload.query,
        top_k=payload.top_k,
        vector_index_id=payload.vector_index_id,
        qdrant_provider_name=payload.qdrant_provider_name,
        semantic_search_enabled=payload.semantic_search_enabled,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("/semantic-search/health", response_model=SemanticSearchHealthResponse)
def get_semantic_search_health():
    return build_semantic_search_health()


@router.post("/hybrid-search", response_model=HybridSearchResponse)
def prepare_hybrid_search(payload: HybridSearchRequest, db: Session = Depends(get_db)):
    return build_hybrid_search_runtime(
        db,
        query=payload.query,
        top_k=payload.top_k,
        hybrid_search_enabled=payload.hybrid_search_enabled,
        runtime_metadata=payload.runtime_metadata,
    )


@router.get("/hybrid-search/health", response_model=HybridSearchHealthResponse)
def get_hybrid_search_health():
    return build_hybrid_search_health()


@router.get("/documents/{document_id}")
def get_knowledge_document(document_id: str, db: Session = Depends(get_db)):
    result = read_knowledge_document(db, document_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge document not found")
    return result


@router.get("/chunks/{chunk_id}")
def get_knowledge_chunk(chunk_id: str, db: Session = Depends(get_db)):
    result = read_knowledge_chunk(db, chunk_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge chunk not found")
    return result


def _query_normalization(payload: KnowledgeSearchRequest) -> QueryNormalizationResult:
    return normalize_query_text(payload.query_text)


def _query(payload: KnowledgeSearchRequest) -> RetrievalQuery:
    normalized = _query_normalization(payload)
    return RetrievalQuery(
        query_text=normalized.normalized_query_text,
        filters=RetrievalFilters(
            organization_id=payload.organization_id,
            collection_ids=payload.collection_ids,
            metadata=payload.metadata,
            classification=payload.classification,
        ),
        top_k=payload.top_k,
        candidate_k=payload.candidate_k,
        lexical_weight=1.0,
        vector_weight=0.0,
        enable_rerank=getattr(payload, "enable_rerank", False),
        enable_diversity=getattr(payload, "enable_diversity", True),
        context_token_budget=getattr(payload, "context_token_budget", 4000),
    )


def _vector_provider_metrics(payload: KnowledgeSearchRequest) -> dict[str, object]:
    provider = resolve_vector_provider(payload.vector_provider_ref)
    resolution = provider.resolve(
        VectorProviderRequest(
            vector_provider_ref=payload.vector_provider_ref,
            retrieval_mode=payload.retrieval_mode,
            embedding_enabled=payload.embedding_enabled,
            embedding_model_ref=payload.embedding_model_ref,
            embedding_provider_ref=payload.embedding_provider_ref,
            embedding_dimension=payload.embedding_dimension,
            collection_ids=tuple(str(item) for item in payload.collection_ids),
        )
    )
    return resolution.as_metrics()


def _resolved_retrieval_mode(payload: KnowledgeSearchRequest) -> str:
    if payload.retrieval_mode in {"vector_only", "hybrid"}:
        return "lexical_only"
    return payload.retrieval_mode


def _retrieval_contract_metrics(payload: KnowledgeSearchRequest) -> dict[str, object]:
    resolved_mode = _resolved_retrieval_mode(payload)
    fallback_used = payload.retrieval_mode != resolved_mode
    fallback_reason = "vector_provider_not_configured" if fallback_used else None
    vector_metrics = _vector_provider_metrics(payload)
    return {
        "retrieval_contract_version": "retrieval_mode_contract_v1",
        "requested_retrieval_mode": payload.retrieval_mode,
        "resolved_retrieval_mode": resolved_mode,
        "retrieval_mode": resolved_mode,
        "retrieval_mode_fallback_used": fallback_used,
        "retrieval_mode_fallback_reason": fallback_reason,
        "lexical_retrieval_enabled": True,
        "lexical_retrieval_provider": "postgres_fts",
        "vector_retrieval_enabled": False,
        **vector_metrics,
        "embedding_enabled": payload.embedding_enabled,
        "embedding_requested": payload.embedding_enabled,
        "embedding_model_ref": payload.embedding_model_ref,
        "embedding_provider_ref": payload.embedding_provider_ref,
        "embedding_dimension": payload.embedding_dimension,
        "embedding_execution_enabled": False,
        "embedding_status": "configured_not_executed" if payload.embedding_enabled else "disabled",
        "embedding_fallback_reason": "embedding_execution_not_configured" if payload.embedding_enabled else None,
    }


def _query_metrics(payload: KnowledgeSearchRequest, normalized: QueryNormalizationResult) -> dict[str, object]:
    return {
        **normalized.as_metrics(),
        "query_normalizer": "deterministic_cpu_v1",
        "query_parser": "websearch_to_tsquery",
        "fts_config": "simple",
    }


def _retrieval_contribution_metrics(
    lexical_candidates: tuple,
    vector_candidates: tuple,
    merged_candidates: tuple[MergedRetrievalCandidate, ...],
) -> dict[str, object]:
    lexical_count = len(lexical_candidates)
    vector_count = len(vector_candidates)
    merged_count = len(merged_candidates)
    lexical_contribution_count = sum(1 for item in merged_candidates if item.lexical_score is not None)
    vector_contribution_count = sum(1 for item in merged_candidates if item.vector_score is not None)
    total_contribution_count = lexical_contribution_count + vector_contribution_count
    lexical_share = 1.0 if lexical_contribution_count else 0.0
    vector_share = 0.0 if total_contribution_count == 0 else vector_contribution_count / total_contribution_count
    return {
        "retrieval_contribution_contract": "retrieval_contribution_metrics_v1",
        "retrieval_contribution_metrics_enabled": True,
        "retrieval_contribution_basis": "merged_candidates",
        "retrieval_contribution_runtime": "lexical_only_fallback",
        "retrieval_contribution_status": "lexical_only",
        "retrieval_contribution_source_of_truth": "postgres_fts",
        "retrieval_contribution_lexical_provider": "postgres_fts",
        "retrieval_contribution_vector_provider": None,
        "retrieval_contribution_total_candidates": merged_count,
        "retrieval_contribution_lexical_candidates": lexical_count,
        "retrieval_contribution_vector_candidates": vector_count,
        "retrieval_contribution_merged_candidates": merged_count,
        "retrieval_contribution_lexical_count": lexical_contribution_count,
        "retrieval_contribution_vector_count": vector_contribution_count,
        "retrieval_contribution_lexical_share": lexical_share,
        "retrieval_contribution_vector_share": vector_share,
        "retrieval_contribution_vector_available": False,
        "retrieval_contribution_fallback_active": vector_count == 0,
        "retrieval_contribution_fallback_reason": "vector_provider_not_configured" if vector_count == 0 else None,
    }


def _hybrid_merge_metrics(
    payload: KnowledgeSearchRequest,
    lexical_candidates: tuple,
    vector_candidates: tuple,
    merged_candidates: tuple[MergedRetrievalCandidate, ...],
) -> dict[str, object]:
    return {
        "hybrid_merge_contract": "weighted_hybrid_candidate_merge_v1",
        "hybrid_merge_enabled": True,
        "hybrid_merge_executed": True,
        "hybrid_merger": "weighted_hybrid_merger_v1",
        "hybrid_merge_requested_mode": payload.retrieval_mode,
        "hybrid_merge_resolved_mode": _resolved_retrieval_mode(payload),
        "lexical_weight": 1.0,
        "vector_weight": 0.0,
        "lexical_candidate_count": len(lexical_candidates),
        "vector_candidate_count": len(vector_candidates),
        "merged_candidate_count": len(merged_candidates),
        "hybrid_lexical_only_fallback": len(vector_candidates) == 0,
        "hybrid_vector_contribution_count": sum(1 for item in merged_candidates if item.vector_score is not None),
        "hybrid_lexical_contribution_count": sum(1 for item in merged_candidates if item.lexical_score is not None),
        "hybrid_vector_contribution_available": False,
        "hybrid_merge_strategy": "lexical_weight_1_vector_weight_0_until_vector_provider_available",
        **_retrieval_contribution_metrics(lexical_candidates, vector_candidates, merged_candidates),
    }


def _merge_candidates(payload: KnowledgeSearchRequest, lexical_candidates: tuple) -> tuple[tuple, dict[str, object]]:
    retrieval_query = _query(payload)
    vector_candidates: tuple = ()
    merged = WeightedHybridMerger().merge(retrieval_query, lexical_candidates, vector_candidates)
    merged_candidates = []
    for item in merged:
        candidate = item.candidate
        metadata = dict(candidate.metadata or {})
        metadata["hybrid_merge"] = {
            "merger": "weighted_hybrid_merger_v1",
            "rank": item.rank,
            "lexical_score": item.lexical_score,
            "vector_score": item.vector_score,
            "merged_score": item.merged_score,
            "vector_candidate_present": item.vector_score is not None,
            "lexical_weight": 1.0,
            "vector_weight": 0.0,
        }
        metadata["retrieval_contribution"] = {
            "contract": "retrieval_contribution_metrics_v1",
            "lexical_contributed": item.lexical_score is not None,
            "vector_contributed": item.vector_score is not None,
            "primary_source": "lexical" if item.lexical_score is not None else "unknown",
            "source_of_truth": "postgres_fts",
            "vector_available": False,
            "fallback_active": item.vector_score is None,
        }
        merged_candidates.append(
            candidate.__class__(
                chunk_id=candidate.chunk_id,
                organization_id=candidate.organization_id,
                document_record_id=candidate.document_record_id,
                document_version_id=candidate.document_version_id,
                collection_id=candidate.collection_id,
                chunk_key=candidate.chunk_key,
                text=candidate.text,
                source=candidate.source,
                score=item.merged_score,
                content_hash=candidate.content_hash,
                metadata=metadata,
                classification=candidate.classification,
            )
        )
    return tuple(merged_candidates), _hybrid_merge_metrics(payload, lexical_candidates, vector_candidates, merged)


def _count_highlights(items: tuple) -> tuple[int, int]:
    highlighted_count = 0
    match_count = 0
    for item in items:
        highlight = (item.metadata or {}).get("highlight") or {}
        if highlight.get("snippet"):
            highlighted_count += 1
        with contextlib.suppress(Exception):
            match_count += int(highlight.get("match_count") or 0)
    return highlighted_count, match_count


def _highlight_metrics(items: tuple, *, stage: str) -> dict[str, object]:
    highlighted_count, match_count = _count_highlights(items)
    return {
        "highlighting_enabled": True,
        "highlighter": "deterministic_cpu_v1",
        f"{stage}_highlighted_count": highlighted_count,
        f"{stage}_highlight_match_count": match_count,
    }


def _with_highlights(candidates: tuple, normalized: QueryNormalizationResult) -> tuple:
    enriched = []
    for candidate in candidates:
        highlight = build_highlight(candidate.text, normalized)
        metadata = dict(candidate.metadata or {})
        metadata["highlight"] = highlight.as_metadata()
        enriched.append(
            candidate.__class__(
                chunk_id=candidate.chunk_id,
                organization_id=candidate.organization_id,
                document_record_id=candidate.document_record_id,
                document_version_id=candidate.document_version_id,
                collection_id=candidate.collection_id,
                chunk_key=candidate.chunk_key,
                text=candidate.text,
                source=candidate.source,
                score=candidate.score,
                content_hash=candidate.content_hash,
                metadata=metadata,
                classification=candidate.classification,
            )
        )
    return tuple(enriched)


def _prepare_candidates(payload: KnowledgeSearchRequest, db: Session) -> tuple[tuple, dict[str, object]]:
    normalized = _query_normalization(payload)
    highlighted = _with_highlights(PostgresFtsRetriever(db).retrieve(_query(payload)), normalized)
    merged, merge_metrics = _merge_candidates(payload, highlighted)
    return rerank_candidates(merged, normalized), merge_metrics


def _read_candidate(candidate) -> KnowledgeCandidateRead:
    return KnowledgeCandidateRead(
        chunk_id=candidate.chunk_id,
        document_record_id=candidate.document_record_id,
        document_version_id=candidate.document_version_id,
        collection_id=candidate.collection_id,
        chunk_key=candidate.chunk_key,
        text=candidate.text,
        score=candidate.score,
        metadata=candidate.metadata,
        classification=candidate.classification,
    )


def _build_context_response(
    payload: KnowledgeContextRequest, db: Session, *, endpoint: str = "context"
) -> KnowledgeContextResponse:
    normalized = _query_normalization(payload)
    retrieval_query = _query(payload)
    retrieved_candidates, merge_metrics = _prepare_candidates(payload, db)
    merged = tuple(
        MergedRetrievalCandidate(
            candidate=candidate,
            lexical_score=((candidate.metadata or {}).get("hybrid_merge") or {}).get("lexical_score"),
            vector_score=((candidate.metadata or {}).get("hybrid_merge") or {}).get("vector_score"),
            merged_score=((candidate.metadata or {}).get("hybrid_merge") or {}).get("merged_score", candidate.score),
            rank=index + 1,
        )
        for index, candidate in enumerate(retrieved_candidates)
    )
    selected = ContentAwareDiversitySelector().select(retrieval_query, merged)
    context = TokenBudgetContextBuilder().build(retrieval_query, selected)
    citations = DeterministicCitationBuilder().build(context)
    return KnowledgeContextResponse(
        query_text=payload.query_text,
        context=tuple(
            KnowledgeContextItemRead(
                chunk_id=item.chunk_id,
                document_record_id=item.document_record_id,
                document_version_id=item.document_version_id,
                collection_id=item.collection_id,
                chunk_key=item.chunk_key,
                text=item.text,
                score=item.score,
                metadata=item.metadata,
                classification=item.classification,
                rank=item.rank,
                citation_key=item.citation_key,
            )
            for item in context
        ),
        citations=tuple(
            KnowledgeCitationRead(
                citation_key=item.citation_key,
                chunk_id=item.chunk_id,
                document_record_id=item.document_record_id,
                document_version_id=item.document_version_id,
                collection_id=item.collection_id,
                chunk_key=item.chunk_key,
                metadata=item.metadata,
            )
            for item in citations
        ),
        metrics={
            "status": "connected",
            "context_count": len(context),
            "citation_count": len(citations),
            "candidate_count": len(retrieved_candidates),
            "retrieval_provider": "postgres_fts",
            **_retrieval_contract_metrics(payload),
            **merge_metrics,
            **_query_metrics(payload, normalized),
            **_highlight_metrics(retrieved_candidates, stage="retrieved_candidates"),
            **_highlight_metrics(context, stage="selected_context"),
            **facets_as_metrics(retrieved_candidates, payload.facet_fields, stage="retrieved_candidates"),
            **facets_as_metrics(context, payload.facet_fields, stage="selected_context"),
            **rerank_metrics(retrieved_candidates, stage="retrieved_candidates"),
            **rerank_metrics(context, stage="selected_context"),
            **build_query_metrics(
                original_query_text=payload.query_text,
                normalized=normalized,
                endpoint=endpoint,
                result_count=len(context),
                citation_count=len(citations),
            ).as_metrics(),
            "vector_enabled": False,
            "diversity_enabled": payload.enable_diversity,
        },
    )


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(payload: KnowledgeSearchRequest, db: Session = Depends(get_db)):
    normalized = _query_normalization(payload)
    retrieved_candidates, merge_metrics = _prepare_candidates(payload, db)
    candidates = retrieved_candidates[: payload.top_k]
    return KnowledgeSearchResponse(
        query_text=payload.query_text,
        candidates=tuple(_read_candidate(candidate) for candidate in candidates),
        metrics={
            "status": "connected",
            "candidate_count": len(candidates),
            "retrieved_candidate_count": len(retrieved_candidates),
            "retrieval_provider": "postgres_fts",
            **_retrieval_contract_metrics(payload),
            **merge_metrics,
            **_query_metrics(payload, normalized),
            **_highlight_metrics(candidates, stage="returned_candidates"),
            **facets_as_metrics(retrieved_candidates, payload.facet_fields, stage="retrieved_candidates"),
            **rerank_metrics(retrieved_candidates, stage="retrieved_candidates"),
            **rerank_metrics(candidates, stage="returned_candidates"),
            **build_query_metrics(
                original_query_text=payload.query_text,
                normalized=normalized,
                endpoint="search",
                result_count=len(candidates),
            ).as_metrics(),
            "vector_enabled": False,
        },
    )


@router.post("/context", response_model=KnowledgeContextResponse)
def build_context(payload: KnowledgeContextRequest, db: Session = Depends(get_db)):
    return _build_context_response(payload, db, endpoint="context")


@router.post("/retrieve", response_model=KnowledgeContextResponse)
def retrieve_knowledge(payload: KnowledgeContextRequest, db: Session = Depends(get_db)):
    return _build_context_response(payload, db, endpoint="retrieve")


def _context_for_inference(context_response: KnowledgeContextResponse) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "chunk_id": str(item.chunk_id),
            "document_version_id": str(item.document_version_id),
            "collection_id": None if item.collection_id is None else str(item.collection_id),
            "chunk_key": item.chunk_key,
            "text": item.text,
            "rank": item.rank,
            "citation_key": item.citation_key,
            "metadata": item.metadata,
        }
        for item in context_response.context
    )


def _citations_for_inference(context_response: KnowledgeContextResponse) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "citation_key": item.citation_key,
            "chunk_id": str(item.chunk_id),
            "document_version_id": str(item.document_version_id),
            "collection_id": None if item.collection_id is None else str(item.collection_id),
            "chunk_key": item.chunk_key,
            "metadata": item.metadata,
        }
        for item in context_response.citations
    )


def _runtime_reason(answer_generated: bool, fallback_reason: str | None, resolved_mode: str) -> str:
    if answer_generated:
        return "assisted_answer_generated"
    return fallback_reason or f"{resolved_mode}_answer_no_generation"


@router.post("/answer", response_model=KnowledgeAnswerResponse)
def answer_knowledge(payload: KnowledgeAnswerRequest, db: Session = Depends(get_db)):
    normalized = _query_normalization(payload)
    context_response = _build_context_response(payload, db, endpoint="answer")
    requested_mode = payload.answer_mode
    provider_result = None
    prompt_resolution = None
    guardrail_resolution = None

    if requested_mode == "context_only":
        resolved_mode = "context_only"
        fallback_used = False
        fallback_reason = None
    elif requested_mode == "assisted":
        prompt_resolution = resolve_prompt_ref(payload.prompt_ref)
        guardrail_resolution = resolve_guardrail_ref(payload.guardrail_ref)
        runtime_options = {
            **prompt_resolution.as_runtime_options(),
            **guardrail_resolution.as_runtime_options(),
        }
        if not prompt_resolution.resolved:
            resolved_mode = "extractive"
            fallback_used = True
            fallback_reason = prompt_resolution.error_code or "prompt_ref_unresolved"
        elif not guardrail_resolution.allowed:
            resolved_mode = "extractive"
            fallback_used = True
            fallback_reason = guardrail_resolution.error_code or "guardrail_blocked"
        else:
            inference_provider = resolve_inference_provider(payload.provider_ref)
            provider_result = inference_provider.generate(
                InferenceRequest(
                    provider_ref=payload.provider_ref,
                    model_ref=payload.model_ref,
                    prompt_ref=payload.prompt_ref,
                    guardrail_ref=payload.guardrail_ref,
                    query_text=payload.query_text,
                    context=_context_for_inference(context_response),
                    citations=_citations_for_inference(context_response),
                    runtime_options=runtime_options,
                )
            )
            resolved_mode = "assisted" if provider_result.success else "extractive"
            fallback_used = not provider_result.success
            fallback_reason = provider_result.error_code if fallback_used else None
    else:
        resolved_mode = "extractive"
        fallback_used = False
        fallback_reason = None

    answer_generated = resolved_mode == "assisted" and provider_result is not None and provider_result.success
    llm_used = answer_generated
    extractive_answer = (
        None if resolved_mode == "context_only" else build_extractive_answer(context_response.context, normalized)
    )
    if answer_generated:
        answer_text = provider_result.generated_text
    elif extractive_answer is None:
        answer_text = None
    else:
        answer_text = extractive_answer.answer

    metrics = {
        **context_response.metrics,
        **build_query_metrics(
            original_query_text=payload.query_text,
            normalized=normalized,
            endpoint="answer",
            result_count=len(context_response.context),
            citation_count=len(context_response.citations),
            answer_mode=resolved_mode,
        ).as_metrics(),
        "answer_contract_version": "answer_mode_contract_v1",
        "answer_endpoint": "answer_mode_runtime_v1",
        "requested_answer_mode": requested_mode,
        "resolved_answer_mode": resolved_mode,
        "answer_mode": resolved_mode,
        "answer_generated": answer_generated,
        "llm_used": llm_used,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "inference_requested": payload.use_inference,
        "inference_enabled": provider_result is not None,
        "inference_provider": None if provider_result is None else provider_result.provider_adapter,
        "provider_ref": payload.provider_ref,
        "model_ref": payload.model_ref,
        "prompt_ref": payload.prompt_ref,
        "guardrail_ref": payload.guardrail_ref,
        "model_id": payload.model_ref,
        "reason": _runtime_reason(answer_generated, fallback_reason, resolved_mode),
    }
    if prompt_resolution is not None:
        metrics.update(prompt_resolution.as_metrics())
    if guardrail_resolution is not None:
        metrics.update(guardrail_resolution.as_metrics())
    if provider_result is not None:
        metrics.update(provider_result.as_metrics())
    if extractive_answer is not None:
        metrics.update(evidence_as_metrics(extractive_answer))
    else:
        metrics.update(
            {"context_only_enabled": True, "extractive_answer_enabled": False, "extractive_evidence_count": 0}
        )

    return KnowledgeAnswerResponse(
        query_text=payload.query_text,
        answer=answer_text,
        context=context_response.context,
        citations=context_response.citations,
        requested_answer_mode=requested_mode,
        resolved_answer_mode=resolved_mode,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        answer_generated=answer_generated,
        llm_used=llm_used,
        provider_ref=payload.provider_ref,
        model_ref=payload.model_ref,
        prompt_ref=payload.prompt_ref,
        guardrail_ref=payload.guardrail_ref,
        metrics=metrics,
    )


@router.post("/feedback", response_model=KnowledgeFeedbackResponse)
def submit_feedback(payload: KnowledgeFeedbackRequest):
    return KnowledgeFeedbackResponse(status="accepted", receipt=build_feedback_receipt(payload))
