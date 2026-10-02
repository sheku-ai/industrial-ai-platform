from __future__ import annotations

import os
from functools import lru_cache

from app.services.secret_store import (
    InMemorySecretStore,
    RedisEphemeralSecretStore,
    SecretStore,
)


@lru_cache(maxsize=1)
def get_secret_store() -> SecretStore:
    """Return the explicitly configured ephemeral secret store provider.

    Redis is required for multi-process/container runtime. The in-memory provider
    remains available only when explicitly selected for unit tests or isolated
    single-process development.
    """
    provider = os.getenv("SECRET_STORE_PROVIDER", "memory").strip().lower()

    if provider == "redis":
        redis_url = os.getenv("SECRET_STORE_REDIS_URL", "").strip()
        if not redis_url:
            raise RuntimeError("SECRET_STORE_REDIS_URL is required for redis secret store")
        return RedisEphemeralSecretStore(
            redis_url,
            key_prefix=os.getenv(
                "SECRET_STORE_KEY_PREFIX",
                "industrial-ai:ephemeral-secret:",
            ),
            socket_timeout_seconds=float(os.getenv("SECRET_STORE_SOCKET_TIMEOUT_SECONDS", "3")),
        )

    if provider == "memory":
        return InMemorySecretStore()

    raise RuntimeError(f"unsupported SECRET_STORE_PROVIDER={provider!r}")


def reset_secret_store_runtime() -> None:
    """Clear the provider singleton for deterministic tests."""
    get_secret_store.cache_clear()
