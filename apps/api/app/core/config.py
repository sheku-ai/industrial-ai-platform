from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.platform_metadata import PRODUCT_NAME, PRODUCT_VERSION


class Settings(BaseSettings):
    app_name: str = f"{PRODUCT_NAME} API"
    app_version: str = PRODUCT_VERSION
    database_url: str = ""
    identity_database_url: str = ""
    portal_port: int = 3000
    cors_allowed_origins: str = ""
    trusted_hosts: str = ""
    secret_key: str = ""
    log_level: str = "INFO"
    api_port: int = 8000
    postgres_max_connections: int = 0
    worker_concurrency: int = 0

    build_commit: str = "unknown"
    build_timestamp: datetime | None = None
    database_revision: str = "unknown"
    configuration_revision: str = "unknown"
    environment_profile: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ENVIRONMENT_PROFILE",
            "APP_ENV",
            "ENVIRONMENT",
            "DEPLOYMENT_ENVIRONMENT",
        ),
    )
    authentication_required: bool | None = None
    api_docs_enabled: bool = False
    debug: bool = False

    auth_cookie_name: str = Field(
        default="industrial_ai_session",
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    auth_cookie_secure: bool = False
    auth_session_absolute_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    auth_session_inactivity_seconds: int = Field(default=3_600, ge=60, le=604_800)
    auth_session_touch_interval_seconds: int = Field(default=300, ge=15, le=3_600)
    auth_argon2_time_cost: int = Field(default=3, ge=1, le=10)
    auth_argon2_memory_cost_kib: int = Field(default=65_536, ge=8_192, le=1_048_576)
    auth_argon2_parallelism: int = Field(default=4, ge=1, le=16)
    auth_argon2_hash_length: int = Field(default=32, ge=16, le=64)
    auth_argon2_salt_length: int = Field(default=16, ge=16, le=64)
    auth_password_min_length: int = Field(default=15, ge=8, le=128)
    auth_password_max_length: int = Field(default=128, ge=32, le=1_024)
    auth_password_block_context: bool = True
    auth_password_block_common: bool = True
    auth_attempt_window_seconds: int = Field(default=900, ge=60, le=86_400)
    auth_attempt_threshold: int = Field(default=5, ge=2, le=100)
    auth_attempt_block_base_seconds: int = Field(default=30, ge=1, le=3_600)
    auth_attempt_block_max_seconds: int = Field(default=900, ge=1, le=86_400)
    auth_csrf_header_name: str = Field(
        default="X-CSRF-Token",
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9-]+$",
    )
    auth_csrf_token_bytes: int = Field(default=32, ge=24, le=64)
    auth_trusted_proxy_networks: str = ""
    auth_forwarded_ip_headers: str = "forwarded,x-forwarded-for"

    feature_embeddings_enabled: bool = False
    feature_vector_retrieval_enabled: bool = False
    feature_worker_enabled: bool = False
    feature_enterprise_extensions_enabled: bool = False
    platform_edition: str = "community"
    installation_instance_id: str = "default"
    sheku_setup_token: str = ""
    installation_default_language: str = "en"
    installation_default_timezone: str = "UTC"

    secret_store_provider: str = "memory"
    secret_store_redis_url: str = ""
    secret_store_socket_timeout_seconds: float = 3.0

    object_storage_endpoint_url: str = ""
    object_storage_provider: str = "filesystem"
    object_storage_region: str = "us-east-1"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_bucket: str = ""
    object_storage_secure: bool = False
    filesystem_storage_root: str = Field(
        default=".runtime/storage/filesystem",
        validation_alias=AliasChoices(
            "INDUSTRIAL_AI_STORAGE_FILESYSTEM_ROOT",
            "FILESYSTEM_STORAGE_ROOT",
        ),
    )
    dependency_probe_timeout_seconds: float = 2.0
    startup_dependency_max_attempts: int = 12
    startup_dependency_retry_seconds: float = 2.0
    ingestion_workspace_root: str = ".runtime/ingestion"
    ingestion_max_source_bytes: int = Field(
        default=1_000_000_000,
        validation_alias=AliasChoices("INGESTION_MAX_SOURCE_BYTES", "MAX_UPLOAD_SIZE"),
    )

    operational_health_pending_warning_seconds: int = 900
    operational_health_stale_data_seconds: int = 300
    operational_health_failed_run_critical_count: int = 5
    configuration_preflight_evidence_max_age_seconds: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_authentication_configuration(self) -> "Settings":
        if self.auth_password_min_length > self.auth_password_max_length:
            raise ValueError("AUTH_PASSWORD_MIN_LENGTH cannot exceed AUTH_PASSWORD_MAX_LENGTH")
        if self.auth_session_inactivity_seconds > self.auth_session_absolute_seconds:
            raise ValueError("AUTH_SESSION_INACTIVITY_SECONDS cannot exceed AUTH_SESSION_ABSOLUTE_SECONDS")
        if self.auth_session_touch_interval_seconds >= self.auth_session_inactivity_seconds:
            raise ValueError("AUTH_SESSION_TOUCH_INTERVAL_SECONDS must be lower than inactivity expiration")
        if self.auth_attempt_block_base_seconds > self.auth_attempt_block_max_seconds:
            raise ValueError("AUTH_ATTEMPT_BLOCK_BASE_SECONDS cannot exceed AUTH_ATTEMPT_BLOCK_MAX_SECONDS")
        if self.identity_database_url and self.database_url:
            platform_url = urlparse(self.database_url.strip())
            identity_url = urlparse(self.identity_database_url.strip())
            platform_target = (
                platform_url.hostname,
                platform_url.port or 5432,
                platform_url.path.rstrip("/"),
            )
            identity_target = (
                identity_url.hostname,
                identity_url.port or 5432,
                identity_url.path.rstrip("/"),
            )
            if platform_target == identity_target:
                raise ValueError("IDENTITY_DATABASE_URL must not point to the platform database")
        if self.environment_profile.strip().lower() == "production":
            if not self.identity_database_url.strip():
                raise ValueError("IDENTITY_DATABASE_URL is required in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be enabled in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        configured = self.cors_allowed_origins.strip()
        if configured:
            return [origin.strip() for origin in configured.split(",") if origin.strip()]
        return [
            f"http://localhost:{self.portal_port}",
            f"http://127.0.0.1:{self.portal_port}",
        ]

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
