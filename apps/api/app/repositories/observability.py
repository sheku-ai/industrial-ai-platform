from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.observability import (
    AvailabilityWindow,
    HealthAcceptance,
    HealthDomain,
    HealthEvaluation,
    HealthEvidence,
    HealthFinding,
    HealthHistory,
    ObservabilityHeartbeat,
    ObservabilityProfile,
    ObservedComponent,
    ObservedDependency,
    ObservedSignal,
)


def _scope(model: object, scope: str, organization_id: uuid.UUID | None):
    return (
        model.scope == scope,
        model.organization_id.is_(None) if organization_id is None else model.organization_id == organization_id,
    )


class ObservabilityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row):
        self.db.add(row)
        self.db.flush()
        return row

    def find_profile(self, scope: str, organization_id: uuid.UUID | None, profile_code: str, version: str):
        return self.db.scalar(
            select(ObservabilityProfile).where(
                *_scope(ObservabilityProfile, scope, organization_id),
                ObservabilityProfile.profile_code == profile_code,
                ObservabilityProfile.version == version,
            )
        )

    def get_profile(self, profile_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(ObservabilityProfile).where(
                ObservabilityProfile.id == profile_id,
                *_scope(ObservabilityProfile, scope, organization_id),
            )
        )

    def active_profile(self, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(ObservabilityProfile)
            .where(*_scope(ObservabilityProfile, scope, organization_id), ObservabilityProfile.status == "active")
            .order_by(ObservabilityProfile.activated_at.desc().nullslast(), ObservabilityProfile.updated_at.desc())
            .limit(1)
        )

    def list_profiles(self, scope: str, organization_id: uuid.UUID | None):
        return list(
            self.db.scalars(
                select(ObservabilityProfile)
                .where(*_scope(ObservabilityProfile, scope, organization_id))
                .order_by(ObservabilityProfile.updated_at.desc())
            ).all()
        )

    def deactivate_profiles(self, scope: str, organization_id: uuid.UUID | None):
        rows = []
        for row in self.list_profiles(scope, organization_id):
            if row.status == "active":
                row.status = "inactive"
                row.record_version += 1
                rows.append(row)
        return rows

    def find_domain(self, profile_id: uuid.UUID, domain_code: str, version: str):
        return self.db.scalar(
            select(HealthDomain).where(
                HealthDomain.profile_id == profile_id,
                HealthDomain.domain_code == domain_code,
                HealthDomain.version == version,
            )
        )

    def get_domain(self, domain_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(HealthDomain).where(HealthDomain.id == domain_id, *_scope(HealthDomain, scope, organization_id))
        )

    def list_domains(self, profile_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(HealthDomain)
                .where(HealthDomain.profile_id == profile_id)
                .order_by(HealthDomain.updated_at.desc(), HealthDomain.domain_code.asc())
            ).all()
        )

    def find_component(self, domain_id: uuid.UUID, component_code: str, version: str):
        return self.db.scalar(
            select(ObservedComponent).where(
                ObservedComponent.health_domain_id == domain_id,
                ObservedComponent.component_code == component_code,
                ObservedComponent.version == version,
            )
        )

    def get_component(self, component_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(ObservedComponent).where(
                ObservedComponent.id == component_id, *_scope(ObservedComponent, scope, organization_id)
            )
        )

    def list_components(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        profile_id: uuid.UUID | None = None,
    ):
        statement = select(ObservedComponent).where(*_scope(ObservedComponent, scope, organization_id))
        if profile_id is not None:
            statement = statement.join(
                HealthDomain,
                HealthDomain.id == ObservedComponent.health_domain_id,
            ).where(HealthDomain.profile_id == profile_id)
        return list(
            self.db.scalars(
                statement.order_by(ObservedComponent.updated_at.desc(), ObservedComponent.component_code.asc())
            ).all()
        )

    def find_dependency(self, component_id: uuid.UUID, dependency_code: str, version: str):
        return self.db.scalar(
            select(ObservedDependency).where(
                ObservedDependency.component_id == component_id,
                ObservedDependency.dependency_code == dependency_code,
                ObservedDependency.version == version,
            )
        )

    def list_dependencies(self, component_ids: list[uuid.UUID]):
        if not component_ids:
            return []
        return list(
            self.db.scalars(
                select(ObservedDependency)
                .where(ObservedDependency.component_id.in_(component_ids))
                .order_by(ObservedDependency.observed_at.desc(), ObservedDependency.dependency_code.asc())
            ).all()
        )

    def find_signal(self, component_id: uuid.UUID, idempotency_key: str):
        return self.db.scalar(
            select(ObservedSignal).where(
                ObservedSignal.component_id == component_id, ObservedSignal.idempotency_key == idempotency_key
            )
        )

    def list_signals(self, component_ids: list[uuid.UUID], limit: int = 1000):
        if not component_ids:
            return []
        return list(
            self.db.scalars(
                select(ObservedSignal)
                .where(ObservedSignal.component_id.in_(component_ids))
                .order_by(ObservedSignal.observed_at.desc())
                .limit(limit)
            ).all()
        )

    def find_heartbeat(self, component_id: uuid.UUID, idempotency_key: str):
        return self.db.scalar(
            select(ObservabilityHeartbeat).where(
                ObservabilityHeartbeat.component_id == component_id,
                ObservabilityHeartbeat.idempotency_key == idempotency_key,
            )
        )

    def list_heartbeats(self, component_ids: list[uuid.UUID], limit: int = 1000):
        if not component_ids:
            return []
        return list(
            self.db.scalars(
                select(ObservabilityHeartbeat)
                .where(ObservabilityHeartbeat.component_id.in_(component_ids))
                .order_by(ObservabilityHeartbeat.observed_at.desc())
                .limit(limit)
            ).all()
        )

    def find_availability(self, component_id: uuid.UUID, idempotency_key: str):
        return self.db.scalar(
            select(AvailabilityWindow).where(
                AvailabilityWindow.component_id == component_id, AvailabilityWindow.idempotency_key == idempotency_key
            )
        )

    def list_availability(self, component_ids: list[uuid.UUID], limit: int = 1000):
        if not component_ids:
            return []
        return list(
            self.db.scalars(
                select(AvailabilityWindow)
                .where(AvailabilityWindow.component_id.in_(component_ids))
                .order_by(AvailabilityWindow.window_end.desc())
                .limit(limit)
            ).all()
        )

    def find_evaluation(self, scope: str, organization_id: uuid.UUID | None, idempotency_key: str):
        return self.db.scalar(
            select(HealthEvaluation).where(
                *_scope(HealthEvaluation, scope, organization_id), HealthEvaluation.idempotency_key == idempotency_key
            )
        )

    def get_evaluation(self, evaluation_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(HealthEvaluation).where(
                HealthEvaluation.id == evaluation_id, *_scope(HealthEvaluation, scope, organization_id)
            )
        )

    def latest_evaluation(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        profile_id: uuid.UUID | None = None,
    ):
        statement = select(HealthEvaluation).where(*_scope(HealthEvaluation, scope, organization_id))
        if profile_id is not None:
            statement = statement.where(HealthEvaluation.profile_id == profile_id)
        return self.db.scalar(statement.order_by(HealthEvaluation.evaluated_at.desc()).limit(1))

    def findings(self, evaluation_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(HealthFinding)
                .where(HealthFinding.evaluation_id == evaluation_id)
                .order_by(HealthFinding.severity.desc(), HealthFinding.created_at.asc())
            ).all()
        )

    def evidence(self, evaluation_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(HealthEvidence)
                .where(HealthEvidence.evaluation_id == evaluation_id)
                .order_by(HealthEvidence.evaluation_timestamp.desc())
            ).all()
        )

    def acceptance(self, evaluation_id: uuid.UUID):
        return self.db.scalar(select(HealthAcceptance).where(HealthAcceptance.evaluation_id == evaluation_id))

    def latest_acceptance(self, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(HealthAcceptance)
            .where(*_scope(HealthAcceptance, scope, organization_id))
            .order_by(HealthAcceptance.accepted_at.desc())
            .limit(1)
        )

    def history(self, scope: str, organization_id: uuid.UUID | None, limit: int = 200):
        return list(
            self.db.scalars(
                select(HealthHistory)
                .where(*_scope(HealthHistory, scope, organization_id))
                .order_by(HealthHistory.captured_at.desc())
                .limit(limit)
            ).all()
        )
