from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError


class SecretStoreError(RuntimeError):
    pass


class SecretNotFound(SecretStoreError):
    pass


class SecretExpired(SecretStoreError):
    pass


class SecretStoreUnavailable(SecretStoreError):
    pass


@dataclass(frozen=True)
class SecretValue:
    value: str
    expires_at: datetime
    single_use: bool = True

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("secret value is required")
        if self.expires_at <= datetime.now(UTC):
            raise ValueError("secret must expire in the future")


class SecretStore(Protocol):
    def put(self, reference: str, secret: SecretValue) -> None: ...

    def inspect(self, reference: str) -> SecretValue: ...

    def resolve(self, reference: str) -> SecretValue: ...

    def revoke(self, reference: str) -> None: ...


class InMemorySecretStore:
    """Process-local secret store intended only for unit tests."""

    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def put(self, reference: str, secret: SecretValue) -> None:
        _validate_reference(reference)
        self._values[reference] = secret

    def inspect(self, reference: str) -> SecretValue:
        secret = self._values.get(reference)
        if secret is None:
            raise SecretNotFound(reference)
        if secret.expires_at <= datetime.now(UTC):
            self._values.pop(reference, None)
            raise SecretExpired(reference)
        return secret

    def resolve(self, reference: str) -> SecretValue:
        secret = self.inspect(reference)
        if secret.single_use:
            self._values.pop(reference, None)
        return secret

    def revoke(self, reference: str) -> None:
        self._values.pop(reference, None)


_RESOLVE_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if not value then
  return nil
end
local payload = cjson.decode(value)
if payload['single_use'] then
  redis.call('DEL', KEYS[1])
end
return value
"""


class RedisEphemeralSecretStore:
    """Shared TTL-bound secret store for multi-process and multi-container runtime.

    References are never used directly as Redis keys. A SHA-256 digest prevents
    references from becoming operationally meaningful in key listings. Secret
    values are stored only in Redis and are removed atomically on single-use
    resolution.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "industrial-ai:ephemeral-secret:",
        socket_timeout_seconds: float = 3.0,
    ) -> None:
        if not redis_url:
            raise ValueError("redis_url is required")
        self._client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=socket_timeout_seconds,
            socket_timeout=socket_timeout_seconds,
            health_check_interval=30,
        )
        self._key_prefix = key_prefix
        self._resolve_script = self._client.register_script(_RESOLVE_SCRIPT)

    def put(self, reference: str, secret: SecretValue) -> None:
        _validate_reference(reference)
        ttl_seconds = _remaining_ttl_seconds(secret.expires_at)
        payload = json.dumps(
            {
                "value": secret.value,
                "expires_at": secret.expires_at.isoformat(),
                "single_use": secret.single_use,
            },
            separators=(",", ":"),
        )
        try:
            self._client.set(self._key(reference), payload, ex=ttl_seconds)
        except RedisError as exc:
            raise SecretStoreUnavailable("ephemeral secret store is unavailable") from exc

    def inspect(self, reference: str) -> SecretValue:
        _validate_reference(reference)
        try:
            payload = self._client.get(self._key(reference))
        except RedisError as exc:
            raise SecretStoreUnavailable("ephemeral secret store is unavailable") from exc
        if payload is None:
            raise SecretNotFound(reference)
        return self._decode(reference, payload)

    def resolve(self, reference: str) -> SecretValue:
        _validate_reference(reference)
        try:
            payload = self._resolve_script(keys=[self._key(reference)])
        except RedisError as exc:
            raise SecretStoreUnavailable("ephemeral secret store is unavailable") from exc
        if payload is None:
            raise SecretNotFound(reference)
        return self._decode(reference, str(payload))

    def revoke(self, reference: str) -> None:
        _validate_reference(reference)
        try:
            self._client.delete(self._key(reference))
        except RedisError as exc:
            raise SecretStoreUnavailable("ephemeral secret store is unavailable") from exc

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except RedisError as exc:
            raise SecretStoreUnavailable("ephemeral secret store is unavailable") from exc

    def _key(self, reference: str) -> str:
        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        return f"{self._key_prefix}{digest}"

    @staticmethod
    def _decode(reference: str, payload: str) -> SecretValue:
        try:
            data = json.loads(payload)
            expires_at = datetime.fromisoformat(str(data["expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            secret = SecretValue(
                value=str(data["value"]),
                expires_at=expires_at,
                single_use=bool(data.get("single_use", True)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SecretStoreError("ephemeral secret payload is invalid") from exc
        if secret.expires_at <= datetime.now(UTC):
            raise SecretExpired(reference)
        return secret


def _validate_reference(reference: str) -> None:
    if not reference or "://" not in reference:
        raise ValueError("secret reference must use an explicit scheme")


def _remaining_ttl_seconds(expires_at: datetime) -> int:
    remaining = int((expires_at - datetime.now(UTC)).total_seconds())
    if remaining < 1:
        raise SecretExpired("secret expiry is not in the future")
    return remaining
