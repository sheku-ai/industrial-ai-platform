import pytest

from app.db.unit_of_work import ApplicationTransaction, SQLAlchemyUnitOfWork, UnitOfWorkError


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


def test_transaction_commit() -> None:
    session = FakeSession()
    transaction = ApplicationTransaction(lambda: SQLAlchemyUnitOfWork(session))
    assert transaction.execute(lambda unit_of_work: "ok") == "ok"
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed == 1


def test_transaction_rollback() -> None:
    session = FakeSession()
    transaction = ApplicationTransaction(lambda: SQLAlchemyUnitOfWork(session))

    def operation(unit_of_work: SQLAlchemyUnitOfWork) -> None:
        unit_of_work.flush()
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError):
        transaction.execute(operation)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed == 1


def test_invalid_transition() -> None:
    session = FakeSession()
    unit_of_work = SQLAlchemyUnitOfWork(session)
    with unit_of_work:
        unit_of_work.commit()
        with pytest.raises(UnitOfWorkError):
            unit_of_work.rollback()
