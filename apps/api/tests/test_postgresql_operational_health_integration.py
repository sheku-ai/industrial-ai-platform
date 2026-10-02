from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.models.runtime import RuntimeExecution
from app.services.operational_health import OperationalHealthService
from tests.integration_support.postgresql_fixtures import (
    create_integration_organization,
    delete_integration_organization,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="explicit PostgreSQL integration environment is required",
)


def test_operational_health_is_tenant_scoped_and_deterministic():
    assert DATABASE_URL is not None

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    first_organization_id = uuid4()
    second_organization_id = uuid4()
    now = datetime.now(UTC)

    try:
        create_integration_organization(session, organization_id=first_organization_id)
        create_integration_organization(session, organization_id=second_organization_id)

        first_execution = RuntimeExecution(
            id=uuid4(),
            organization_id=first_organization_id,
            execution_type="integration.health",
            subject_type="integration.fixture",
            subject_id=uuid4(),
            status="pending",
            requested_at=now,
            available_at=now,
            input_payload={},
            policy_snapshot={},
            metrics={},
        )
        second_execution = RuntimeExecution(
            id=uuid4(),
            organization_id=second_organization_id,
            execution_type="integration.health",
            subject_type="integration.fixture",
            subject_id=uuid4(),
            status="dead_lettered",
            requested_at=now,
            available_at=now,
            started_at=now,
            finished_at=now,
            error_code="integration.dead_letter",
            input_payload={},
            policy_snapshot={},
            metrics={},
        )
        session.add_all([first_execution, second_execution])
        session.commit()

        first = OperationalHealthService(session).get_snapshot(first_organization_id)
        second = OperationalHealthService(session).get_snapshot(second_organization_id)

        assert first.runtime.pending_executions == 1
        assert first.runtime.dead_letter_executions == 0
        assert first.summary.overall_status == "healthy"

        assert second.runtime.pending_executions == 0
        assert second.runtime.dead_letter_executions == 1
        assert second.summary.overall_status == "critical"
    finally:
        session.rollback()
        organization_ids = (first_organization_id, second_organization_id)
        session.execute(
            delete(RuntimeExecution).where(
                RuntimeExecution.organization_id.in_(organization_ids)
            )
        )
        session.flush()
        for organization_id in organization_ids:
            delete_integration_organization(session, organization_id)
        session.commit()
        session.close()
        engine.dispose()
