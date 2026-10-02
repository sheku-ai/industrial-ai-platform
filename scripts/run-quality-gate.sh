#!/usr/bin/env bash

set -u
set -o pipefail

PROJECT_NAME="industrial-ai-quality"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPOSITORY_ROOT/docker-compose.quality.yml"
RELEASE=false
CACHE_MODE="${QUALITY_GATE_CACHE_MODE:-warm}"
COMPOSE_BUILD_ARGUMENTS=()
DOCKER_BUILD_ARGUMENTS=()

case "$CACHE_MODE" in
  warm) ;;
  cold)
    COMPOSE_BUILD_ARGUMENTS+=(--no-cache --pull)
    DOCKER_BUILD_ARGUMENTS+=(--no-cache --pull)
    ;;
  *)
    printf 'QUALITY_GATE_CACHE_MODE must be warm or cold, received: %s\n' "$CACHE_MODE" >&2
    exit 2
    ;;
esac

if [ "${1:-}" = "--release" ]; then
  RELEASE=true
  shift
fi
if [ "$#" -ne 0 ]; then
  printf 'Usage: %s [--release]\n' "$0" >&2
  exit 2
fi

cd "$REPOSITORY_ROOT" || exit 2

COMMIT_SHA="$(git rev-parse HEAD)"
BRANCH="$(git branch --show-current)"
if [ -n "$(git status --short)" ]; then
  WORKTREE_DIRTY=true
else
  WORKTREE_DIRTY=false
fi
QUALITY_IMAGE_TAG="${COMMIT_SHA:0:12}"
export QUALITY_IMAGE_TAG

REPORT_DIRECTORY="$REPOSITORY_ROOT/runtime/quality-reports"
JSON_REPORT="$REPORT_DIRECTORY/$COMMIT_SHA.json"
MARKDOWN_REPORT="$REPORT_DIRECTORY/$COMMIT_SHA.md"
PREVIOUS_LOG_DIRECTORY="$REPORT_DIRECTORY/$COMMIT_SHA.logs"
mkdir -p "$REPORT_DIRECTORY"
if [ -e "$JSON_REPORT" ] || [ -e "$MARKDOWN_REPORT" ] || [ -e "$PREVIOUS_LOG_DIRECTORY" ]; then
  HISTORY_DIRECTORY="$REPORT_DIRECTORY/history/$COMMIT_SHA/$(date -u +'%Y%m%dT%H%M%SZ')-$$"
  mkdir -p "$HISTORY_DIRECTORY"
  for previous_path in "$JSON_REPORT" "$MARKDOWN_REPORT" "$PREVIOUS_LOG_DIRECTORY"; do
    if [ -e "$previous_path" ]; then
      mv "$previous_path" "$HISTORY_DIRECTORY/"
    fi
  done
  printf 'Archived previous evidence: %s\n' "${HISTORY_DIRECTORY#"$REPOSITORY_ROOT"/}"
fi
LOG_DIRECTORY="$REPORT_DIRECTORY/$COMMIT_SHA.logs"
RESULTS_FILE="$LOG_DIRECTORY/results.tsv"
mkdir -p "$LOG_DIRECTORY"
: > "$RESULTS_FILE"

STARTED_EPOCH="$(date +%s)"
STARTED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
CLEANUP_DONE=false
CLEANUP_RESULT=1
BOOTSTRAP_RESULT=0

