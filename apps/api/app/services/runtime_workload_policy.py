from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class WorkloadClassification:
    workload_class: str
    queue_key: str


@dataclass(frozen=True)
class WorkloadPolicyDecision:
    admitted: bool
    reason: str
    classification: WorkloadClassification


class RuntimeWorkloadPolicy:
    """Generic workload-class isolation without business-specific queue names."""

    def __init__(
        self,
        classifier: Callable[[UUID, str | None], WorkloadClassification],
        *,
        accepted_queue_keys: set[str] | frozenset[str] | None = None,
    ) -> None:
        if not callable(classifier):
            raise ValueError("classifier is required")
        self._classifier = classifier
        normalized = (
            frozenset(value.strip() for value in accepted_queue_keys if value.strip())
            if accepted_queue_keys is not None
            else None
        )
        self.accepted_queue_keys = normalized or None

    def evaluate(self, organization_id: UUID, execution_type: str | None) -> WorkloadPolicyDecision:
        classification = self._classifier(organization_id, execution_type)
        if not classification.workload_class.strip():
            raise ValueError("workload_class is required")
        if not classification.queue_key.strip():
            raise ValueError("queue_key is required")
        if self.accepted_queue_keys is not None and classification.queue_key not in self.accepted_queue_keys:
            return WorkloadPolicyDecision(False, "workload_queue_not_accepted", classification)
        return WorkloadPolicyDecision(True, "workload_queue_admitted", classification)


def workload_policy_metrics(decision: WorkloadPolicyDecision) -> dict[str, str | bool]:
    return {
        "workload_admitted": decision.admitted,
        "workload_reason": decision.reason,
        "workload_class": decision.classification.workload_class,
        "workload_queue_key": decision.classification.queue_key,
    }
