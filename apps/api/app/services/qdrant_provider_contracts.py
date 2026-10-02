"""Descriptor-only Qdrant provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QdrantProviderDescriptor:
    provider_name: str = "qdrant-disabled"
    provider_type: str = "descriptor-only"
    provider_version: str = "descriptor-only/1.0"
    enabled: bool = False
    descriptor_only: bool = True
    endpoint_configured: bool = False
    collection_name: str = "derived-vector-index"
    collection_status: str = "disabled"
    vector_dimensions: int = 0
    distance_metric: str = "cosine"
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "provider_version": self.provider_version,
            "enabled": self.enabled,
            "descriptor_only": self.descriptor_only,
            "endpoint_configured": self.endpoint_configured,
            "collection_name": self.collection_name,
            "collection_status": self.collection_status,
            "vector_dimensions": self.vector_dimensions,
            "distance_metric": self.distance_metric,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }


@dataclass(frozen=True)
class QdrantConnectionDescriptor:
    provider_name: str
    provider_type: str
    provider_version: str
    enabled: bool = False
    descriptor_only: bool = True
    endpoint_configured: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "provider_version": self.provider_version,
            "enabled": self.enabled,
            "descriptor_only": self.descriptor_only,
            "endpoint_configured": self.endpoint_configured,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }


@dataclass(frozen=True)
class QdrantCollectionDescriptor:
    provider_name: str
    collection_name: str
    collection_status: str
    vector_dimensions: int
    distance_metric: str
    enabled: bool = False
    descriptor_only: bool = True
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "collection_name": self.collection_name,
            "collection_status": self.collection_status,
            "vector_dimensions": self.vector_dimensions,
            "distance_metric": self.distance_metric,
            "enabled": self.enabled,
            "descriptor_only": self.descriptor_only,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }


@dataclass(frozen=True)
class QdrantExecutionPlan:
    provider: QdrantProviderDescriptor
    connection: QdrantConnectionDescriptor
    collection: QdrantCollectionDescriptor
    execution_allowed: bool = False
    descriptor_only: bool = True
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "qdrant_execution_plan_schema_version": "1",
            "provider": self.provider.as_dict(),
            "connection": self.connection.as_dict(),
            "collection": self.collection.as_dict(),
            "execution_allowed": self.execution_allowed,
            "descriptor_only": self.descriptor_only,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }


@dataclass(frozen=True)
class QdrantExecutionResult:
    plan: QdrantExecutionPlan
    execution_status: str = "descriptor_only"
    vector_values_stored: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "qdrant_execution_result_schema_version": "1",
            "execution_status": self.execution_status,
            "plan": self.plan.as_dict(),
            "vector_values_stored": self.vector_values_stored,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }


@dataclass(frozen=True)
class QdrantHealthResult:
    provider: QdrantProviderDescriptor
    health_status: str = "disabled"
    healthy: bool = True
    enabled: bool = False
    descriptor_only: bool = True
    endpoint_configured: bool = False
    qdrant_called: bool = False
    network_call_attempted: bool = False
    semantic_search_enabled: bool = False
    hybrid_search_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "qdrant_health_result_schema_version": "1",
            "provider": self.provider.as_dict(),
            "health_status": self.health_status,
            "healthy": self.healthy,
            "enabled": self.enabled,
            "descriptor_only": self.descriptor_only,
            "endpoint_configured": self.endpoint_configured,
            "qdrant_called": self.qdrant_called,
            "network_call_attempted": self.network_call_attempted,
            "semantic_search_enabled": self.semantic_search_enabled,
            "hybrid_search_enabled": self.hybrid_search_enabled,
        }
