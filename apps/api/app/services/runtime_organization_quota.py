from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OrganizationQuota:
    max_active_work: int | None = None
    max_queued_work: int | None = None
    max_started_in_window: int | None = None
    max_source_bytes_in_window: int | None = None


@dataclass(frozen=True)
class OrganizationUsage:
    active_work: int = 0
    queued_work: int = 0
    started_in_window: int = 0
    source_bytes_in_window: int = 0


@dataclass(frozen=True)
class OrganizationQuotaDecision:
    admitted: bool
    reason: str
    quota: OrganizationQuota
    usage: OrganizationUsage


class OrganizationQuotaController:
    """Provider-neutral organization-scoped quota admission service."""

    def __init__(
        self,
        quota_provider: Callable[[UUID], OrganizationQuota | None],
        usage_provider: Callable[[UUID], OrganizationUsage],
    ) -> None:
        if not callable(quota_provider):
            raise ValueError("quota_provider is required")
        if not callable(usage_provider):
            raise ValueError("usage_provider is required")
        self._quota_provider = quota_provider
        self._usage_provider = usage_provider

    def evaluate(self, organization_id: UUID) -> OrganizationQuotaDecision:
        quota = self._quota_provider(organization_id) or OrganizationQuota()
        usage = self._usage_provider(organization_id)
        if quota.max_active_work is not None and usage.active_work >= quota.max_active_work:
            return OrganizationQuotaDecision(False, "organization_active_work_limit", quota, usage)
        if quota.max_queued_work is not None and usage.queued_work > quota.max_queued_work:
            return OrganizationQuotaDecision(False, "organization_queue_limit", quota, usage)
        if quota.max_started_in_window is not None and usage.started_in_window >= quota.max_started_in_window:
            return OrganizationQuotaDecision(False, "organization_execution_rate_limit", quota, usage)
        if (
            quota.max_source_bytes_in_window is not None
            and usage.source_bytes_in_window >= quota.max_source_bytes_in_window
        ):
            return OrganizationQuotaDecision(False, "organization_source_bytes_limit", quota, usage)
        return OrganizationQuotaDecision(True, "organization_quota_admitted", quota, usage)


def organization_quota_metrics(decision: OrganizationQuotaDecision) -> dict[str, int | str | bool | None]:
    return {
        "organization_quota_admitted": decision.admitted,
        "organization_quota_reason": decision.reason,
        "organization_usage_active_work": decision.usage.active_work,
        "organization_usage_queued_work": decision.usage.queued_work,
        "organization_usage_started_in_window": decision.usage.started_in_window,
        "organization_usage_source_bytes_in_window": decision.usage.source_bytes_in_window,
        "organization_quota_max_active_work": decision.quota.max_active_work,
        "organization_quota_max_queued_work": decision.quota.max_queued_work,
        "organization_quota_max_started_in_window": decision.quota.max_started_in_window,
        "organization_quota_max_source_bytes_in_window": decision.quota.max_source_bytes_in_window,
    }
