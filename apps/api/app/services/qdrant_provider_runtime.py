"""Descriptor-only Qdrant provider runtime adapter."""

from __future__ import annotations

from app.services.qdrant_provider_contracts import (
    QdrantCollectionDescriptor,
    QdrantConnectionDescriptor,
    QdrantExecutionPlan,
    QdrantExecutionResult,
    QdrantHealthResult,
    QdrantProviderDescriptor,
)


class QdrantProviderRuntimeAdapter:
    def build_connection_descriptor(self, provider: QdrantProviderDescriptor) -> QdrantConnectionDescriptor:
        return QdrantConnectionDescriptor(
            provider_name=provider.provider_name,
            provider_type=provider.provider_type,
            provider_version=provider.provider_version,
            enabled=provider.enabled,
            descriptor_only=provider.descriptor_only,
            endpoint_configured=provider.endpoint_configured,
            qdrant_called=False,
            network_call_attempted=False,
            semantic_search_enabled=False,
            hybrid_search_enabled=False,
        )

    def build_collection_descriptor(
        self,
        provider: QdrantProviderDescriptor,
        *,
        collection_name: str | None = None,
        vector_dimensions: int | None = None,
    ) -> QdrantCollectionDescriptor:
        return QdrantCollectionDescriptor(
            provider_name=provider.provider_name,
            collection_name=collection_name or provider.collection_name,
            collection_status=provider.collection_status,
            vector_dimensions=int(vector_dimensions if vector_dimensions is not None else provider.vector_dimensions),
            distance_metric=provider.distance_metric,
            enabled=provider.enabled,
            descriptor_only=provider.descriptor_only,
            qdrant_called=False,
            network_call_attempted=False,
            semantic_search_enabled=False,
            hybrid_search_enabled=False,
        )

    def build_execution_plan(
        self,
        provider: QdrantProviderDescriptor,
        *,
        collection_name: str | None = None,
        vector_dimensions: int | None = None,
    ) -> QdrantExecutionPlan:
        connection = self.build_connection_descriptor(provider)
        collection = self.build_collection_descriptor(
            provider,
            collection_name=collection_name,
            vector_dimensions=vector_dimensions,
        )
        return QdrantExecutionPlan(
            provider=provider,
            connection=connection,
            collection=collection,
            execution_allowed=False,
            descriptor_only=True,
            qdrant_called=False,
            network_call_attempted=False,
            semantic_search_enabled=False,
            hybrid_search_enabled=False,
        )

    def evaluate_health(self, provider: QdrantProviderDescriptor) -> QdrantHealthResult:
        return QdrantHealthResult(
            provider=provider,
            health_status="disabled" if not provider.enabled else "descriptor_only",
            healthy=True,
            enabled=provider.enabled,
            descriptor_only=provider.descriptor_only,
            endpoint_configured=provider.endpoint_configured,
            qdrant_called=False,
            network_call_attempted=False,
            semantic_search_enabled=False,
            hybrid_search_enabled=False,
        )

    def execute_vector_index_publication_plan(self, plan: QdrantExecutionPlan) -> QdrantExecutionResult:
        return QdrantExecutionResult(
            plan=plan,
            execution_status="descriptor_only",
            vector_values_stored=False,
            qdrant_called=False,
            network_call_attempted=False,
            semantic_search_enabled=False,
            hybrid_search_enabled=False,
        )


default_qdrant_provider_runtime_adapter = QdrantProviderRuntimeAdapter()


def get_qdrant_provider_runtime_adapter() -> QdrantProviderRuntimeAdapter:
    return default_qdrant_provider_runtime_adapter
