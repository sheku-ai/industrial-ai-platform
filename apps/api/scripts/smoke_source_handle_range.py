from __future__ import annotations

import hashlib
import json
import uuid

import boto3

from app.core.config import get_settings
from app.services.s3_source_acquisition import S3SourceAcquisitionService


def main() -> int:
    settings = get_settings()
    bucket = settings.object_storage_bucket
    key = f"smoke/source-handle/{uuid.uuid4()}.bin"
    payload = (b"source-handle-range-smoke-" * 256) + b"END"

    client = boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint_url or None,
        region_name=settings.object_storage_region,
        aws_access_key_id=settings.object_storage_access_key or None,
        aws_secret_access_key=settings.object_storage_secret_key or None,
        use_ssl=settings.object_storage_secure,
    )
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentType="application/octet-stream",
        Metadata={"sha256": hashlib.sha256(payload).hexdigest()},
    )

    try:
        handle = S3SourceAcquisitionService().open_handle(f"s3://{bucket}/{key}")
        first = b"".join(handle.iter_bytes(start=0, end_exclusive=64, chunk_size=13))
        middle = b"".join(handle.iter_bytes(start=64, end_exclusive=160, chunk_size=17))
        passed = (
            first == payload[:64]
            and middle == payload[64:160]
            and handle.content_length == len(payload)
            and handle.checksum_sha256 == hashlib.sha256(payload).hexdigest()
        )
        print(
            json.dumps(
                {
                    "passed": passed,
                    "content_length": handle.content_length,
                    "first_range_length": len(first),
                    "middle_range_length": len(middle),
                    "checksum_matches": handle.checksum_sha256 == hashlib.sha256(payload).hexdigest(),
                    "source_reference": handle.source_reference,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        client.delete_object(Bucket=bucket, Key=key)


if __name__ == "__main__":
    raise SystemExit(main())
