#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.production.yml)
ENV_FILE="${INSTALL_ENV_FILE:-$ROOT_DIR/.env}"
OBJECT_STORAGE_ENABLED="${INSTALL_OBJECT_STORAGE:-false}"

if [[ -n "${INSTALL_DATA_ROOT:-}" ]]; then
  DATA_ROOT="$INSTALL_DATA_ROOT"
else
  DATA_ROOT="${XDG_DATA_HOME:-${HOME:?HOME is required when INSTALL_DATA_ROOT is not set}/.local/share}/sheku"
fi

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

preflight_fail() {
  printf '\nERROR: %s\n\n' "$*" >&2
  printf 'No installation changes were made.\n' >&2
  exit 1
}

require_command() {
  local executable="$1"
  local name="$2"
  command -v "$executable" >/dev/null 2>&1 \
    || preflight_fail "$name is required but was not found on PATH."
  printf '%s: available\n' "$name"
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

supported_linux_releases() {
  printf '%s\n' \
    'Supported Linux releases:' \
    '- Ubuntu 22.04 LTS' \
    '- Ubuntu 24.04 LTS' \
    '- Ubuntu 26.04 LTS' \
    '- Debian 12' \
    '- Debian 13'
}

unsupported_linux_fail() {
  printf '\nERROR: %s\n\n' "$*" >&2
  supported_linux_releases >&2
  printf '\nNo installation changes were made.\n' >&2
  exit 1
}

detect_platform() {
  local kernel_name
  local kernel_release
  local kernel_release_lower
  local proc_version=""
  local proc_version_lower=""
  local ID=""
  local VERSION_ID=""
  local PRETTY_NAME=""
  local NAME=""

  kernel_name="$(uname -s)"
  kernel_release="$(uname -r)"
  PLATFORM_KERNEL="$kernel_name"
  case "$kernel_name" in
    Darwin)
      PLATFORM_KIND="macos"
      PLATFORM_ID="macos"
      if command -v sw_vers >/dev/null 2>&1; then
        PLATFORM_DISPLAY="macOS $(sw_vers -productVersion)"
      else
        PLATFORM_DISPLAY="macOS"
      fi
      ;;
    Linux)
      if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
      fi
      PLATFORM_ID="$(lowercase "$ID")"
      PLATFORM_VERSION="$VERSION_ID"
      PLATFORM_DISPLAY="${PRETTY_NAME:-${NAME:-Linux} ${VERSION_ID:-}}"
      [[ -r /proc/version ]] && proc_version="$(</proc/version)"
      kernel_release_lower="$(lowercase "$kernel_release")"
      proc_version_lower="$(lowercase "$proc_version")"
      if [[ -n "${WSL_INTEROP:-}" \
        || -n "${WSL_DISTRO_NAME:-}" \
        || "$kernel_release_lower" == *microsoft* \
        || "$proc_version_lower" == *microsoft* ]]; then
        PLATFORM_KIND="wsl"
        if [[ "$kernel_release_lower" != *wsl2* && "$kernel_release_lower" != *microsoft-standard* ]]; then
          WSL_VERSION="1"
        else
          WSL_VERSION="2"
        fi
        PLATFORM_DISPLAY="${PLATFORM_DISPLAY% } (WSL${WSL_VERSION})"
      else
        case "$PLATFORM_ID" in
          ubuntu) PLATFORM_KIND="ubuntu" ;;
          debian) PLATFORM_KIND="debian" ;;
          *) PLATFORM_KIND="unsupported" ;;
        esac
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*)
      PLATFORM_KIND="unsupported"
      PLATFORM_ID="windows-shell"
      PLATFORM_DISPLAY="Windows shell ($kernel_name)"
      ;;
    *)
      PLATFORM_KIND="unsupported"
      PLATFORM_ID="$(lowercase "$kernel_name")"
      PLATFORM_DISPLAY="$kernel_name"
      ;;
  esac
}

normalize_architecture() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) PLATFORM_ARCH="amd64" ;;
    aarch64|arm64) PLATFORM_ARCH="arm64" ;;
    *) preflight_fail "Architecture '$machine' is not supported. Supported architectures: amd64 and arm64." ;;
  esac
}

