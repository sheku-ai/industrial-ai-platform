from __future__ import annotations

from app.contracts.runtime_execution import ProviderExecutionRequest, ProviderExecutionResult
from app.providers.base import ProviderCapabilities, ProviderHealth


class DisabledProviderAdapter:
    @property
    def adapter_type(self) -> str:
        return "disabled"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            generation=False,
            streaming=False,
            tool_calling=False,
            structured_output=False,
            embeddings=False,
            health_check=True,
            metadata={"execution_enabled": False},
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status="disabled",
            message="Provider execution is not configured.",
            metadata={"network_call_performed": False},
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            request_id=request.request_id,
            status="failed",
            retryable=False,
            provider_error_code="provider_not_available",
            provider_metadata={
                "adapter_type": self.adapter_type,
                "network_call_performed": False,
                "generation_performed": False,
            },
        )
