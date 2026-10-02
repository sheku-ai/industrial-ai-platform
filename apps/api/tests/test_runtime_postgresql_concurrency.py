import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.core import Organization
from app.models.runtime import RuntimeExecution, RuntimeExecutionAttempt, RuntimeExecutionEvent
from app.services.runtime_lifecycle import InvalidLeaseError, RuntimeLifecycleService

RUN_POSTGRES = os.getenv("RUN_POSTGRES_RUNTIME_TESTS") == "1"
TEST_DATABASE_URL = os.getenv("RUNTIME_POSTGRES_TEST_DATABASE_URL", "")


def _is_disposable_test_database(url: str) -> bool:
    if not url.startswith("postgresql"):
        return False
    database = make_url(url).database or ""
    return database.endswith("_test") or database.startswith("test_")


pytestmark = pytest.mark.skipif(
    not RUN_POSTGRES or not _is_disposable_test_database(TEST_DATABASE_URL),
    reason=(
        "set RUN_POSTGRES_RUNTIME_TESTS=1 and "
        "RUNTIME_POSTGRES_TEST_DATABASE_URL to a disposable PostgreSQL database "
        "whose name starts with test_ or ends with _test"
    ),
)


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _reset_runtime_test_data(session_factory):
    """Reset only a disposable test database without weakening append-only triggers."""
    with session_factory() as session:
        session.execute(
            text(
                "TRUNCATE TABLE "
                "runtime.execution_artifacts, "
                "runtime.execution_events, "
                "runtime.execution_attempts, "
                "runtime.executions "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.execute(
            delete(Organization).where(Organization.slug.like("runtime-pg-%"))
        )
        session.commit()


@pytest.fixture(scope="module", autouse=True)
def isolated_runtime_database(session_factory):
    _reset_runtime_test_data(session_factory)
    try:
        yield
    finally:
        _reset_runtime_test_data(session_factory)


def _create_organization(session, organization_id=None):
    organization_id = organization_id or uuid4()
    organization = Organization(
        id=organization_id,
        slug=f"runtime-pg-{organization_id}",
        name=f"Runtime PostgreSQL Test {organization_id}",
        description="Ephemeral organization for runtime PostgreSQL integration tests",
        status="active",
        config={},
        created_by="pytest",
        updated_by="pytest",
    )
    session.add(organization)
    session.commit()
    return organization_id


@pytest.fixture
def organization_id(session_factory):
    with session_factory() as session:
        return _create_organization(session)


def _create_execution(session, organization_id, *, priority=100, suffix="default"):
    execution, created = RuntimeLifecycleService(session).create_or_get(
        organization_id=organization_id,
        execution_type="document.ingestion",
        subject_type="document_version",
        subject_id=uuid4(),
        idempotency_key=f"runtime-pg-{suffix}-{uuid4()}",
        requested_by="pytest",
        priority=priority,
        input_payload={},
        policy_snapshot={},
    )
    assert created is True
    session.commit()
    return execution


def test_competing_claims_skip_locked_execution(session_factory, organization_id):
    with session_factory() as setup:
        first = _create_execution(setup, organization_id, priority=10, suffix="first")
        second = _create_execution(setup, organization_id, priority=20, suffix="second")

    session_a = session_factory()
    session_b = session_factory()
    tx_a = session_a.begin()
    try:
        claim_a = RuntimeLifecycleService(session_a).claim(
            organization_id=organization_id,
            worker_id="worker-a",
            lease_duration=timedelta(minutes=5),
        )
        assert claim_a is not None
        execution_a, attempt_a = claim_a
        assert execution_a.id == first.id

        claim_b = RuntimeLifecycleService(session_b).claim(
            organization_id=organization_id,
            worker_id="worker-b",
            lease_duration=timedelta(minutes=5),
        )
        session_b.commit()

        assert claim_b is not None
        execution_b, attempt_b = claim_b
        assert execution_b.id == second.id
        assert execution_b.id != execution_a.id
        assert attempt_b.lease_token != attempt_a.lease_token
    finally:
        tx_a.rollback()
        session_a.close()
        session_b.close()


def test_expired_execution_is_reclaimed_with_new_attempt_and_fences_stale_token(
    session_factory,
    organization_id,
):
    with session_factory() as session:
        execution = _create_execution(session, organization_id, suffix="reclaim")
        t0 = execution.requested_at + timedelta(seconds=1)

        claimed = RuntimeLifecycleService(session).claim(
            organization_id=organization_id,
            worker_id="worker-old",
            lease_duration=timedelta(seconds=30),
            now=t0,
        )
        assert claimed is not None
        _, first_attempt = claimed
        first_token = first_attempt.lease_token
        session.commit()

    with session_factory() as session:
        RuntimeLifecycleService(session).expire(
            organization_id,
            execution.id,
            now=t0 + timedelta(seconds=31),
        )
        session.commit()

    with session_factory() as session:
        reclaimed = RuntimeLifecycleService(session).claim(
            organization_id=organization_id,
            worker_id="worker-new",
            lease_duration=timedelta(minutes=5),
            now=t0 + timedelta(seconds=32),
        )
        assert reclaimed is not None
        reclaimed_execution, second_attempt = reclaimed
        session.commit()

        assert reclaimed_execution.id == execution.id
        assert second_attempt.attempt_number == 2
        assert second_attempt.lease_token != first_token

    with session_factory() as session:
        with pytest.raises(InvalidLeaseError):
            RuntimeLifecycleService(session).heartbeat(
                organization_id,
                execution.id,
                lease_token=first_token,
                extend_by=timedelta(minutes=5),
                now=t0 + timedelta(seconds=33),
            )
        session.rollback()

    with session_factory() as session:
        with pytest.raises(InvalidLeaseError):
            RuntimeLifecycleService(session).succeed(
                organization_id,
                execution.id,
                lease_token=first_token,
                metrics={"stale": True},
                now=t0 + timedelta(seconds=33),
            )
        session.rollback()

    with session_factory() as session:
        attempts = session.scalars(
            select(RuntimeExecutionAttempt)
            .where(RuntimeExecutionAttempt.execution_id == execution.id)
            .order_by(RuntimeExecutionAttempt.attempt_number)
        ).all()
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[0].status == "expired"
        assert attempts[1].status == "leased"

        current_execution = session.get(RuntimeExecution, execution.id)
        assert current_execution is not None
        assert current_execution.status == "leased"

        events = session.scalars(
            select(RuntimeExecutionEvent)
            .where(RuntimeExecutionEvent.execution_id == execution.id)
            .order_by(RuntimeExecutionEvent.sequence_number)
        ).all()
        sequences = [event.sequence_number for event in events]
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))


def test_claim_is_tenant_scoped(session_factory):
    with session_factory() as session:
        organization_a = _create_organization(session)
        organization_b = _create_organization(session)

    with session_factory() as session:
        _create_execution(session, organization_b, priority=1, suffix="tenant-b")

    with session_factory() as session:
        claim = RuntimeLifecycleService(session).claim(
            organization_id=organization_a,
            worker_id="worker-a",
            lease_duration=timedelta(minutes=5),
        )
        session.commit()
        assert claim is None
