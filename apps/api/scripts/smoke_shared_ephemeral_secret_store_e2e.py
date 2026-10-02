from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg

from app.services.secret_store import (
    RedisEphemeralSecretStore,
    SecretNotFound,
    SecretValue,
)


def _store() -> RedisEphemeralSecretStore:
    return RedisEphemeralSecretStore(
        os.environ["SECRET_STORE_REDIS_URL"],
        key_prefix=os.getenv(
            "SECRET_STORE_KEY_PREFIX",
            "industrial-ai:ephemeral-secret:",
        ),
    )


def _producer() -> int:
    reference = os.environ["SMOKE_SECRET_REFERENCE"]
    secret_value = os.environ["SMOKE_SECRET_VALUE"]
    ttl_seconds = int(os.environ["SMOKE_SECRET_TTL_SECONDS"])
    _store().put(
        reference,
        SecretValue(
            value=secret_value,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            single_use=True,
        ),
    )
    print(json.dumps({"stored": True, "reference": reference}))
    return 0


def _consumer() -> int:
    reference = os.environ["SMOKE_SECRET_REFERENCE"]
    try:
        secret = _store().resolve(reference)
    except SecretNotFound:
        print(json.dumps({"consumed": False, "reason": "not_found"}))
        return 4
    print(
        json.dumps(
            {
                "consumed": True,
                "value_sha256": hashlib.sha256(secret.value.encode("utf-8")).hexdigest(),
                "single_use": secret.single_use,
            }
        )
    )
    return 0


def _run_mode(mode: str, env: dict[str, str], expected_code: int = 0) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, __file__, mode],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != expected_code:
        raise RuntimeError(
            f"subprocess mode={mode} returned {completed.returncode}; "
            f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
        )
    output = completed.stdout.strip().splitlines()
    return json.loads(output[-1]) if output else {}


def _database_contains(secret_value: str) -> bool:
    database_url = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://", 1)
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    pattern = f"%{secret_value}%"
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        for table_name in ("document_review_cases", "document_review_events"):
            cursor.execute(
                f"SELECT EXISTS (SELECT 1 FROM documents.{table_name} AS row_value "
                "WHERE row_to_json(row_value)::text LIKE %s)",
                (pattern,),
            )
            if bool(cursor.fetchone()[0]):
                return True
    return False


def _orchestrate() -> int:
    store = _store()
    store.ping()

    secret_value = f"secret-{secrets.token_urlsafe(24)}"
    secret_hash = hashlib.sha256(secret_value.encode("utf-8")).hexdigest()
    base_env = os.environ.copy()

    consume_reference = f"redis-secret://{uuid4()}"
    consume_env = {
        **base_env,
        "SMOKE_SECRET_REFERENCE": consume_reference,
        "SMOKE_SECRET_VALUE": secret_value,
        "SMOKE_SECRET_TTL_SECONDS": "30",
    }
    producer_result = _run_mode("producer", consume_env)
    consumer_result = _run_mode("consumer", consume_env)
    second_consumer_result = _run_mode("consumer", consume_env, expected_code=4)

    ttl_reference = f"redis-secret://{uuid4()}"
    ttl_env = {
        **base_env,
        "SMOKE_SECRET_REFERENCE": ttl_reference,
        "SMOKE_SECRET_VALUE": secret_value,
        "SMOKE_SECRET_TTL_SECONDS": "2",
    }
    _run_mode("producer", ttl_env)
    time.sleep(2.2)
    ttl_result = _run_mode("consumer", ttl_env, expected_code=4)

    revoke_reference = f"redis-secret://{uuid4()}"
    revoke_env = {
        **base_env,
        "SMOKE_SECRET_REFERENCE": revoke_reference,
        "SMOKE_SECRET_VALUE": secret_value,
        "SMOKE_SECRET_TTL_SECONDS": "30",
    }
    _run_mode("producer", revoke_env)
    store.revoke(revoke_reference)
    revoke_result = _run_mode("consumer", revoke_env, expected_code=4)

    credential_value_persisted = _database_contains(secret_value)
    passed = all(
        (
            producer_result.get("stored") is True,
            consumer_result.get("consumed") is True,
            consumer_result.get("value_sha256") == secret_hash,
            second_consumer_result.get("reason") == "not_found",
            ttl_result.get("reason") == "not_found",
            revoke_result.get("reason") == "not_found",
            credential_value_persisted is False,
        )
    )

    print(
        json.dumps(
            {
                "passed": passed,
                "provider": "redis",
                "cross_process_consumed": consumer_result.get("consumed") is True,
                "single_use_enforced": second_consumer_result.get("reason") == "not_found",
                "ttl_enforced": ttl_result.get("reason") == "not_found",
                "revoke_enforced": revoke_result.get("reason") == "not_found",
                "credential_value_persisted": credential_value_persisted,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "producer":
        return _producer()
    if len(sys.argv) == 2 and sys.argv[1] == "consumer":
        return _consumer()
    return _orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
