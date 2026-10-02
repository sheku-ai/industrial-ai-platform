from uuid import uuid4

import pytest

from tests.integration_support.s3_environment import load_s3_integration_environment
from tests.integration_support.s3_object_store import S3CompatibleObjectStore

environment = load_s3_integration_environment()
pytestmark = pytest.mark.skipif(
    environment is None,
    reason="explicit S3 integration environment is not configured",
)


def test_s3_compatible_put_stat_read_remove_smoke():
    assert environment is not None
    store = S3CompatibleObjectStore(
        endpoint_url=environment.endpoint_url,
        access_key_id=environment.access_key_id,
        secret_access_key=environment.secret_access_key,
        bucket=environment.bucket,
        region=environment.region,
        use_ssl=environment.use_ssl,
    )
    key = f"integration/{uuid4()}/connectivity/object.txt"
    payload = b"industrial-ai-platform-s3-smoke"

    try:
        checksum = store.put_bytes(key, payload, content_type="text/plain")
        metadata = store.stat(key)
        restored = store.read_bytes(key)

        assert metadata is not None
        assert metadata.size_bytes == len(payload)
        assert metadata.checksum_sha256 == checksum
        assert metadata.content_type in {"text/plain", "text/plain; charset=utf-8"}
        assert restored == payload
    finally:
        store.remove(key)

    assert store.stat(key) is None
