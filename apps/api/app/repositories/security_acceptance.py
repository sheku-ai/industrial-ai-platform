from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security_acceptance import SecurityEvidence, SecurityFinding, SecurityPolicyRuntime


class SecurityAcceptanceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def scope_criteria(model: Any, scope: str, organization_id: uuid.UUID | None) -> list[Any]:
        criteria = [model.scope == scope]
        criteria.append(
            model.organization_id.is_(None) if organization_id is None else model.organization_id == organization_id
        )
        return criteria

    def list_policies(self, scope: str, organization_id: uuid.UUID | None) -> list[SecurityPolicyRuntime]:
        return list(
            self.db.scalars(
                select(SecurityPolicyRuntime)
                .where(*self.scope_criteria(SecurityPolicyRuntime, scope, organization_id))
                .order_by(SecurityPolicyRuntime.created_at.desc())
            ).all()
        )

    def get_policy(
        self,
        policy_id: uuid.UUID,
        scope: str,
        organization_id: uuid.UUID | None,
    ) -> SecurityPolicyRuntime | None:
        return self.db.scalar(
            select(SecurityPolicyRuntime).where(
                SecurityPolicyRuntime.id == policy_id,
                *self.scope_criteria(SecurityPolicyRuntime, scope, organization_id),
            )
        )

    def active_policy(self, scope: str, organization_id: uuid.UUID | None) -> SecurityPolicyRuntime | None:
        return self.db.scalar(
            select(SecurityPolicyRuntime)
            .where(
                *self.scope_criteria(SecurityPolicyRuntime, scope, organization_id),
                SecurityPolicyRuntime.status == "active",
            )
            .order_by(SecurityPolicyRuntime.activated_at.desc().nullslast(), SecurityPolicyRuntime.created_at.desc())
            .limit(1)
        )

    def list_findings(self, scope: str, organization_id: uuid.UUID | None) -> list[SecurityFinding]:
        return list(
            self.db.scalars(
                select(SecurityFinding)
                .where(*self.scope_criteria(SecurityFinding, scope, organization_id))
                .order_by(SecurityFinding.last_observed_at.desc(), SecurityFinding.id.desc())
            ).all()
        )

    def find_finding(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        rule: str,
        source_runtime: str,
        source_entity_type: str,
        source_entity_id: str | None,
        evidence_hash: str,
    ) -> SecurityFinding | None:
        return self.db.scalar(
            select(SecurityFinding)
            .where(
                *self.scope_criteria(SecurityFinding, scope, organization_id),
                SecurityFinding.rule == rule,
                SecurityFinding.source_runtime == source_runtime,
                SecurityFinding.source_entity_type == source_entity_type,
                SecurityFinding.source_entity_id == source_entity_id,
                SecurityFinding.evidence_hash == evidence_hash,
            )
            .order_by(SecurityFinding.created_at.desc())
            .limit(1)
        )

    def list_evidence(self, scope: str, organization_id: uuid.UUID | None) -> list[SecurityEvidence]:
        return list(
            self.db.scalars(
                select(SecurityEvidence)
                .where(*self.scope_criteria(SecurityEvidence, scope, organization_id))
                .order_by(SecurityEvidence.observed_at.desc(), SecurityEvidence.created_at.desc())
            ).all()
        )

    def find_evidence(
        self,
        scope: str,
        organization_id: uuid.UUID | None,
        evidence_type: str,
        source_runtime: str,
        source_entity_type: str,
        source_entity_id: str | None,
        evidence_hash: str,
    ) -> SecurityEvidence | None:
        return self.db.scalar(
            select(SecurityEvidence)
            .where(
                *self.scope_criteria(SecurityEvidence, scope, organization_id),
                SecurityEvidence.evidence_type == evidence_type,
                SecurityEvidence.source_runtime == source_runtime,
                SecurityEvidence.source_entity_type == source_entity_type,
                SecurityEvidence.source_entity_id == source_entity_id,
                SecurityEvidence.evidence_hash == evidence_hash,
            )
            .order_by(SecurityEvidence.created_at.desc())
            .limit(1)
        )
