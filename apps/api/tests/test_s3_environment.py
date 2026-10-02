
import pytest

from tests.integration_support.s3_environment import load_s3_integration_environment

S3_VARIABLES = (
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_BUCKET",
    "S3_REGION",
    "S3_USE_SSL",
)


def clear_environment(monkeypatch):
    for name in S3_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_environment_loader_returns_none_when_required_values_are_missing(monkeypatch):
    clear_environment(monkeypatch)

    assert load_s3_integration_environment() is None


def test_environment_loader_returns_explicit_configuration(monkeypatch):
    clear_environment(monkeypatch)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("S3_BUCKET", "integration")
    monkeypatch.setenv("S3_REGION", "custom-region")
    monkeypatch.setenv("S3_USE_SSL", "true")

    environment = load_s3_integration_environment()

    assert environment is not None
    assert environment.endpoint_url == "http://127.0.0.1:9000"
    assert environment.region == "custom-region"
    assert environment.use_ssl is True


def test_environment_loader_rejects_invalid_ssl_value(monkeypatch):
    clear_environment(monkeypatch)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("S3_BUCKET", "integration")
    monkeypatch.setenv("S3_USE_SSL", "sometimes")

    with pytest.raises(ValueError, match="S3_USE_SSL"):
        load_s3_integration_environment()
