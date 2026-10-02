from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

JsonMapping = Mapping[str, Any]


@dataclass(frozen=True)
class SecretReference:
    resolver_type: str
    reference: str
    metadata: JsonMapping = field(default_factory=dict)


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True)
class SecretResolutionResult:
    status: str
    value: SecretValue | None = None
    error_code: str | None = None
    message: str | None = None
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class SecretResolver(Protocol):
    @property
    def resolver_type(self) -> str: ...

    def resolve(self, reference: SecretReference) -> SecretResolutionResult: ...
