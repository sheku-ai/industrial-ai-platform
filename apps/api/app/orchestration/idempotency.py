from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from app.contracts.runtime_execution import RuntimeExecutionRequest


class IdempotencyStatus(StrEnum):
    ACQUIRED = "acquired"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class IdempotencyKey:
    value: str
    request_id: str
    organization_scope: str


@dataclass(frozen=True)
class IdempotencyRecord:
    key: IdempotencyKey
    status: IdempotencyStatus
    result_reference: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class IdempotencyClaim:
    acquired: bool
    record: IdempotencyRecord


class DuplicateExecutionError(RuntimeError):
    """Raised when an execution key is already owned by another lifecycle."""


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if hasattr(value, "hex") and hasattr(value, "version"):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    return str(value)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _normalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_idempotency_key(
    request: RuntimeExecutionRequest,
    *,
    rendered_prompt_hash: str | None = None,
) -> IdempotencyKey:
    organization_scope = str(request.organization_id) if request.organization_id else "global"
    payload = {
        "organization_scope": organization_scope,
        "request_id": str(request.request_id),
        "runtime_profile_id": str(request.runtime_profile_id) if request.runtime_profile_id else None,
        "provider_id": str(request.provider_id) if request.provider_id else None,
        "model_id": str(request.model_id) if request.model_id else None,
        "prompt_id": str(request.prompt_id) if request.prompt_id else None,
        "guardrail_id": str(request.guardrail_id) if request.guardrail_id else None,
        "resolved_answer_mode": request.resolved_answer_mode,
        "generation_allowed": request.generation_allowed,
        "rendered_prompt_hash": rendered_prompt_hash,
        "parameters_hash": _stable_hash(dict(request.parameters)),
        "variables_hash": _stable_hash(dict(request.variables)),
        "context_hash": _stable_hash({"context": request.context}),
    }
    return IdempotencyKey(
        value=_stable_hash(payload),
        request_id=str(request.request_id),
        organization_scope=organization_scope,
    )


@runtime_checkable
class IdempotencyStore(Protocol):
    def claim(self, key: IdempotencyKey) -> IdempotencyClaim: ...

    def complete(self, key: IdempotencyKey, *, result_reference: str | None = None) -> IdempotencyRecord: ...

    def fail(self, key: IdempotencyKey, *, failure_code: str) -> IdempotencyRecord: ...

    def get(self, key: IdempotencyKey) -> IdempotencyRecord | None: ...


class InMemoryIdempotencyStore:
    """Process-local reference store for tests and Community single-process mode."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = Lock()

    def claim(self, key: IdempotencyKey) -> IdempotencyClaim:
        with self._lock:
            existing = self._records.get(key.value)
            if existing is not None:
                return IdempotencyClaim(acquired=False, record=existing)

            record = IdempotencyRecord(key=key, status=IdempotencyStatus.ACQUIRED)
            self._records[key.value] = record
            return IdempotencyClaim(acquired=True, record=record)

    def complete(self, key: IdempotencyKey, *, result_reference: str | None = None) -> IdempotencyRecord:
        return self._replace(
            key,
            IdempotencyRecord(
                key=key,
                status=IdempotencyStatus.COMPLETED,
                result_reference=result_reference,
            ),
        )

    def fail(self, key: IdempotencyKey, *, failure_code: str) -> IdempotencyRecord:
        if not failure_code:
            raise ValueError("failure_code is required")
        return self._replace(
            key,
            IdempotencyRecord(
                key=key,
                status=IdempotencyStatus.FAILED,
                failure_code=failure_code,
            ),
        )

    def get(self, key: IdempotencyKey) -> IdempotencyRecord | None:
        with self._lock:
            return self._records.get(key.value)

    def _replace(self, key: IdempotencyKey, record: IdempotencyRecord) -> IdempotencyRecord:
        with self._lock:
            if key.value not in self._records:
                raise KeyError("idempotency key has not been claimed")
            self._records[key.value] = record
            return record
