import hashlib
import json
from typing import Any


def resolve_configuration_revision(settings: Any) -> str:
    payload = {
        "app_name": getattr(settings, "app_name", ""),
        "app_version": getattr(settings, "app_version", ""),
        "embeddings": bool(getattr(settings, "feature_embeddings_enabled", False)),
        "vector_retrieval": bool(getattr(settings, "feature_vector_retrieval_enabled", False)),
        "worker": bool(getattr(settings, "feature_worker_enabled", False)),
        "enterprise_extensions": bool(getattr(settings, "feature_enterprise_extensions_enabled", False)),
        "object_storage_configured": bool(getattr(settings, "object_storage_endpoint_url", "")),
        "object_storage_region": getattr(settings, "object_storage_region", ""),
        "object_storage_secure": bool(getattr(settings, "object_storage_secure", False)),
        "ingestion_workspace_root": getattr(settings, "ingestion_workspace_root", ""),
        "ingestion_max_source_bytes": int(getattr(settings, "ingestion_max_source_bytes", 0)),
        "pending_warning_seconds": int(getattr(settings, "operational_health_pending_warning_seconds", 0)),
        "stale_data_seconds": int(getattr(settings, "operational_health_stale_data_seconds", 0)),
        "failed_run_critical_count": int(getattr(settings, "operational_health_failed_run_critical_count", 0)),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"
