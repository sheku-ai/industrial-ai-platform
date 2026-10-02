from pathlib import Path

SCRIPT = Path("scripts/install-platform.sh")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _shell_function(source: str, name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + len("\n}")
    return source[start:end]


def test_installer_uses_production_compose_override() -> None:
    source = _source()
    assert "docker-compose.production.yml" in source
    assert "COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.production.yml)" in source
    assert '--project-name "$COMPOSE_PROJECT"' in source
    assert '--env-file "$ENV_FILE"' in source


def test_installer_builds_current_application_images_before_startup() -> None:
    source = _source()
    build_command = "compose build migrator identity-migrator api scheduler portal"
    assert build_command in source
    assert source.index(build_command) < source.index("compose up -d postgres identity-postgres")


def test_installer_does_not_write_database_state_with_sql() -> None:
    source = _source()
    assert "psql" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE core." not in source


def test_installer_delegates_product_onboarding_to_the_setup_wizard() -> None:
    source = _source()
    assert "Organization name:" not in source
    assert "Organization slug" not in source
    assert "Administrator email:" not in source
    assert "Administrator password:" not in source
    assert "bootstrap-installation" not in source
    assert "http://127.0.0.1:3000/setup" in source


def test_installer_generates_and_preserves_setup_access_code() -> None:
    source = _source()
    ensure_secret = _shell_function(source, "ensure_generated_secret")

    assert 'SETUP_ACCESS_CODE="$(ensure_generated_secret SHEKU_SETUP_TOKEN)"' in source
    assert 'current="$(read_env_value "$key")"' in ensure_secret
    assert 'if [[ -z "$current" ]]' in ensure_secret
    assert 'set_env_value "$key" "$current"' in ensure_secret


def test_installer_reads_authoritative_installation_status_before_final_output() -> None:
    source = _source()
    completed_branch = source[source.index('if [[ "$INSTALLATION_STATE" == "COMPLETED" ]]') :]

    assert "curl -fsS http://127.0.0.1:8000/setup/status" in source
    assert "UNCONFIGURED|IN_PROGRESS|READY_TO_COMPLETE|COMPLETED" in source
    assert "unset SETUP_ACCESS_CODE" in completed_branch.split("else", maxsplit=1)[0]
    assert "Setup access code:" not in completed_branch.split("else", maxsplit=1)[0]
    assert "Setup access code: %s" in completed_branch.split("else", maxsplit=1)[1]


def test_installer_reconciles_completed_installation_platform_owner_explicitly() -> None:
    source = _source()
    completed_branch = source[source.index('if [[ "$INSTALLATION_STATE" == "COMPLETED" ]]') :]
    completed_output, incomplete_output = completed_branch.split("else", maxsplit=1)

    command = "compose exec -T api python -m app.cli reconcile-installation-platform-owner"
    assert command in completed_output
    assert command not in incomplete_output
    assert completed_output.index(command) < completed_output.index("SHEKU is ready.")
    assert "password" not in command


def test_installer_uses_separate_filesystem_and_runtime_paths() -> None:
    source = _source()
    assert 'FILESYSTEM_STORAGE_PATH="$(ensure_env_value FILESYSTEM_STORAGE_PATH "$DATA_ROOT/filesystem")"' in source
    assert 'RUNTIME_DATA_PATH="$(ensure_env_value RUNTIME_DATA_PATH "$DATA_ROOT/runtime")"' in source
    assert "$DATA_ROOT/runtime/storage/filesystem" not in source


def test_installer_defaults_to_user_writable_data_root() -> None:
    source = _source()
    assert "XDG_DATA_HOME" in source
    assert "/.local/share}/sheku" in source
    assert 'DATA_ROOT="${INSTALL_DATA_ROOT' not in source
    assert "/data/industrial-ai" not in source


def test_installer_defaults_to_filesystem_storage_and_keeps_minio_opt_in() -> None:
    source = _source()
    assert 'OBJECT_STORAGE_ENABLED="${INSTALL_OBJECT_STORAGE:-false}"' in source
    assert "set_env_value CONTAINER_OBJECT_STORAGE_PROVIDER filesystem" in source
    assert 'set_env_value CONTAINER_OBJECT_STORAGE_ENDPOINT_URL ""' in source
    assert 'if [[ "$OBJECT_STORAGE_ENABLED" == "true" ]]' in source
    assert "compose --profile object-storage up -d minio minio-init" in source


def test_installer_preflight_accepts_supported_ubuntu_releases() -> None:
    source = _source()
    platform_check = _shell_function(source, "validate_platform")

    assert "ubuntu:22.04" in platform_check
    assert "ubuntu:24.04" in platform_check
    assert "ubuntu:26.04" in platform_check


def test_installer_preflight_accepts_supported_debian_releases() -> None:
    source = _source()
    platform_check = _shell_function(source, "validate_platform")

    assert "debian:12" in platform_check
    assert "debian:13" in platform_check


def test_installer_preflight_rejects_uncertified_linux_releases() -> None:
    source = _source()
    detection = _shell_function(source, "detect_platform")
    platform_check = _shell_function(source, "validate_platform")

    assert '*) PLATFORM_KIND="unsupported"' in detection
    assert "is not a certified SHEKU installation platform" in platform_check
    assert "Supported Linux releases:" in source
    assert "No installation changes were made." in source


def test_installer_preflight_supports_macos_and_requires_wsl2_for_windows() -> None:
    source = _source()

    assert "Darwin)" in source
    assert 'PLATFORM_KIND="macos"' in source
    assert 'PLATFORM_KIND="wsl"' in source
    assert "WSL_INTEROP" in source
    assert "WSL_DISTRO_NAME" in source
    assert "WSL1 is not supported" in source
    assert "Windows 11 with WSL2" in source
    assert "${kernel_release,,}" not in source
    assert "${docker_info,,}" not in source


def test_installer_preflight_normalizes_supported_architectures() -> None:
    source = _source()
    architecture_check = _shell_function(source, "normalize_architecture")

    assert 'x86_64|amd64) PLATFORM_ARCH="amd64"' in architecture_check
    assert 'aarch64|arm64) PLATFORM_ARCH="arm64"' in architecture_check
    assert "Architecture '$machine' is not supported" in architecture_check


def test_installer_preflight_requires_host_commands() -> None:
    source = _source()
    preflight = _shell_function(source, "run_preflight")

    assert "require_command bash Bash" in preflight
    assert "require_command git Git" in preflight
    assert "require_command curl curl" in preflight
    assert "require_command openssl OpenSSL" in preflight
    assert "require_command docker Docker" in preflight


def test_installer_preflight_validates_docker_and_compose_versions() -> None:
    source = _source()
    version_check = _shell_function(source, "check_docker_versions")

    assert "docker --version" in version_check
    assert "version_from_output" in version_check
    assert "docker compose version --short" in version_check
    assert "Docker Compose v2 is required" in version_check
    assert "10#$compose_major < 2" in version_check


def test_installer_preflight_distinguishes_daemon_permissions_from_unavailability() -> None:
    source = _source()
    daemon_check = _shell_function(source, "check_docker_daemon")

    assert "docker info" in daemon_check
    assert "current user cannot access the Docker daemon" in daemon_check
    assert "Docker daemon is not reachable" in daemon_check


def test_installer_checks_ports_during_preflight() -> None:
    source = _source()
    preflight = _shell_function(source, "run_preflight")

    for port in ("3000", "8000"):
        assert f"require_available_port {port}" in preflight
    assert 'require_available_port "$POSTGRES_HOST_PORT" postgres' in preflight
    assert 'require_available_port "$IDENTITY_POSTGRES_HOST_PORT" identity-postgres' in preflight


def test_installer_preflight_runs_before_any_host_changes() -> None:
    source = _source()
    preflight = _shell_function(source, "run_preflight")
    preflight_call = source.index("\nrun_preflight\n")

    for forbidden in (
        "mkdir",
        "set_env_value",
        "ensure_generated_secret",
        "compose build",
        "compose up",
    ):
        assert forbidden not in preflight

    assert preflight_call < source.index('mkdir -p "$(dirname "$ENV_FILE")"')
    assert preflight_call < source.index('POSTGRES_PASSWORD="$(ensure_generated_secret POSTGRES_PASSWORD)"')
    assert preflight_call < source.index("compose build migrator identity-migrator api scheduler portal")
    assert preflight_call < source.index("compose up -d postgres identity-postgres")


def test_installer_preflight_reports_a_readable_summary() -> None:
    source = _source()

    for message in (
        "SHEKU installation preflight",
        "Operating system: %s",
        "Architecture: %s",
        "Docker Compose: available",
        "Docker daemon: reachable",
        "Ports: available",
        "Existing storage: compatible",
        "Preflight: PASSED",
    ):
        assert message in source


def test_installer_does_not_require_application_runtime_tools_on_the_host() -> None:
    source = _source()

    for command in ("python", "python3", "node", "npm", "psql", "alembic", "redis", "minio", "ollama"):
        assert f"require_command {command}" not in source


def test_installer_does_not_install_host_dependencies() -> None:
    source = _source()

    for installer in ("apt ", "apt-get", "brew ", "winget", "choco", "curl | sh", "sudo "):
        assert installer not in source


def test_installer_lets_compose_run_migrators_and_filesystem_initialization_once() -> None:
    source = _source()
    assert "run --rm migrator" not in source
    assert "run --rm identity-migrator" not in source
    assert "run --rm filesystem-storage-init" not in source
    assert "compose up -d api scheduler portal" in source


def test_installer_does_not_require_community_intent_model_bootstrap() -> None:
    source = _source()
    assert "bootstrap-community-intent-model" not in source


def test_installer_checks_storage_compatibility_before_compose_up() -> None:
    source = _source()
    preflight = _shell_function(source, "require_compatible_storage")

    assert "storage_volumes=(postgres_data identity_postgres_data filesystem_storage_data)" in preflight
    assert 'postgres_data) expected_path="$POSTGRES_DATA_PATH"' in preflight
    assert 'identity_postgres_data) expected_path="$IDENTITY_POSTGRES_DATA_PATH"' in preflight
    assert 'filesystem_storage_data) expected_path="$FILESYSTEM_STORAGE_PATH"' in preflight
    assert 'expected_config="local|none|bind|$expected_path"' in preflight
    assert 'COMPOSE_PROJECT="${COMPOSE_PROJECT:-industrial-ai-platform}"' in source
    assert 'volume_name="${COMPOSE_PROJECT}_${volume_key}"' in preflight
    assert 'incompatible_volumes+=("$volume_name")' in preflight
    assert "Installation stopped to protect persisted data." in preflight
    assert "exit 1" in preflight
    preflight = _shell_function(source, "run_preflight")
    assert "require_compatible_storage" in preflight
    assert source.index("\nrun_preflight\n") < source.index("compose up -d postgres identity-postgres")


def test_installer_allows_absent_or_compatible_storage() -> None:
    source = _source()
    preflight = _shell_function(source, "require_compatible_storage")

    assert 'if [[ -z "$existing_volume" ]]' in preflight
    assert "continue" in preflight
    assert 'if [[ "$actual_config" != "$expected_config" ]]' in preflight
    assert "if ((${#incompatible_volumes[@]} == 0))" in preflight
    assert "return 0" in preflight


def test_installer_never_automatically_removes_or_recreates_storage() -> None:
    source = _source()

    assert "docker volume rm" not in source
    assert "compose down" not in source
    assert "--force-recreate" not in source
    assert "--renew-anon-volumes" not in source
    assert "yes |" not in source


def test_installer_keeps_ai_optional_and_disabled_by_default() -> None:
    source = _source()
    assert "set_env_value FEATURE_EMBEDDINGS_ENABLED false" in source
    assert "set_env_value FEATURE_VECTOR_RETRIEVAL_ENABLED false" in source
    assert "--profile ai" not in source
