"""Governance-aware query metrics for Knowledge Runtime.

Sprint 11.6 adds deterministic runtime telemetry without requiring a database
migration. Persistence can be added later through the audit or telemetry domain.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.retrieval.query_normalization import QueryNormalizationResult


@dataclass(frozen=True)
class QueryMetricsTrace:
    """Runtime query telemetry safe for response metrics."""

    query_event_id: str
    query_hash: str
    normalized_query_hash: str
    captured_at_epoch_ms: int
    retention_mode: str = "ephemeral_response_metrics"
    persistence_enabled: bool = False
    fields: dict[str, Any] = field(default_factory=dict)

    def as_metrics(self) -> dict[str, object]:
        return {
            "query_metrics_enabled": True,
            "query_metrics_version": "deterministic_query_metrics_v1",
            "query_event_id": self.query_event_id,
            "query_hash": self.query_hash,
            "normalized_query_hash": self.normalized_query_hash,
            "query_metrics_captured_at_epoch_ms": self.captured_at_epoch_ms,
            "query_metrics_retention_mode": self.retention_mode,
            "query_metrics_persistence_enabled": self.persistence_enabled,
            **self.fields,
        }


def build_query_metrics(
    *,
    original_query_text: str,
    normalized: QueryNormalizationResult,
    endpoint: str,
    result_count: int,
    citation_count: int = 0,
    answer_mode: str | None = None,
) -> QueryMetricsTrace:
    """Build non-persistent query telemetry for one runtime response."""

    fields: dict[str, Any] = {
        "query_endpoint": endpoint,
        "query_result_count": int(result_count),
        "query_citation_count": int(citation_count),
        "query_text_recorded": False,
        "normalized_query_text_recorded": False,
        "query_length": len(original_query_text or ""),
        "normalized_query_length": len(normalized.normalized_query_text or ""),
    }
    if answer_mode:
        fields["query_answer_mode"] = answer_mode

    return QueryMetricsTrace(
        query_event_id=str(uuid.uuid4()),
        query_hash=_hash_text(original_query_text),
        normalized_query_hash=_hash_text(normalized.normalized_query_text),
        captured_at_epoch_ms=int(time.time() * 1000),
        fields=fields,
    )


def build_feedback_receipt(payload: Any) -> dict[str, object]:
    """Build an auditable feedback receipt without persisting the event."""

    rating = getattr(payload, "rating", None)
    return {
        "feedback_received": True,
        "feedback_event_id": str(uuid.uuid4()),
        "feedback_status": "accepted_not_persisted",
        "feedback_persistence_enabled": False,
        "feedback_retention_mode": "ephemeral_response_receipt",
        "feedback_version": "deterministic_feedback_receipt_v1",
        "organization_id": str(getattr(payload, "organization_id", "")),
        "query_event_id": getattr(payload, "query_event_id", None),
        "target_type": getattr(payload, "target_type", None),
        "target_id": getattr(payload, "target_id", None),
        "rating": rating,
        "comment_recorded": bool(getattr(payload, "comment", None)),
        "comment_text_persisted": False,
        "metadata_recorded": bool(getattr(payload, "metadata", None)),
    }


def _hash_text(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()
