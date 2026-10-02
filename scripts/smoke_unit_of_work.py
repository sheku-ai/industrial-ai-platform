#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db.unit_of_work import ApplicationTransaction, SQLAlchemyUnitOfWork, UnitOfWorkError


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.close_count = 0
        self.pending: list[str] = []
        self.committed: list[str] = []

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1
        self.committed.extend(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()

    def close(self) -> None:
        self.close_count += 1


def main() -> int:
    success_session = FakeSession()
    success_transaction = ApplicationTransaction(lambda: SQLAlchemyUnitOfWork(success_session))

    def successful_operation(unit_of_work: SQLAlchemyUnitOfWork) -> str:
        success_session.pending.extend(["entity-a", "entity-b"])
        unit_of_work.flush()
        return "ok"

    result = success_transaction.execute(successful_operation)
    assert result == "ok"
    assert success_session.commit_count == 1
    assert success_session.rollback_count == 0
    assert success_session.committed == ["entity-a", "entity-b"]
    assert success_session.close_count == 1

    failed_session = FakeSession()
    failed_transaction = ApplicationTransaction(lambda: SQLAlchemyUnitOfWork(failed_session))

    def failed_operation(unit_of_work: SQLAlchemyUnitOfWork) -> None:
        failed_session.pending.append("entity-a")
        unit_of_work.flush()
        failed_session.pending.append("entity-b")
        raise RuntimeError("simulated failure")

    failed = False
    try:
        failed_transaction.execute(failed_operation)
    except RuntimeError:
        failed = True

    assert failed is True
    assert failed_session.commit_count == 0
    assert failed_session.rollback_count == 1
    assert failed_session.committed == []
    assert failed_session.pending == []
    assert failed_session.close_count == 1

    state_session = FakeSession()
    unit_of_work = SQLAlchemyUnitOfWork(state_session)
    with unit_of_work:
        unit_of_work.commit()
        invalid_transition_rejected = False
        try:
            unit_of_work.rollback()
        except UnitOfWorkError:
            invalid_transition_rejected = True
        assert invalid_transition_rejected is True

    print(json.dumps({
        "status": "passed",
        "contract": "UnitOfWork",
        "success_commit_count": success_session.commit_count,
        "failed_commit_count": failed_session.commit_count,
        "failed_rollback_count": failed_session.rollback_count,
        "multi_entity_atomicity": True,
        "invalid_transition_rejected": True,
        "provider_execution_enabled": False
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
