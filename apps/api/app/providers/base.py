from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.contracts.runtime_execution import ProviderExecutionRequest, ProviderExecutionResult

JsonMapping = Mapping[str, Any]


@dataclass(frozen=True)
class ProviderCapabilities:
    generation: bool = False
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    embeddings: bool = False
    health_check: bool = True
    metadata: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    message: str | None = None
    latency_ms: int | None = None
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class ProviderAdapter(Protocol):
    @property
    def adapter_type(self) -> str: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def health_check(self) -> ProviderHealth: ...

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult: ...