validate_platform() {
  local linux_id="$PLATFORM_ID"
  local linux_version="${PLATFORM_VERSION:-}"

  if [[ "$PLATFORM_KIND" == "wsl" ]]; then
    if [[ "$WSL_VERSION" != "2" ]]; then
      preflight_fail "WSL1 is not supported. Use Windows 11 with WSL2 and Docker Desktop integration."
    fi
  elif [[ "$PLATFORM_KIND" == "macos" ]]; then
    return 0
  elif [[ "$PLATFORM_KIND" == "unsupported" ]]; then
    if [[ "$PLATFORM_ID" == "windows-shell" ]]; then
      preflight_fail "Run this installer from a supported Linux distribution in WSL2, not directly from cmd.exe, PowerShell, or a Windows compatibility shell."
    fi
    if [[ "$PLATFORM_KERNEL" == "Linux" ]]; then
      unsupported_linux_fail "$PLATFORM_DISPLAY is not a certified SHEKU installation platform."
    fi
    preflight_fail "$PLATFORM_DISPLAY is not a supported SHEKU installation platform. Use a certified Linux release, macOS, or Windows 11 with WSL2."
  fi

  case "$linux_id:$linux_version" in
    ubuntu:22.04|ubuntu:24.04|ubuntu:26.04|debian:12|debian:13) ;;
    ubuntu:*|debian:*)
      unsupported_linux_fail "$PLATFORM_DISPLAY is not a supported SHEKU installation platform."
      ;;
    *)
      unsupported_linux_fail "$PLATFORM_DISPLAY is not a certified SHEKU installation platform."
      ;;
  esac
}

