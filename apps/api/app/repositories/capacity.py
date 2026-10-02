from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.capacity import (
    CapacityAcceptance,
    CapacityEvaluation,
    CapacityEvidence,
    CapacityFinding,
    CapacityProfile,
    CapacityRecommendation,
    HistoricalCapacityTrend,
    LoadTestExecution,
    LoadTestResult,
)


def _scope(model: object, scope: str, organization_id: uuid.UUID | None):
    return (
        model.scope == scope,
        model.organization_id.is_(None) if organization_id is None else model.organization_id == organization_id,
    )


class CapacityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row):
        self.db.add(row)
        self.db.flush()
        return row

    def get_profile(self, profile_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(CapacityProfile).where(
                CapacityProfile.id == profile_id, *_scope(CapacityProfile, scope, organization_id)
            )
        )

    def find_profile(self, scope: str, organization_id: uuid.UUID | None, profile_code: str, version: str):
        return self.db.scalar(
            select(CapacityProfile).where(
                *_scope(CapacityProfile, scope, organization_id),
                CapacityProfile.profile_code == profile_code,
                CapacityProfile.version == version,
            )
        )

    def active_profile(self, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(CapacityProfile)
            .where(*_scope(CapacityProfile, scope, organization_id), CapacityProfile.status == "active")
            .order_by(CapacityProfile.activated_at.desc().nullslast(), CapacityProfile.updated_at.desc())
            .limit(1)
        )

    def list_profiles(self, scope: str, organization_id: uuid.UUID | None):
        return list(
            self.db.scalars(
                select(CapacityProfile)
                .where(*_scope(CapacityProfile, scope, organization_id))
                .order_by(CapacityProfile.updated_at.desc())
            ).all()
        )

    def deactivate_profiles(self, scope: str, organization_id: uuid.UUID | None) -> list[CapacityProfile]:
        deactivated: list[CapacityProfile] = []
        for row in self.list_profiles(scope, organization_id):
            if row.status == "active":
                row.status = "inactive"
                deactivated.append(row)
        return deactivated

    def find_load_test(self, scope: str, organization_id: uuid.UUID | None, idempotency_key: str):
        return self.db.scalar(
            select(LoadTestExecution).where(
                *_scope(LoadTestExecution, scope, organization_id),
                LoadTestExecution.idempotency_key == idempotency_key,
            )
        )

    def get_load_test(self, execution_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(LoadTestExecution).where(
                LoadTestExecution.id == execution_id,
                *_scope(LoadTestExecution, scope, organization_id),
            )
        )

    def list_results(self, execution_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(LoadTestResult)
                .where(LoadTestResult.load_test_execution_id == execution_id)
                .order_by(LoadTestResult.metric_code.asc())
            ).all()
        )

    def find_result(self, execution_id: uuid.UUID, metric_code: str):
        return self.db.scalar(
            select(LoadTestResult).where(
                LoadTestResult.load_test_execution_id == execution_id,
                LoadTestResult.metric_code == metric_code,
            )
        )

    def find_evaluation(self, scope: str, organization_id: uuid.UUID | None, idempotency_key: str):
        return self.db.scalar(
            select(CapacityEvaluation).where(
                *_scope(CapacityEvaluation, scope, organization_id),
                CapacityEvaluation.idempotency_key == idempotency_key,
            )
        )

    def get_evaluation(self, evaluation_id: uuid.UUID, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(CapacityEvaluation).where(
                CapacityEvaluation.id == evaluation_id,
                *_scope(CapacityEvaluation, scope, organization_id),
            )
        )

    def latest_evaluation(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        profile_id: uuid.UUID | None = None,
    ):
        statement = select(CapacityEvaluation).where(*_scope(CapacityEvaluation, scope, organization_id))
        if profile_id is not None:
            statement = statement.where(CapacityEvaluation.profile_id == profile_id)
        return self.db.scalar(statement.order_by(CapacityEvaluation.evaluated_at.desc()).limit(1))

    def findings(self, evaluation_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(CapacityFinding)
                .where(CapacityFinding.evaluation_id == evaluation_id)
                .order_by(CapacityFinding.severity.asc(), CapacityFinding.created_at.asc())
            ).all()
        )

    def recommendations(self, evaluation_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(CapacityRecommendation)
                .where(CapacityRecommendation.evaluation_id == evaluation_id)
                .order_by(CapacityRecommendation.priority.asc(), CapacityRecommendation.created_at.asc())
            ).all()
        )

    def evidence(self, evaluation_id: uuid.UUID):
        return list(
            self.db.scalars(
                select(CapacityEvidence)
                .where(CapacityEvidence.evaluation_id == evaluation_id)
                .order_by(CapacityEvidence.observed_at.desc())
            ).all()
        )

    def find_evidence(self, evaluation_id: uuid.UUID, evidence_code: str, evidence_hash: str):
        return self.db.scalar(
            select(CapacityEvidence).where(
                CapacityEvidence.evaluation_id == evaluation_id,
                CapacityEvidence.evidence_code == evidence_code,
                CapacityEvidence.evidence_hash == evidence_hash,
            )
        )

    def trends(self, scope: str, organization_id: uuid.UUID | None, limit: int = 500):
        return list(
            self.db.scalars(
                select(HistoricalCapacityTrend)
                .where(*_scope(HistoricalCapacityTrend, scope, organization_id))
                .order_by(HistoricalCapacityTrend.captured_at.desc(), HistoricalCapacityTrend.metric_code.asc())
                .limit(limit)
            ).all()
        )

    def acceptance(self, evaluation_id: uuid.UUID):
        return self.db.scalar(select(CapacityAcceptance).where(CapacityAcceptance.evaluation_id == evaluation_id))

    def latest_acceptance(self, scope: str, organization_id: uuid.UUID | None):
        return self.db.scalar(
            select(CapacityAcceptance)
            .where(*_scope(CapacityAcceptance, scope, organization_id))
            .order_by(CapacityAcceptance.accepted_at.desc())
            .limit(1)
        )
