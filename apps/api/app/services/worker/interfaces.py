"""Platform Worker service interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Protocol

from app.services.worker.contracts import (
    ArtifactPublicationRequest,
    ArtifactPublicationResult,
    JobLease,
    PipelineStateTransition,
    RetryDecision,
    WorkerExecutionContext,
    WorkerExecutionResult,
    WorkerNodeRef,
)


class JobLeaseRepository(Protocol):
    """Persistence boundary for atomic job leasing and state updates."""

    def claim_next(self, worker: WorkerNodeRef, lease_duration: timedelta) -> JobLease | None:
        """Atomically claim the next executable job for this worker."""
        ...

    def transition(self, transition: PipelineStateTransition) -> None:
        """Persist a job state transition."""
        ...


class JobRoutingService(ABC):
    """Determines whether a worker node can execute a leased job."""

    @abstractmethod
    def can_execute(self, worker: WorkerNodeRef, lease: JobLease) -> bool:
        raise NotImplementedError


class JobRetryService(ABC):
    """Determines retry behavior for failed worker attempts."""

    @abstractmethod
    def decide(self, lease: JobLease, result: WorkerExecutionResult) -> RetryDecision:
        raise NotImplementedError


class PipelineStateService(ABC):
    """Builds deterministic state transitions for worker execution."""

    @abstractmethod
    def to_running(self, lease: JobLease) -> PipelineStateTransition:
        raise NotImplementedError

    @abstractmethod
    def from_result(self, lease: JobLease, result: WorkerExecutionResult) -> PipelineStateTransition:
        raise NotImplementedError

    @abstractmethod
    def from_retry_decision(self, lease: JobLease, decision: RetryDecision) -> PipelineStateTransition:
        raise NotImplementedError


class ArtifactPublisher(ABC):
    """Publishes worker artifacts and returns persistable descriptors."""

    @abstractmethod
    def publish(self, request: ArtifactPublicationRequest) -> ArtifactPublicationResult:
        raise NotImplementedError


class WorkerExecutor(ABC):
    """Executes a leased job through product-level service boundaries."""

    @abstractmethod
    def execute(self, context: WorkerExecutionContext) -> WorkerExecutionResult:
        raise NotImplementedError


class PlatformWorker(ABC):
    """Worker runtime boundary.

    Implementations may run in a daemon, container, scheduler, queue consumer, or
    managed worker service. This interface does not mandate process topology.
    """

    @abstractmethod
    def run_once(self, worker: WorkerNodeRef) -> WorkerExecutionResult | None:
        raise NotImplementedError
