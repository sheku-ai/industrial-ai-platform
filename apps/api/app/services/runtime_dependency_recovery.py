from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

TRANSIENT_DEPENDENCY_ERRORS = (
    SQLAlchemyError,
    RedisError,
    BotoCoreError,
    ClientError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def is_transient_dependency_error(exc: BaseException) -> bool:
    return isinstance(exc, TRANSIENT_DEPENDENCY_ERRORS)


@dataclass
class RuntimeDependencyRecovery:
    initial_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 30.0
    multiplier: float = 2.0
    sleep: Callable[[float], None] = time.sleep
    attempts: int = 0

    def wait(self) -> float:
        delay = min(
            self.maximum_delay_seconds,
            self.initial_delay_seconds * (self.multiplier**self.attempts),
        )
        self.attempts += 1
        self.sleep(delay)
        return delay

    def recovered(self) -> None:
        self.attempts = 0
