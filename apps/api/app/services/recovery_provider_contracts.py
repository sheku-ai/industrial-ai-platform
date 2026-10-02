from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_type: str
    resource_type: str
    provider_reference: str | None = None
    storage_location_masked: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum: str | None = None
    verification_status: str = "pending"
    metadata_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationDescriptor:
    verification_type: str
    status: str
    checks: dict[str, bool]
    evidence_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackupProviderRequest:
    provider_type: str
    provider_reference: str | None
    scope: str
    organization_id: str | None
    backup_type: str
    configuration_payload: dict[str, Any]


@dataclass(frozen=True)
class BackupProviderResult:
    accepted: bool
    status: str
    provider_execution_id: str | None = None
    blockers: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RestoreProviderRequest:
    provider_type: str
    provider_reference: str | None
    scope: str
    organization_id: str | None
    restore_target_type: str
    restore_target_reference: str | None
    destructive_operation: bool
    configuration_payload: dict[str, Any]


@dataclass(frozen=True)
class RestoreProviderResult:
    accepted: bool
    status: str
    provider_execution_id: str | None = None
    blockers: tuple[dict[str, Any], ...] = ()


class RecoveryProvider(Protocol):
    provider_type: str

    def plan_backup(self, request: BackupProviderRequest) -> BackupProviderResult: ...

    def register_backup_result(self, request: BackupProviderRequest) -> BackupProviderResult: ...

    def describe_backup(self, provider_execution_id: str) -> dict[str, Any]: ...

    def plan_restore(self, request: RestoreProviderRequest) -> RestoreProviderResult: ...

    def register_restore_result(self, request: RestoreProviderRequest) -> RestoreProviderResult: ...

    def describe_restore(self, provider_execution_id: str) -> dict[str, Any]: ...


class ExternalEvidenceRecoveryProvider:
    provider_type = "external_evidence"

    def plan_backup(self, request: BackupProviderRequest) -> BackupProviderResult:
        return BackupProviderResult(accepted=True, status="registration_required")

    def register_backup_result(self, request: BackupProviderRequest) -> BackupProviderResult:
        return BackupProviderResult(accepted=True, status="registered")

    def describe_backup(self, provider_execution_id: str) -> dict[str, Any]:
        return {"provider_execution_id": provider_execution_id, "execution_source": "external_evidence"}

    def plan_restore(self, request: RestoreProviderRequest) -> RestoreProviderResult:
        if request.destructive_operation:
            return RestoreProviderResult(accepted=True, status="approval_required")
        return RestoreProviderResult(accepted=True, status="registration_required")

    def register_restore_result(self, request: RestoreProviderRequest) -> RestoreProviderResult:
        return RestoreProviderResult(accepted=True, status="registered")

    def describe_restore(self, provider_execution_id: str) -> dict[str, Any]:
        return {"provider_execution_id": provider_execution_id, "execution_source": "external_evidence"}


class ManualRegistrationRecoveryProvider(ExternalEvidenceRecoveryProvider):
    provider_type = "manual_registration"


class FilesystemRecoveryProvider(ExternalEvidenceRecoveryProvider):
    provider_type = "filesystem"

    def describe_backup(self, provider_execution_id: str) -> dict[str, Any]:
        return {
            "provider_execution_id": provider_execution_id,
            "execution_source": "persistent_filesystem",
        }


class DisabledRecoveryProvider:
    provider_type = "disabled"

    def _blocked(self) -> BackupProviderResult:
        return BackupProviderResult(
            accepted=False,
            status="blocked",
            blockers=({"code": "RECOVERY_PROVIDER_DISABLED", "message": "Recovery provider is disabled."},),
        )

    def plan_backup(self, request: BackupProviderRequest) -> BackupProviderResult:
        return self._blocked()

    def register_backup_result(self, request: BackupProviderRequest) -> BackupProviderResult:
        return self._blocked()

    def describe_backup(self, provider_execution_id: str) -> dict[str, Any]:
        return {"provider_execution_id": provider_execution_id, "status": "disabled"}

    def plan_restore(self, request: RestoreProviderRequest) -> RestoreProviderResult:
        return RestoreProviderResult(
            accepted=False,
            status="blocked",
            blockers=({"code": "RECOVERY_PROVIDER_DISABLED", "message": "Recovery provider is disabled."},),
        )

    def register_restore_result(self, request: RestoreProviderRequest) -> RestoreProviderResult:
        return self.plan_restore(request)

    def describe_restore(self, provider_execution_id: str) -> dict[str, Any]:
        return {"provider_execution_id": provider_execution_id, "status": "disabled"}


def get_recovery_provider(provider_type: str) -> RecoveryProvider:
    normalized = (provider_type or "disabled").strip().lower()
    if normalized == "external_evidence":
        return ExternalEvidenceRecoveryProvider()
    if normalized == "manual_registration":
        return ManualRegistrationRecoveryProvider()
    if normalized == "filesystem":
        return FilesystemRecoveryProvider()
    return DisabledRecoveryProvider()
