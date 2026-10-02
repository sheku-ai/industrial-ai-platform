from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recovery import (
    BackupArtifactEvidence,
    BackupExecution,
    RecoveryEvidence,
    RecoveryPolicy,
    RestoreExecution,
    RestoreVerification,
)


class RecoveryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def scope_criteria(model: Any, scope: str, organization_id: uuid.UUID | None) -> list[Any]:
        criteria = [model.scope == scope]
        if organization_id is None:
            criteria.append(model.organization_id.is_(None))
        else:
            criteria.append(model.organization_id == organization_id)
        return criteria

    def get_policy(self, policy_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None) -> RecoveryPolicy | None:
        return self.db.scalar(
            select(RecoveryPolicy).where(
                RecoveryPolicy.id == policy_id,
                *self.scope_criteria(RecoveryPolicy, scope, organization_id),
            )
        )

    def list_policies(self, scope: str, organization_id: uuid.UUID | None) -> list[RecoveryPolicy]:
        return list(
            self.db.scalars(
                select(RecoveryPolicy)
                .where(*self.scope_criteria(RecoveryPolicy, scope, organization_id))
                .order_by(RecoveryPolicy.created_at.desc())
            ).all()
        )

    def active_policy(self, scope: str, organization_id: uuid.UUID | None) -> RecoveryPolicy | None:
        return self.db.scalar(
            select(RecoveryPolicy)
            .where(*self.scope_criteria(RecoveryPolicy, scope, organization_id), RecoveryPolicy.status == "active")
            .order_by(RecoveryPolicy.activated_at.desc().nullslast(), RecoveryPolicy.created_at.desc())
            .limit(1)
        )

    def policies_for_activation(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        policy_id: uuid.UUID,
    ) -> list[RecoveryPolicy]:
        return list(
            self.db.scalars(
                select(RecoveryPolicy)
                .where(
                    *self.scope_criteria(RecoveryPolicy, scope, organization_id),
                    (RecoveryPolicy.id == policy_id) | (RecoveryPolicy.status == "active"),
                )
                .order_by(RecoveryPolicy.status.asc(), RecoveryPolicy.created_at.asc())
                .with_for_update()
            ).all()
        )

    def find_backup_by_idempotency(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        provider_type: str,
        input_hash: str,
        idempotency_key: str,
    ) -> BackupExecution | None:
        return self.db.scalar(
            select(BackupExecution)
            .where(
                *self.scope_criteria(BackupExecution, scope, organization_id),
                BackupExecution.provider_type == provider_type,
                BackupExecution.input_hash == input_hash,
                BackupExecution.idempotency_key == idempotency_key,
            )
            .order_by(BackupExecution.created_at.desc())
        )

    def backup_idempotency_conflict(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        provider_type: str,
        input_hash: str,
        idempotency_key: str,
    ) -> bool:
        return (
            self.db.scalar(
                select(BackupExecution.id)
                .where(
                    *self.scope_criteria(BackupExecution, scope, organization_id),
                    BackupExecution.provider_type == provider_type,
                    BackupExecution.input_hash != input_hash,
                    BackupExecution.idempotency_key == idempotency_key,
                )
                .limit(1)
            )
            is not None
        )

    def get_backup(self, backup_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None) -> BackupExecution | None:
        return self.db.scalar(
            select(BackupExecution).where(
                BackupExecution.id == backup_id,
                *self.scope_criteria(BackupExecution, scope, organization_id),
            )
        )

    def list_backups(self, scope: str, organization_id: uuid.UUID | None) -> list[BackupExecution]:
        return list(
            self.db.scalars(
                select(BackupExecution)
                .where(*self.scope_criteria(BackupExecution, scope, organization_id))
                .order_by(BackupExecution.requested_at.desc())
            ).all()
        )

    def latest_completed_backup(self, scope: str, organization_id: uuid.UUID | None) -> BackupExecution | None:
        return self.db.scalar(
            select(BackupExecution)
            .where(
                *self.scope_criteria(BackupExecution, scope, organization_id),
                BackupExecution.status == "completed",
            )
            .order_by(BackupExecution.completed_at.desc().nullslast(), BackupExecution.created_at.desc())
            .limit(1)
        )

    def backup_completion_evidence(self, backup_id: uuid.UUID) -> RecoveryEvidence | None:
        return self.db.scalar(
            select(RecoveryEvidence)
            .where(
                RecoveryEvidence.evidence_type == "backup_execution_completed",
                RecoveryEvidence.source_entity_type == "backup_execution",
                RecoveryEvidence.source_entity_id == str(backup_id),
            )
            .order_by(RecoveryEvidence.observed_at.desc())
            .limit(1)
        )

    def get_evidence(self, evidence_id: uuid.UUID) -> RecoveryEvidence | None:
        return self.db.get(RecoveryEvidence, evidence_id)

    def latest_completed_backup_for_policy(
        self,
        policy_id: uuid.UUID,
        scope: str,
        organization_id: uuid.UUID | None,
    ) -> BackupExecution | None:
        return self.db.scalar(
            select(BackupExecution)
            .where(
                *self.scope_criteria(BackupExecution, scope, organization_id),
                BackupExecution.policy_id == policy_id,
                BackupExecution.status == "completed",
            )
            .order_by(BackupExecution.completed_at.desc().nullslast(), BackupExecution.created_at.desc())
            .limit(1)
        )

    def artifacts_for_backup(self, backup_id: uuid.UUID) -> list[BackupArtifactEvidence]:
        return list(
            self.db.scalars(
                select(BackupArtifactEvidence)
                .where(BackupArtifactEvidence.backup_execution_id == backup_id)
                .order_by(BackupArtifactEvidence.resource_type.asc(), BackupArtifactEvidence.created_at.desc())
            ).all()
        )

    def find_restore_by_idempotency(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        provider_type: str,
        input_hash: str,
        idempotency_key: str,
    ) -> RestoreExecution | None:
        return self.db.scalar(
            select(RestoreExecution)
            .where(
                *self.scope_criteria(RestoreExecution, scope, organization_id),
                RestoreExecution.provider_type == provider_type,
                RestoreExecution.input_hash == input_hash,
                RestoreExecution.idempotency_key == idempotency_key,
            )
            .order_by(RestoreExecution.created_at.desc())
        )

    def restore_idempotency_conflict(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        provider_type: str,
        input_hash: str,
        idempotency_key: str,
    ) -> bool:
        return (
            self.db.scalar(
                select(RestoreExecution.id)
                .where(
                    *self.scope_criteria(RestoreExecution, scope, organization_id),
                    RestoreExecution.provider_type == provider_type,
                    RestoreExecution.input_hash != input_hash,
                    RestoreExecution.idempotency_key == idempotency_key,
                )
                .limit(1)
            )
            is not None
        )

    def get_restore(
        self, restore_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None
    ) -> RestoreExecution | None:
        return self.db.scalar(
            select(RestoreExecution).where(
                RestoreExecution.id == restore_id,
                *self.scope_criteria(RestoreExecution, scope, organization_id),
            )
        )

    def list_restores(self, scope: str, organization_id: uuid.UUID | None) -> list[RestoreExecution]:
        return list(
            self.db.scalars(
                select(RestoreExecution)
                .where(*self.scope_criteria(RestoreExecution, scope, organization_id))
                .order_by(RestoreExecution.requested_at.desc())
            ).all()
        )

    def latest_completed_restore(self, scope: str, organization_id: uuid.UUID | None) -> RestoreExecution | None:
        return self.db.scalar(
            select(RestoreExecution)
            .where(
                *self.scope_criteria(RestoreExecution, scope, organization_id),
                RestoreExecution.status == "completed",
            )
            .order_by(RestoreExecution.completed_at.desc().nullslast(), RestoreExecution.created_at.desc())
            .limit(1)
        )

    def latest_completed_restore_for_policy(
        self,
        policy_id: uuid.UUID,
        scope: str,
        organization_id: uuid.UUID | None,
    ) -> RestoreExecution | None:
        return self.db.scalar(
            select(RestoreExecution)
            .join(BackupExecution, BackupExecution.id == RestoreExecution.backup_execution_id)
            .where(
                *self.scope_criteria(RestoreExecution, scope, organization_id),
                RestoreExecution.policy_id == policy_id,
                BackupExecution.policy_id == policy_id,
                BackupExecution.scope == RestoreExecution.scope,
                BackupExecution.organization_id.is_(None)
                if organization_id is None
                else BackupExecution.organization_id == organization_id,
                RestoreExecution.status == "completed",
            )
            .order_by(RestoreExecution.completed_at.desc().nullslast(), RestoreExecution.created_at.desc())
            .limit(1)
        )

    def get_verification(self, verification_id: uuid.UUID) -> RestoreVerification | None:
        return self.db.get(RestoreVerification, verification_id)

    def verifications_for_restore(self, restore_id: uuid.UUID) -> list[RestoreVerification]:
        return list(
            self.db.scalars(
                select(RestoreVerification)
                .where(RestoreVerification.restore_execution_id == restore_id)
                .order_by(RestoreVerification.created_at.desc())
            ).all()
        )

    def latest_passed_verification(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
    ) -> RestoreVerification | None:
        return self.db.scalar(
            select(RestoreVerification)
            .join(RestoreExecution, RestoreExecution.id == RestoreVerification.restore_execution_id)
            .where(
                *self.scope_criteria(RestoreExecution, scope, organization_id),
                RestoreExecution.status == "completed",
                RestoreVerification.status == "passed",
            )
            .order_by(RestoreVerification.completed_at.desc().nullslast(), RestoreVerification.created_at.desc())
            .limit(1)
        )

    def latest_passed_verification_for_restore(self, restore_id: uuid.UUID) -> RestoreVerification | None:
        return self.db.scalar(
            select(RestoreVerification)
            .where(
                RestoreVerification.restore_execution_id == restore_id,
                RestoreVerification.status == "passed",
            )
            .order_by(RestoreVerification.completed_at.desc().nullslast(), RestoreVerification.created_at.desc())
            .limit(1)
        )

    def latest_evidence(self, scope: str, organization_id: uuid.UUID | None) -> list[RecoveryEvidence]:
        return list(
            self.db.scalars(
                select(RecoveryEvidence)
                .where(*self.scope_criteria(RecoveryEvidence, scope, organization_id))
                .order_by(RecoveryEvidence.evidence_type.asc(), RecoveryEvidence.observed_at.desc())
            ).all()
        )
