from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operational_observability import (
    BoundedRetryAttempt,
    FailureRecoveryAction,
    OperationalEvidence,
    OperationalExecution,
    OperationalIncident,
    RuntimeComponent,
    RuntimeObservation,
)


class OperationalObservabilityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_component(
        self, component_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None
    ) -> RuntimeComponent | None:
        return self.db.scalar(
            select(RuntimeComponent).where(
                RuntimeComponent.id == component_id,
                RuntimeComponent.scope == scope,
                RuntimeComponent.organization_id.is_(None)
                if organization_id is None
                else RuntimeComponent.organization_id == organization_id,
            )
        )

    def find_component(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        component_code: str,
        instance_id: str,
    ) -> RuntimeComponent | None:
        return self.db.scalar(
            select(RuntimeComponent).where(
                RuntimeComponent.scope == scope,
                RuntimeComponent.organization_id.is_(None)
                if organization_id is None
                else RuntimeComponent.organization_id == organization_id,
                RuntimeComponent.component_code == component_code,
                RuntimeComponent.instance_id == instance_id,
            )
        )

    def list_components(self, scope: str, organization_id: uuid.UUID | None) -> list[RuntimeComponent]:
        return list(
            self.db.scalars(
                select(RuntimeComponent)
                .where(
                    RuntimeComponent.scope == scope,
                    RuntimeComponent.organization_id.is_(None)
                    if organization_id is None
                    else RuntimeComponent.organization_id == organization_id,
                )
                .order_by(RuntimeComponent.component_type.asc(), RuntimeComponent.component_code.asc())
            ).all()
        )

    def add_component(self, component: RuntimeComponent) -> RuntimeComponent:
        self.db.add(component)
        self.db.flush()
        return component

    def find_observation(
        self, component_id: uuid.UUID, observation_type: str, evidence_hash: str
    ) -> RuntimeObservation | None:
        return self.db.scalar(
            select(RuntimeObservation).where(
                RuntimeObservation.component_id == component_id,
                RuntimeObservation.observation_type == observation_type,
                RuntimeObservation.evidence_hash == evidence_hash,
            )
        )

    def list_observations(self, scope: str, organization_id: uuid.UUID | None) -> list[RuntimeObservation]:
        return list(
            self.db.scalars(
                select(RuntimeObservation)
                .where(
                    RuntimeObservation.scope == scope,
                    RuntimeObservation.organization_id.is_(None)
                    if organization_id is None
                    else RuntimeObservation.organization_id == organization_id,
                )
                .order_by(RuntimeObservation.observed_at.desc())
            ).all()
        )

    def add_observation(self, observation: RuntimeObservation) -> RuntimeObservation:
        self.db.add(observation)
        self.db.flush()
        return observation

    def find_execution(
        self, scope: str, organization_id: uuid.UUID | None, execution_type: str, key: str
    ) -> OperationalExecution | None:
        return self.db.scalar(
            select(OperationalExecution).where(
                OperationalExecution.scope == scope,
                OperationalExecution.organization_id.is_(None)
                if organization_id is None
                else OperationalExecution.organization_id == organization_id,
                OperationalExecution.execution_type == execution_type,
                OperationalExecution.idempotency_key == key,
            )
        )

    def get_execution(
        self, execution_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None
    ) -> OperationalExecution | None:
        return self.db.scalar(
            select(OperationalExecution).where(
                OperationalExecution.id == execution_id,
                OperationalExecution.scope == scope,
                OperationalExecution.organization_id.is_(None)
                if organization_id is None
                else OperationalExecution.organization_id == organization_id,
            )
        )

    def list_executions(self, scope: str, organization_id: uuid.UUID | None) -> list[OperationalExecution]:
        return list(
            self.db.scalars(
                select(OperationalExecution)
                .where(
                    OperationalExecution.scope == scope,
                    OperationalExecution.organization_id.is_(None)
                    if organization_id is None
                    else OperationalExecution.organization_id == organization_id,
                )
                .order_by(OperationalExecution.requested_at.desc())
            ).all()
        )

    def add_execution(self, execution: OperationalExecution) -> OperationalExecution:
        self.db.add(execution)
        self.db.flush()
        return execution

    def find_retry(self, execution_id: uuid.UUID, attempt_number: int) -> BoundedRetryAttempt | None:
        return self.db.scalar(
            select(BoundedRetryAttempt).where(
                BoundedRetryAttempt.operational_execution_id == execution_id,
                BoundedRetryAttempt.attempt_number == attempt_number,
            )
        )

    def list_retries(self, execution_id: uuid.UUID) -> list[BoundedRetryAttempt]:
        return list(
            self.db.scalars(
                select(BoundedRetryAttempt)
                .where(BoundedRetryAttempt.operational_execution_id == execution_id)
                .order_by(BoundedRetryAttempt.attempt_number.asc())
            ).all()
        )

    def get_retry(self, retry_id: uuid.UUID) -> BoundedRetryAttempt | None:
        return self.db.get(BoundedRetryAttempt, retry_id)

    def add_retry(self, retry: BoundedRetryAttempt) -> BoundedRetryAttempt:
        self.db.add(retry)
        self.db.flush()
        return retry

    def find_open_incident(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        incident_code: str,
        source_entity_type: str | None,
        source_entity_id: str | None,
    ) -> OperationalIncident | None:
        return self.db.scalar(
            select(OperationalIncident).where(
                OperationalIncident.scope == scope,
                OperationalIncident.organization_id.is_(None)
                if organization_id is None
                else OperationalIncident.organization_id == organization_id,
                OperationalIncident.incident_code == incident_code,
                OperationalIncident.source_entity_type == source_entity_type,
                OperationalIncident.source_entity_id == source_entity_id,
                OperationalIncident.status.in_(("open", "acknowledged", "recovering")),
            )
        )

    def get_incident(
        self, incident_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None
    ) -> OperationalIncident | None:
        return self.db.scalar(
            select(OperationalIncident).where(
                OperationalIncident.id == incident_id,
                OperationalIncident.scope == scope,
                OperationalIncident.organization_id.is_(None)
                if organization_id is None
                else OperationalIncident.organization_id == organization_id,
            )
        )

    def list_incidents(self, scope: str, organization_id: uuid.UUID | None) -> list[OperationalIncident]:
        return list(
            self.db.scalars(
                select(OperationalIncident)
                .where(
                    OperationalIncident.scope == scope,
                    OperationalIncident.organization_id.is_(None)
                    if organization_id is None
                    else OperationalIncident.organization_id == organization_id,
                )
                .order_by(OperationalIncident.last_observed_at.desc())
            ).all()
        )

    def add_incident(self, incident: OperationalIncident) -> OperationalIncident:
        self.db.add(incident)
        self.db.flush()
        return incident

    def find_recovery_action(
        self, incident_id: uuid.UUID, action_type: str, input_hash: str
    ) -> FailureRecoveryAction | None:
        return self.db.scalar(
            select(FailureRecoveryAction).where(
                FailureRecoveryAction.incident_id == incident_id,
                FailureRecoveryAction.action_type == action_type,
                FailureRecoveryAction.input_hash == input_hash,
            )
        )

    def get_recovery_action(self, action_id: uuid.UUID) -> FailureRecoveryAction | None:
        return self.db.get(FailureRecoveryAction, action_id)

    def list_recovery_actions(self, incident_id: uuid.UUID | None = None) -> list[FailureRecoveryAction]:
        statement = select(FailureRecoveryAction).order_by(FailureRecoveryAction.requested_at.desc())
        if incident_id is not None:
            statement = statement.where(FailureRecoveryAction.incident_id == incident_id)
        return list(self.db.scalars(statement).all())

    def add_recovery_action(self, action: FailureRecoveryAction) -> FailureRecoveryAction:
        self.db.add(action)
        self.db.flush()
        return action

    def find_evidence(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        evidence_type: str,
        source_entity_type: str,
        source_entity_id: str,
        evidence_hash: str,
    ) -> OperationalEvidence | None:
        return self.db.scalar(
            select(OperationalEvidence).where(
                OperationalEvidence.scope == scope,
                OperationalEvidence.organization_id.is_(None)
                if organization_id is None
                else OperationalEvidence.organization_id == organization_id,
                OperationalEvidence.evidence_type == evidence_type,
                OperationalEvidence.source_entity_type == source_entity_type,
                OperationalEvidence.source_entity_id == source_entity_id,
                OperationalEvidence.evidence_hash == evidence_hash,
            )
        )

    def list_evidence(self, scope: str, organization_id: uuid.UUID | None) -> list[OperationalEvidence]:
        return list(
            self.db.scalars(
                select(OperationalEvidence)
                .where(
                    OperationalEvidence.scope == scope,
                    OperationalEvidence.organization_id.is_(None)
                    if organization_id is None
                    else OperationalEvidence.organization_id == organization_id,
                )
                .order_by(OperationalEvidence.observed_at.desc())
            ).all()
        )

    def add_evidence(self, evidence: OperationalEvidence) -> OperationalEvidence:
        self.db.add(evidence)
        self.db.flush()
        return evidence
