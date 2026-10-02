from datetime import UTC, datetime, timedelta

import pytest

from app.api.routes.document_review_runtime import router
from app.services.secret_store import InMemorySecretStore, SecretNotFound, SecretValue


def test_in_memory_secret_store_is_single_use() -> None:
    store = InMemorySecretStore()
    reference = "secret://document-review/one"
    store.put(
        reference,
        SecretValue(
            value="not-persisted",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            single_use=True,
        ),
    )

    inspected = store.inspect(reference)
    assert inspected.value == "not-persisted"
    resolved = store.resolve(reference)
    assert resolved.value == "not-persisted"
    with pytest.raises(SecretNotFound):
        store.resolve(reference)


def test_secret_store_rejects_expired_values() -> None:
    with pytest.raises(ValueError, match="expire in the future"):
        SecretValue(
            value="expired",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_secret_store_revoke_is_idempotent() -> None:
    store = InMemorySecretStore()
    store.revoke("secret://missing")
    with pytest.raises(SecretNotFound):
        store.inspect("secret://missing")


def test_runtime_router_exposes_retry_and_expiry_endpoints() -> None:
    paths = {route.path for route in router.routes}

    assert "/document-reviews/expire-due" in paths
    assert "/document-reviews/{review_id}/retry" in paths