version_from_output() {
  local output="$1"
  if [[ "$output" =~ ([0-9]+\.[0-9]+(\.[0-9]+)?) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

check_docker_versions() {
  local docker_output
  local compose_output
  local compose_major

  docker_output="$(docker --version 2>&1)" \
    || preflight_fail "Docker is installed but its version could not be read."
  DOCKER_VERSION="$(version_from_output "$docker_output")" \
    || preflight_fail "Docker returned an unrecognized version string."
  printf 'Docker: available (%s)\n' "$DOCKER_VERSION"

  compose_output="$(docker compose version --short 2>&1)" \
    || preflight_fail "Docker Compose v2 is required. Install or enable the Docker Compose plugin."
  COMPOSE_VERSION="$(version_from_output "$compose_output")" \
    || preflight_fail "Docker Compose returned an unrecognized version string."
  compose_major="${COMPOSE_VERSION%%.*}"
  if ((10#$compose_major < 2)); then
    preflight_fail "Docker Compose v2 is required; detected version $COMPOSE_VERSION."
  fi
  printf 'Docker Compose: available (%s)\n' "$COMPOSE_VERSION"
}

check_docker_daemon() {
  local docker_info
  local docker_info_lower
  if docker_info="$(docker info 2>&1)"; then
    printf 'Docker daemon: reachable\n'
    return 0
  fi
  docker_info_lower="$(lowercase "$docker_info")"
  if [[ "$docker_info_lower" == *permission*denied* \
    || "$docker_info_lower" == *access*denied* \
    || "$docker_info_lower" == *permission* ]]; then
    preflight_fail "Docker is installed, but the current user cannot access the Docker daemon. Configure Docker permissions or Docker Desktop integration and retry."
  fi
  preflight_fail "Docker is installed, but the Docker daemon is not reachable. Start Docker or Docker Desktop and retry."
}

read_env_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

env_value_or_default() {
  local key="$1"
  local default_value="$2"
  local current
  current="$(read_env_value "$key")"
  printf '%s' "${current:-$default_value}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp)"
  if [[ -f "$ENV_FILE" ]]; then
    awk -v key="$key" -v value="$value" '
      BEGIN { replaced = 0 }
      index($0, key "=") == 1 {
        if (!replaced) {
          print key "=" value
          replaced = 1
        }
        next
      }
      { print }
      END {
        if (!replaced) print key "=" value
      }
    ' "$ENV_FILE" > "$temporary"
  else
    printf '%s=%s\n' "$key" "$value" > "$temporary"
  fi
  install -m 600 "$temporary" "$ENV_FILE"
  rm -f "$temporary"
}

ensure_env_value() {
  local key="$1"
  local default_value="$2"
  local current
  current="$(read_env_value "$key")"
  if [[ -z "$current" ]]; then
    set_env_value "$key" "$default_value"
    current="$default_value"
  fi
  printf '%s' "$current"
}

ensure_generated_secret() {
  local key="$1"
  local current
  current="$(read_env_value "$key")"
  if [[ -z "$current" ]]; then
    current="$(openssl rand -hex 32)"
    set_env_value "$key" "$current"
  fi
  printf '%s' "$current"
}

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(read_env_value COMPOSE_PROJECT_NAME)}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-industrial-ai-platform}"

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" \
    "${COMPOSE_FILES[@]}" \
    "$@"
}

stack_service_running() {
  local service="$1"
  [[ -n "$(
    docker ps \
      --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
      --filter "label=com.docker.compose.service=$service" \
      --quiet
  )" ]]
}

volume_storage_config() {
  local volume_name="$1"
  docker volume inspect \
    --format '{{.Driver}}|{{with .Options}}{{index . "type"}}|{{index . "o"}}|{{index . "device"}}{{end}}' \
    "$volume_name"
}

require_compatible_storage() {
  local volume_key
  local expected_path
  local volume_name
  local existing_volume
  local actual_config
  local expected_config
  local incompatible_volumes=()
  local storage_volumes=(postgres_data identity_postgres_data filesystem_storage_data)

  for volume_key in "${storage_volumes[@]}"; do
    case "$volume_key" in
      postgres_data) expected_path="$POSTGRES_DATA_PATH" ;;
      identity_postgres_data) expected_path="$IDENTITY_POSTGRES_DATA_PATH" ;;
      filesystem_storage_data) expected_path="$FILESYSTEM_STORAGE_PATH" ;;
    esac
    volume_name="${COMPOSE_PROJECT}_${volume_key}"
    existing_volume="$(
      docker volume ls --quiet --filter "name=$volume_name" \
        | while IFS= read -r candidate; do
            if [[ "$candidate" == "$volume_name" ]]; then
              printf '%s\n' "$candidate"
            fi
          done
    )" || preflight_fail "Existing Docker volumes could not be listed."
    if [[ -z "$existing_volume" ]]; then
      continue
    fi

    actual_config="$(volume_storage_config "$volume_name")" \
      || preflight_fail "Existing Docker volume '$volume_name' could not be inspected."
    expected_config="local|none|bind|$expected_path"
    if [[ "$actual_config" != "$expected_config" ]]; then
      incompatible_volumes+=("$volume_name")
    fi
  done

  if ((${#incompatible_volumes[@]} == 0)); then
    return 0
  fi

  printf '\nERROR: existing SHEKU Docker volumes use a legacy or incompatible storage configuration.\n' >&2
  printf 'Installation stopped to protect persisted data.\n\n' >&2
  printf 'Incompatible volumes:\n' >&2
  printf '  %s\n' "${incompatible_volumes[@]}" >&2
  printf '\nNo installation changes were made.\n\n' >&2
  printf 'Review or migrate the existing installation before retrying.\n' >&2
  exit 1
}

port_is_open() {
  local port="$1"
  (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
}

require_available_port() {
  local port="$1"
  local service="$2"
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    preflight_fail "Port '$port' is invalid."
  fi
  if ((10#$port < 1 || 10#$port > 65535)); then
    preflight_fail "Port '$port' is invalid."
  fi
  if port_is_open "$port" && ! stack_service_running "$service"; then
    preflight_fail "Port $port is already in use."
  fi
}

wait_for_api() {
  local attempts=60
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_portal() {
  local attempts=60
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS http://127.0.0.1:3000/setup >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

installation_state() {
  local response
  local state
  response="$(curl -fsS http://127.0.0.1:8000/setup/status)" \
    || fail "Installation status could not be read from the API."
  state="$(
    printf '%s' "$response" \
      | sed -n 's/.*"state"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
  )"
  case "$state" in
    UNCONFIGURED|IN_PROGRESS|READY_TO_COMPLETE|COMPLETED)
      printf '%s' "$state"
      ;;
    *)
      fail "Installation status returned an unsupported state."
      ;;
  esac
}

run_preflight() {
  printf '\nSHEKU installation preflight\n\n'

  detect_platform
  printf 'Operating system: %s\n' "$PLATFORM_DISPLAY"
  normalize_architecture
  printf 'Architecture: %s\n' "$PLATFORM_ARCH"
  validate_platform

  require_command bash Bash
  require_command git Git
  require_command curl curl
  require_command openssl OpenSSL
  require_command docker Docker >/dev/null
  check_docker_versions
  check_docker_daemon

  [[ -f docker-compose.yml ]] || preflight_fail "docker-compose.yml was not found."
  [[ -f docker-compose.production.yml ]] || preflight_fail "docker-compose.production.yml was not found."
  if [[ "$OBJECT_STORAGE_ENABLED" != "true" && "$OBJECT_STORAGE_ENABLED" != "false" ]]; then
    preflight_fail "INSTALL_OBJECT_STORAGE must be 'true' or 'false'."
  fi

  POSTGRES_HOST_PORT="${POSTGRES_PORT:-$(read_env_value POSTGRES_PORT)}"
  POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"
  IDENTITY_POSTGRES_HOST_PORT="${IDENTITY_POSTGRES_PORT:-$(read_env_value IDENTITY_POSTGRES_PORT)}"
  IDENTITY_POSTGRES_HOST_PORT="${IDENTITY_POSTGRES_HOST_PORT:-5433}"

  require_available_port 3000 portal
  require_available_port 8000 api
  require_available_port "$POSTGRES_HOST_PORT" postgres
  require_available_port "$IDENTITY_POSTGRES_HOST_PORT" identity-postgres
  printf 'Ports: available\n'

  POSTGRES_DATA_PATH="$(env_value_or_default POSTGRES_DATA_PATH "$DATA_ROOT/postgres")"
  IDENTITY_POSTGRES_DATA_PATH="$(env_value_or_default IDENTITY_POSTGRES_DATA_PATH "$DATA_ROOT/identity-postgres")"
  FILESYSTEM_STORAGE_PATH="$(env_value_or_default FILESYSTEM_STORAGE_PATH "$DATA_ROOT/filesystem")"
  require_compatible_storage
  printf 'Existing storage: compatible\n'

  printf '\nPreflight: PASSED\n'
}

run_preflight

printf '\nSHEKU installation\n\n'

mkdir -p "$(dirname "$ENV_FILE")"
mkdir -p "$DATA_ROOT"
chmod 700 "$DATA_ROOT"

POSTGRES_DATA_PATH="$(ensure_env_value POSTGRES_DATA_PATH "$DATA_ROOT/postgres")"
IDENTITY_POSTGRES_DATA_PATH="$(ensure_env_value IDENTITY_POSTGRES_DATA_PATH "$DATA_ROOT/identity-postgres")"
FILESYSTEM_STORAGE_PATH="$(ensure_env_value FILESYSTEM_STORAGE_PATH "$DATA_ROOT/filesystem")"
MINIO_DATA_PATH="$(ensure_env_value MINIO_DATA_PATH "$DATA_ROOT/minio")"
RUNTIME_DATA_PATH="$(ensure_env_value RUNTIME_DATA_PATH "$DATA_ROOT/runtime")"
BACKUP_DATA_PATH="$(ensure_env_value BACKUP_DATA_PATH "$DATA_ROOT/backups")"

mkdir -p \
  "$POSTGRES_DATA_PATH" \
  "$IDENTITY_POSTGRES_DATA_PATH" \
  "$FILESYSTEM_STORAGE_PATH" \
  "$MINIO_DATA_PATH" \
  "$RUNTIME_DATA_PATH" \
  "$BACKUP_DATA_PATH"

POSTGRES_USER="$(ensure_env_value POSTGRES_USER industrial_ai)"
POSTGRES_DB="$(ensure_env_value POSTGRES_DB industrial_ai)"
POSTGRES_PASSWORD="$(ensure_generated_secret POSTGRES_PASSWORD)"
IDENTITY_POSTGRES_USER="$(ensure_env_value IDENTITY_POSTGRES_USER industrial_ai_identity)"
IDENTITY_POSTGRES_DB="$(ensure_env_value IDENTITY_POSTGRES_DB industrial_ai_identity)"
IDENTITY_POSTGRES_PASSWORD="$(ensure_generated_secret IDENTITY_POSTGRES_PASSWORD)"
MINIO_ROOT_USER="$(ensure_env_value MINIO_ROOT_USER industrial_ai)"
SETUP_ACCESS_CODE="$(ensure_generated_secret SHEKU_SETUP_TOKEN)"

set_env_value CONTAINER_DATABASE_URL \
  "postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
IDENTITY_DATABASE_AUTH="${IDENTITY_POSTGRES_USER}:${IDENTITY_POSTGRES_PASSWORD}"
set_env_value CONTAINER_IDENTITY_DATABASE_URL \
  "postgresql+psycopg://${IDENTITY_DATABASE_AUTH}@identity-postgres:5432/${IDENTITY_POSTGRES_DB}"
unset IDENTITY_DATABASE_AUTH
if [[ "$OBJECT_STORAGE_ENABLED" == "true" ]]; then
  MINIO_ROOT_PASSWORD="$(ensure_generated_secret MINIO_ROOT_PASSWORD)"
  OBJECT_STORAGE_BUCKET="$(ensure_env_value OBJECT_STORAGE_BUCKET documents)"
  set_env_value CONTAINER_OBJECT_STORAGE_PROVIDER minio
  set_env_value CONTAINER_OBJECT_STORAGE_ENDPOINT_URL http://minio:9000
  set_env_value CONTAINER_OBJECT_STORAGE_ACCESS_KEY "$MINIO_ROOT_USER"
  set_env_value CONTAINER_OBJECT_STORAGE_SECRET_KEY "$MINIO_ROOT_PASSWORD"
  set_env_value CONTAINER_OBJECT_STORAGE_BUCKET "$OBJECT_STORAGE_BUCKET"
  unset MINIO_ROOT_PASSWORD
elif [[ "$OBJECT_STORAGE_ENABLED" == "false" ]]; then
  set_env_value CONTAINER_OBJECT_STORAGE_PROVIDER filesystem
  set_env_value CONTAINER_OBJECT_STORAGE_ENDPOINT_URL ""
  set_env_value CONTAINER_OBJECT_STORAGE_ACCESS_KEY ""
  set_env_value CONTAINER_OBJECT_STORAGE_SECRET_KEY ""
  set_env_value CONTAINER_OBJECT_STORAGE_BUCKET ""
else
  fail "INSTALL_OBJECT_STORAGE must be 'true' or 'false'."
fi
set_env_value AUTHENTICATION_REQUIRED true
set_env_value API_DOCS_ENABLED false
set_env_value FEATURE_EMBEDDINGS_ENABLED false
set_env_value FEATURE_VECTOR_RETRIEVAL_ENABLED false
set_env_value FEATURE_WORKER_ENABLED false
set_env_value FEATURE_ENTERPRISE_EXTENSIONS_ENABLED false
chmod 600 "$ENV_FILE"

unset POSTGRES_PASSWORD IDENTITY_POSTGRES_PASSWORD

compose config --quiet
compose build migrator identity-migrator api scheduler portal

compose up -d postgres identity-postgres

if [[ "$OBJECT_STORAGE_ENABLED" == "true" ]]; then
  compose --profile object-storage up -d minio minio-init
  compose --profile object-storage up -d api scheduler portal
else
  compose up -d api scheduler portal
fi

wait_for_api || fail "API did not become ready within the installation timeout"
wait_for_portal || fail "Portal did not become available within the installation timeout"

INSTALLATION_STATE="$(installation_state)"
if [[ "$INSTALLATION_STATE" == "COMPLETED" ]]; then
  compose exec -T api python -m app.cli reconcile-installation-platform-owner \
    || fail "Completed installation platform owner reconciliation failed."
  unset SETUP_ACCESS_CODE
  printf '\nSHEKU is ready.\n\n'
  printf 'Portal: http://127.0.0.1:3000\n'
  printf 'API health: http://127.0.0.1:8000/health/ready\n'
  printf 'Installation: configured\n'
else
  printf '\nSHEKU infrastructure is ready.\n\n'
  printf 'Portal: http://127.0.0.1:3000/setup\n'
  printf 'API health: http://127.0.0.1:8000/health/ready\n'
  printf 'Setup access code: %s\n\n' "$SETUP_ACCESS_CODE"
  printf 'Complete the first-run setup in the browser.\n'
  unset SETUP_ACCESS_CODE
fi
