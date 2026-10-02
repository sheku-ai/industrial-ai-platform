from __future__ import annotations

from app.secret_refs.base import SecretReference, SecretResolutionResult


class DisabledSecretResolver:
    @property
    def resolver_type(self) -> str:
        return "disabled"

    def resolve(self, reference: SecretReference) -> SecretResolutionResult:
        return SecretResolutionResult(
            status="disabled",
            value=None,
            error_code="secret_reference_unresolved",
            message="Secret resolution is not configured.",
            metadata={
                "resolver_type": self.resolver_type,
                "reference_present": bool(reference.reference),
                "network_call_performed": False,
            },
        )
