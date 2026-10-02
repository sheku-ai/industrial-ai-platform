from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.production_acceptance import (
    ProductionAcceptanceEvidence,
    ProductionAcceptanceGateResult,
    ProductionAcceptanceRun,
)


class ProductionAcceptanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def scope_criteria(scope: str, organization_id: uuid.UUID | None) -> list[object]:
        criteria: list[object] = [ProductionAcceptanceRun.scope == scope]
        if organization_id is None:
            criteria.append(ProductionAcceptanceRun.organization_id.is_(None))
        else:
            criteria.append(ProductionAcceptanceRun.organization_id == organization_id)
        return criteria

    def find_idempotent_run(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        contract_version: str,
        input_hash: str,
        idempotency_key: str,
    ) -> ProductionAcceptanceRun | None:
        criteria = self.scope_criteria(scope, organization_id)
        criteria.extend(
            [
                ProductionAcceptanceRun.contract_version == contract_version,
                ProductionAcceptanceRun.input_hash == input_hash,
                ProductionAcceptanceRun.idempotency_key == idempotency_key,
            ]
        )
        return self.db.scalar(
            select(ProductionAcceptanceRun).where(*criteria).order_by(ProductionAcceptanceRun.created_at.desc())
        )

    def has_idempotency_conflict(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        contract_version: str,
        input_hash: str,
        idempotency_key: str,
    ) -> bool:
        criteria = self.scope_criteria(scope, organization_id)
        criteria.extend(
            [
                ProductionAcceptanceRun.contract_version == contract_version,
                ProductionAcceptanceRun.idempotency_key == idempotency_key,
                ProductionAcceptanceRun.input_hash != input_hash,
            ]
        )
        return self.db.scalar(select(ProductionAcceptanceRun.id).where(*criteria).limit(1)) is not None

    def get_run(
        self,
        run_id: uuid.UUID,
        *,
        scope: str | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> ProductionAcceptanceRun | None:
        criteria: list[object] = [ProductionAcceptanceRun.id == run_id]
        if scope is not None:
            criteria.extend(self.scope_criteria(scope, organization_id))
        return self.db.scalar(select(ProductionAcceptanceRun).where(*criteria))

    def latest_completed(
        self,
        *,
        scope: str,
        organization_id: uuid.UUID | None,
        terminal_statuses: set[str],
    ) -> ProductionAcceptanceRun | None:
        criteria = self.scope_criteria(scope, organization_id)
        criteria.append(ProductionAcceptanceRun.status.in_(tuple(terminal_statuses)))
        return self.db.scalar(
            select(ProductionAcceptanceRun)
            .where(*criteria)
            .order_by(
                ProductionAcceptanceRun.completed_at.desc().nullslast(), ProductionAcceptanceRun.created_at.desc()
            )
            .limit(1)
        )

    def clear_evidence(self, run_id: uuid.UUID) -> None:
        self.db.execute(delete(ProductionAcceptanceEvidence).where(ProductionAcceptanceEvidence.run_id == run_id))

    def clear_gate_results(self, run_id: uuid.UUID) -> None:
        self.db.execute(delete(ProductionAcceptanceGateResult).where(ProductionAcceptanceGateResult.run_id == run_id))

    def list_gate_results(self, run_id: uuid.UUID) -> list[ProductionAcceptanceGateResult]:
        return list(
            self.db.scalars(
                select(ProductionAcceptanceGateResult)
                .where(ProductionAcceptanceGateResult.run_id == run_id)
                .order_by(ProductionAcceptanceGateResult.domain.asc(), ProductionAcceptanceGateResult.gate_code.asc())
            ).all()
        )

    def list_evidence(self, run_id: uuid.UUID) -> list[ProductionAcceptanceEvidence]:
        return list(
            self.db.scalars(
                select(ProductionAcceptanceEvidence)
                .where(ProductionAcceptanceEvidence.run_id == run_id)
                .order_by(ProductionAcceptanceEvidence.evidence_type.asc())
            ).all()
        )