COMPOSE=(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE")

relative_path() {
  case "$1" in
    "$REPOSITORY_ROOT"/*) printf '%s' "${1#"$REPOSITORY_ROOT"/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

record_result() {
  local name="$1"
  local blocking="$2"
  local exit_code="$3"
  local duration="$4"
  local summary="$5"
  local log_path="$6"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$name" "$blocking" "$exit_code" "$duration" "$summary" "$(relative_path "$log_path")" \
    >> "$RESULTS_FILE"
  if [ "$exit_code" -eq 0 ]; then
    printf '[passed] %s\n' "$name"
  else
    printf '[failed] %s (exit %s)\n' "$name" "$exit_code"
  fi
}

run_stage() {
  local name="$1"
  local blocking="$2"
  local summary="$3"
  shift 3
  local log_path="$LOG_DIRECTORY/$name.log"
  local started completed result
  started="$(date +%s)"
  "$@" > "$log_path" 2>&1
  result=$?
  completed="$(date +%s)"
  record_result "$name" "$blocking" "$result" "$((completed - started))" "$summary" "$log_path"
  return 0
}

accumulate() {
  local current="$1"
  shift
  "$@"
  local result=$?
  if [ "$result" -ne 0 ]; then
    return 1
  fi
  return "$current"
}

cleanup_quality_project() {
  if [ "$CLEANUP_DONE" = true ]; then
    return "$CLEANUP_RESULT"
  fi
  CLEANUP_DONE=true
  local log_path="$LOG_DIRECTORY/cleanup_status.log"
  local started completed result remaining_containers remaining_volumes remaining_networks
  started="$(date +%s)"
  result=0
  {
    "${COMPOSE[@]}" down --volumes --timeout 10 || result=1
    remaining_containers="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT_NAME")"
    remaining_volumes="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT_NAME")"
    remaining_networks="$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT_NAME")"
    printf 'remaining_containers=%s\n' "${remaining_containers:-none}"
    printf 'remaining_volumes=%s\n' "${remaining_volumes:-none}"
    printf 'remaining_networks=%s\n' "${remaining_networks:-none}"
    if [ -n "$remaining_containers" ] || [ -n "$remaining_volumes" ] || [ -n "$remaining_networks" ]; then
      result=1
    fi
  } > "$log_path" 2>&1
  completed="$(date +%s)"
  CLEANUP_RESULT="$result"
  record_result \
    cleanup_status true "$result" "$((completed - started))" \
    "Compose teardown and label-based resource verification" "$log_path"
  return "$result"
}

cleanup_trap() {
  local original_result=$?
  trap - EXIT INT TERM
  cleanup_quality_project >/dev/null 2>&1 || true
  exit "$original_result"
}
trap cleanup_trap EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_product_image_checks() {
  local result=0
  local api_image="industrial-ai-quality-api-production:$QUALITY_IMAGE_TAG"
  local portal_image="industrial-ai-quality-portal-production:$QUALITY_IMAGE_TAG"
  local server_arch api_arch portal_arch api_user portal_user

  python3 quality-gate/check_compose_isolation.py || result=1
  "${COMPOSE[@]}" build "${COMPOSE_BUILD_ARGUMENTS[@]}" quality-platform-migrator || result=1
  docker build \
    "${DOCKER_BUILD_ARGUMENTS[@]}" \
    --file apps/admin-portal/Dockerfile \
    --target runtime \
    --tag "$portal_image" \
    . || result=1
  "${COMPOSE[@]}" run --rm --no-deps quality-image-contracts image-contracts || result=1

  server_arch="$(docker version --format '{{.Server.Arch}}' 2>/dev/null || true)"
  api_arch="$(docker image inspect "$api_image" --format '{{.Architecture}}' 2>/dev/null || true)"
  portal_arch="$(docker image inspect "$portal_image" --format '{{.Architecture}}' 2>/dev/null || true)"
  api_user="$(docker image inspect "$api_image" --format '{{.Config.User}}' 2>/dev/null || true)"
  portal_user="$(docker image inspect "$portal_image" --format '{{.Config.User}}' 2>/dev/null || true)"
  printf 'native_architecture server=%s api=%s portal=%s\n' "$server_arch" "$api_arch" "$portal_arch"
  printf 'configured_users api=%s portal=%s\n' "$api_user" "$portal_user"
  if [ -z "$server_arch" ] || [ "$api_arch" != "$server_arch" ] || [ "$portal_arch" != "$server_arch" ]; then
    result=1
  fi
  if [ "$api_user" != "platform" ] || [ "$portal_user" != "platform" ]; then
    result=1
  fi

  docker run --rm --network none --read-only --tmpfs /tmp \
    --entrypoint python "$api_image" -c '
import importlib.util
import json
import os
from pathlib import Path

root = Path("/app")
sensitive = sorted(
    str(path.relative_to(root))
    for path in root.rglob("*")
    if path.is_file()
    and (path.name.startswith(".env") or path.suffix.lower() in {".bak", ".backup", ".dump", ".sql"})
)
runtime = root / "runtime"
checks = {
    "effective_uid": os.getuid(),
    "non_root": os.getuid() != 0,
    "tests_absent": not (root / "tests").exists(),
    "pytest_absent": importlib.util.find_spec("pytest") is None,
    "sensitive_files_absent": not sensitive,
    "persisted_runtime_absent": runtime.is_dir() and not any(runtime.iterdir()),
}
checks["passed"] = all(value for key, value in checks.items() if key != "effective_uid")
print(json.dumps({**checks, "sensitive_files": sensitive}, sort_keys=True))
raise SystemExit(0 if checks["passed"] else 1)
' || result=1

  docker run --rm --network none --read-only --tmpfs /tmp \
    --entrypoint node "$portal_image" -e '
const fs = require("fs");
const path = require("path");
function walk(directory, findings = []) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(full, findings);
    else if (entry.name.startsWith(".env") || /\.(bak|backup|dump|sql)$/i.test(entry.name)) findings.push(full);
  }
  return findings;
}
const sensitive = walk("/app");
const checks = {
  effective_uid: process.getuid(),
  non_root: process.getuid() !== 0,
  standalone_server_present: fs.existsSync("/app/apps/admin-portal/server.js"),
  standalone_static_present: fs.existsSync("/app/apps/admin-portal/.next/static"),
  sensitive_files_absent: sensitive.length === 0,
};
checks.passed = Object.entries(checks).filter(([key]) => key !== "effective_uid").every(([, value]) => Boolean(value));
console.log(JSON.stringify({ ...checks, sensitive_files: sensitive }));
process.exit(checks.passed ? 0 : 1);
' || result=1

  if [ "$RELEASE" = true ]; then
    python3 scripts/run_multiarch_build_checks.py \
      --platforms linux/amd64,linux/arm64 \
      --timeout-seconds 3300 || result=1
  fi
  return "$result"
}

run_migration_checks() {
  local result=0
  "${COMPOSE[@]}" run --rm --no-deps quality-platform-migrator || result=1
  "${COMPOSE[@]}" run --rm --no-deps quality-identity-migrator || result=1
  "${COMPOSE[@]}" run --rm --no-deps quality-backend migrations-check || result=1
  return "$result"
}

printf 'Industrial AI Platform Quality Gate\n'
printf 'Commit: %s\n' "$COMMIT_SHA"
printf 'Mode: %s\n' "$([ "$RELEASE" = true ] && printf release || printf native)"
printf 'Build cache: %s\n' "$CACHE_MODE"

BOOTSTRAP_LOG="$LOG_DIRECTORY/validator-images.log"
"${COMPOSE[@]}" build \
  "${COMPOSE_BUILD_ARGUMENTS[@]}" \
  quality-backend quality-portal quality-npm-audit quality-python-audit quality-image-contracts \
  > "$BOOTSTRAP_LOG" 2>&1
BOOTSTRAP_RESULT=$?
if [ "$BOOTSTRAP_RESULT" -ne 0 ]; then
  printf '[failed] validator image build (remaining gates will still be attempted)\n'
fi

run_stage \
  production_images true \
  "Native production builds, image contents, non-root runtime, standalone portal, and static portability contracts" \
  run_product_image_checks

DATABASE_LOG="$LOG_DIRECTORY/database-startup.log"
"${COMPOSE[@]}" up -d --wait quality-platform-postgres quality-identity-postgres \
  > "$DATABASE_LOG" 2>&1
DATABASE_RESULT=$?
if [ "$DATABASE_RESULT" -ne 0 ]; then
  printf '[failed] disposable database startup (dependent gates will still be attempted)\n'
fi

run_stage migrations true \
  "Platform and identity migrations applied; chains have one repository head and databases are current" \
  run_migration_checks
run_stage backend_tests true "Root pytest suite configured by pyproject.toml" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend backend-tests
run_stage security_tests true "Authentication, identity, global role, and global user PostgreSQL regression" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend security-tests

run_stage ruff true "Blocking workflow-baseline Ruff check" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend ruff
run_stage ruff_expanded false "Informational Ruff check for main, identity, services, API routes, and API tests" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend ruff-expanded
run_stage ruff_format true "Blocking workflow-baseline Ruff format check" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend ruff-format
run_stage ruff_format_expanded false "Informational Ruff format check for expanded backend scope" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend ruff-format-expanded
run_stage mypy true "Blocking workflow-baseline Mypy analysis" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend mypy
run_stage mypy_expanded false "Informational Mypy analysis for expanded backend scope" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend mypy-expanded
run_stage bandit true "Blocking workflow-baseline Bandit analysis" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend bandit
run_stage bandit_expanded false "Informational Bandit analysis for expanded backend scope" \
  "${COMPOSE[@]}" run --rm --no-deps quality-backend bandit-expanded

run_stage typescript true "TypeScript no-emit compilation" \
  "${COMPOSE[@]}" run --rm --no-deps quality-portal typescript
run_stage eslint true "Portal ESLint" \
  "${COMPOSE[@]}" run --rm --no-deps quality-portal eslint
run_stage portal_build true "Production Next.js standalone build" \
  "${COMPOSE[@]}" run --rm --no-deps quality-portal portal-build
run_stage contracts true "All declared portal functional and security contracts" \
  "${COMPOSE[@]}" run --rm --no-deps quality-portal portal-contracts
run_stage portal_editorial_audit false "Informational portal visible-text audit" \
  "${COMPOSE[@]}" run --rm --no-deps quality-portal portal-editorial-audit

run_stage npm_audit_production true "Production dependencies at high severity threshold" \
  "${COMPOSE[@]}" run --rm --no-deps quality-npm-audit npm-audit-production
run_stage npm_audit_all false "Complete dependency tree at high severity threshold" \
  "${COMPOSE[@]}" run --rm --no-deps quality-npm-audit npm-audit-all
run_stage python_audit false "Pinned pip-audit against API production requirements" \
  "${COMPOSE[@]}" run --rm --no-deps quality-python-audit python-audit

cleanup_quality_project || true

COMPLETED_EPOCH="$(date +%s)"
COMPLETED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
DURATION_SECONDS="$((COMPLETED_EPOCH - STARTED_EPOCH))"

RENDER_ARGUMENTS=(
  python3 scripts/render-quality-report.py
  --results "$RESULTS_FILE"
  --output-json "$JSON_REPORT"
  --output-markdown "$MARKDOWN_REPORT"
  --commit-sha "$COMMIT_SHA"
  --branch "$BRANCH"
  --worktree-dirty "$WORKTREE_DIRTY"
  --started-at "$STARTED_AT"
  --completed-at "$COMPLETED_AT"
  --duration-seconds "$DURATION_SECONDS"
  --compose-project "$PROJECT_NAME"
)
if [ "$RELEASE" = true ]; then
  RENDER_ARGUMENTS+=(--release)
fi
"${RENDER_ARGUMENTS[@]}"
RENDER_RESULT=$?

stage_failed() {
  local stage_pattern="$1"
  awk -F '\t' -v pattern="$stage_pattern" '
    $1 ~ pattern && $2 == "true" && $3 != 0 { failed=1 }
    END { exit failed ? 0 : 1 }
  ' "$RESULTS_FILE"
}

if stage_failed '^(backend_tests|ruff|ruff_format|mypy|bandit)$'; then BACKEND_STATUS=failed; else BACKEND_STATUS=passed; fi
if stage_failed '^security_tests$'; then SECURITY_STATUS=failed; else SECURITY_STATUS=passed; fi
if stage_failed '^migrations$'; then MIGRATIONS_STATUS=failed; else MIGRATIONS_STATUS=passed; fi
if stage_failed '^(typescript|eslint|portal_build|contracts)$'; then PORTAL_STATUS=failed; else PORTAL_STATUS=passed; fi
if stage_failed '^npm_audit_production$'; then DEPENDENCIES_STATUS=failed; else DEPENDENCIES_STATUS=passed; fi
if stage_failed '^production_images$'; then IMAGES_STATUS=failed; else IMAGES_STATUS=passed; fi
if stage_failed '^cleanup_status$'; then CLEANUP_STATUS=failed; else CLEANUP_STATUS=completed; fi

if [ "$RENDER_RESULT" -eq 0 ]; then
  OVERALL_STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["overall_status"].upper())' "$JSON_REPORT")"
  OVERALL_RESULT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["overall_exit_code"])' "$JSON_REPORT")"
else
  OVERALL_STATUS=FAILED
  OVERALL_RESULT=1
fi

TERMINAL_SUMMARY="$LOG_DIRECTORY/terminal-summary.txt"
{
  printf '\nQUALITY GATE: %s\n' "$OVERALL_STATUS"
  printf 'Exit code: %s\n' "$OVERALL_RESULT"
  printf 'Commit: %s\n' "$COMMIT_SHA"
  printf 'Worktree dirty: %s\n' "$WORKTREE_DIRTY"
  printf 'Started: %s\n' "$STARTED_AT"
  printf 'Completed: %s\n' "$COMPLETED_AT"
  printf 'Backend: %s\n' "$BACKEND_STATUS"
  printf 'Security regression: %s\n' "$SECURITY_STATUS"
  printf 'Migrations: %s\n' "$MIGRATIONS_STATUS"
  printf 'Portal: %s\n' "$PORTAL_STATUS"
  printf 'Dependencies: %s\n' "$DEPENDENCIES_STATUS"
  printf 'Production images: %s\n' "$IMAGES_STATUS"
  printf 'Report: %s\n' "$(relative_path "$MARKDOWN_REPORT")"
  printf 'Cleanup: %s\n' "$CLEANUP_STATUS"
} | tee "$TERMINAL_SUMMARY"

exit "$OVERALL_RESULT"
