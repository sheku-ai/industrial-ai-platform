from __future__ import annotations

import os

from app.secret_refs.base import (
    SecretReference,
    SecretResolutionResult,
    SecretValue,
)


class EnvironmentSecretResolver:
    @property
    def resolver_type(self) -> str:
        return "env"

    def resolve(self, reference: SecretReference) -> SecretResolutionResult:
        variable_name = reference.reference.strip()
        if not variable_name:
            return SecretResolutionResult(
                status="not_found",
                error_code="secret_reference_unresolved",
                message="Environment variable reference is empty.",
                metadata={"resolver_type": self.resolver_type},
            )

        value = os.getenv(variable_name)
        if value is None:
            return SecretResolutionResult(
                status="not_found",
                error_code="secret_reference_unresolved",
                message="Environment variable was not found.",
                metadata={
                    "resolver_type": self.resolver_type,
                    "reference_present": True,
                },
            )

        return SecretResolutionResult(
            status="resolved",
            value=SecretValue(value),
            metadata={
                "resolver_type": self.resolver_type,
                "reference_present": True,
                "network_call_performed": False,
            },
        )
