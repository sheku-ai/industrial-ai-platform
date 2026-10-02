from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class S3IntegrationEnvironment:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str
    use_ssl: bool


def load_s3_integration_environment() -> S3IntegrationEnvironment | None:
    required = {
        "endpoint_url": os.getenv("S3_ENDPOINT_URL"),
        "access_key_id": os.getenv("S3_ACCESS_KEY_ID"),
        "secret_access_key": os.getenv("S3_SECRET_ACCESS_KEY"),
        "bucket": os.getenv("S3_BUCKET"),
    }
    if any(value is None or not value.strip() for value in required.values()):
        return None

    use_ssl_raw = (os.getenv("S3_USE_SSL") or "false").strip().lower()
    if use_ssl_raw not in {"true", "false"}:
        raise ValueError("S3_USE_SSL must be true or false")

    return S3IntegrationEnvironment(
        endpoint_url=required["endpoint_url"].strip(),
        access_key_id=required["access_key_id"].strip(),
        secret_access_key=required["secret_access_key"].strip(),
        bucket=required["bucket"].strip(),
        region=(os.getenv("S3_REGION") or "us-east-1").strip(),
        use_ssl=use_ssl_raw == "true",
    )
