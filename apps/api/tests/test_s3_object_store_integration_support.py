from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from tests.integration_support.s3_object_store import S3CompatibleObjectStore


class ClientStub:
    def __init__(self):
        self.calls = []
        self.head_response = {
            "ContentLength": 3,
            "ContentType": "text/plain",
            "Metadata": {"sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"},
        }

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs))
        return {}

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return self.head_response

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"Body": BytesIO(b"abc")}

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {}


def build_store(client):
    return S3CompatibleObjectStore(
        endpoint_url="http://127.0.0.1:9000",
        access_key_id="key",
        secret_access_key="secret",
        bucket="integration",
        client=client,
    )


def test_put_stat_read_and_remove_contract():
    client = ClientStub()
    store = build_store(client)

    checksum = store.put_bytes("integration/run/object.txt", b"abc", content_type="text/plain")
    metadata = store.stat("integration/run/object.txt")
    payload = store.read_bytes("integration/run/object.txt")
    store.remove("integration/run/object.txt")

    assert checksum == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert metadata is not None
    assert metadata.size_bytes == 3
    assert metadata.checksum_sha256 == checksum
    assert metadata.content_type == "text/plain"
    assert payload == b"abc"
    assert [call[0] for call in client.calls] == ["put", "head", "get", "delete"]
    assert client.calls[0][1]["Metadata"] == {"sha256": checksum}


def test_stat_returns_none_for_missing_object():
    client = ClientStub()

    def missing(**kwargs):
        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
            "HeadObject",
        )

    client.head_object = missing
    store = build_store(client)

    assert store.stat("integration/run/missing.txt") is None


def test_adapter_rejects_implicit_or_absolute_configuration():
    with pytest.raises(ValueError, match="endpoint_url"):
        S3CompatibleObjectStore(
            endpoint_url=" ",
            access_key_id="key",
            secret_access_key="secret",
            bucket="integration",
        )

    store = build_store(ClientStub())
    with pytest.raises(ValueError, match="relative"):
        store.put_bytes("/absolute", b"abc")
