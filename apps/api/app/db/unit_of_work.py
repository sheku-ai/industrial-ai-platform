from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from sqlalchemy.orm import Session


class UnitOfWorkState(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    CLOSED = "closed"


class UnitOfWorkError(RuntimeError):
    pass


class SQLAlchemyUnitOfWork:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.state = UnitOfWorkState.NEW

    def __enter__(self) -> SQLAlchemyUnitOfWork:
        if self.state != UnitOfWorkState.NEW:
            raise UnitOfWorkError("unit of work cannot be re-entered")
        self.state = UnitOfWorkState.ACTIVE
        return self

    def flush(self) -> None:
        self._require_active()
        self.session.flush()

    def commit(self) -> None:
        self._require_active()
        self.session.commit()
        self.state = UnitOfWorkState.COMMITTED

    def rollback(self) -> None:
        self._require_active()
        self.session.rollback()
        self.state = UnitOfWorkState.ROLLED_BACK

    def __exit__(self, exc_type, exc, traceback) -> Literal[False]:
        del exc_type, exc, traceback
        try:
            if self.state == UnitOfWorkState.ACTIVE:
                self.session.rollback()
                self.state = UnitOfWorkState.ROLLED_BACK
        finally:
            self.session.close()
            self.state = UnitOfWorkState.CLOSED
        return False

    def _require_active(self) -> None:
        if self.state != UnitOfWorkState.ACTIVE:
            raise UnitOfWorkError(f"unit of work is not active: {self.state}")


class ApplicationTransaction[ResultT]:
    def __init__(self, unit_of_work_factory: Callable[[], SQLAlchemyUnitOfWork]) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def execute(self, operation: Callable[[SQLAlchemyUnitOfWork], ResultT]) -> ResultT:
        with self.unit_of_work_factory() as unit_of_work:
            result = operation(unit_of_work)
            unit_of_work.commit()
        return result
