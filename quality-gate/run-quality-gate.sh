#!/usr/bin/env bash

set -u
set -o pipefail

run_all() {
  local result=0
  local command_result
  for command in "$@"; do
    bash -c "$command"
    command_result=$?
    if [ "$command_result" -ne 0 ]; then
      result=1
    fi
  done
  return "$result"
}

case "${1:-help}" in
  backend-tests)
    cd /workspace
    exec python -m pytest -p no:cacheprovider
    ;;
  security-tests)
    cd /workspace
    exec python -m pytest -p no:cacheprovider \
      apps/api/tests/test_authentication_core.py \
      apps/api/tests/test_authentication_core_postgresql.py \
      apps/api/tests/test_global_role_management_postgresql.py \
      apps/api/tests/test_global_user_management_postgresql.py
    ;;
  migrations-check)
    cd /workspace/apps/api
    exec python /workspace/quality-gate/check_migrations.py
    ;;
  ruff)
    cd /workspace
    exec python -m ruff check \
      apps/api/app/core apps/api/app/security \
      apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py tests
    ;;
  ruff-expanded)
    cd /workspace
    exec python -m ruff check \
      apps/api/main.py apps/api/app/identity apps/api/app/services \
      apps/api/app/api apps/api/tests
    ;;
  ruff-format)
    cd /workspace
    exec python -m ruff format --check \
      apps/api/app/core apps/api/app/security \
      apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py tests
    ;;
  ruff-format-expanded)
    cd /workspace
    exec python -m ruff format --check \
      apps/api/main.py apps/api/app/identity apps/api/app/services \
      apps/api/app/api apps/api/tests
    ;;
  mypy)
    cd /workspace
    exec python -m mypy \
      apps/api/app/core apps/api/app/security \
      apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py
    ;;
  mypy-expanded)
    cd /workspace
    exec python -m mypy \
      apps/api/main.py apps/api/app/identity apps/api/app/services \
      apps/api/app/api apps/api/tests
    ;;
  bandit)
    cd /workspace
    exec python -m bandit -q -r \
      apps/api/app/core apps/api/app/security \
      apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py
    ;;
  bandit-expanded)
    cd /workspace
    exec python -m bandit -q -r \
      apps/api/main.py apps/api/app/identity apps/api/app/services \
      apps/api/app/api apps/api/tests
    ;;
  typescript)
    cd /workspace/apps/admin-portal
    exec /workspace/node_modules/.bin/tsc --noEmit --pretty false
    ;;
  eslint)
    cd /workspace/apps/admin-portal
    exec /workspace/node_modules/.bin/eslint .
    ;;
  portal-build)
    cd /workspace/apps/admin-portal
    exec npm run build
    ;;
  portal-contracts)
    cd /workspace/apps/admin-portal
    run_all \
      "npm run check:i18n" \
      "npm run check:ai-configuration" \
      "npm run check:security-global-roles" \
      "npm run check:security-global-users" \
      "npm run check:session-lifecycle" \
      "npm run check:operations" \
      "node scripts/check-document-structure-contract.mjs" \
      "node scripts/check-global-user-editor-state.mjs" \
      "node scripts/check-operational-health-issues-contract.mjs" \
      "node scripts/check-organization-health-scope-contract.mjs"
    ;;
  portal-editorial-audit)
    cd /workspace/apps/admin-portal
    exec node scripts/audit-visible-text.mjs
    ;;
  npm-audit-production)
    cd /workspace/apps/admin-portal
    exec npm audit --omit=dev --audit-level=high --json
    ;;
  npm-audit-all)
    cd /workspace/apps/admin-portal
    exec npm audit --include=dev --audit-level=high --json
    ;;
  python-audit)
    cd /workspace/apps/api
    exec pip-audit --requirement requirements.txt --format json --progress-spinner off
    ;;
  image-contracts)
    cd /workspace
    run_all \
      "python apps/api/scripts/check_container_portability_contract.py" \
      "python apps/api/scripts/check_container_supply_chain_contract.py" \
      "python apps/api/scripts/check_api_production_image_contract.py" \
      "python apps/api/scripts/check_portal_production_image_contract.py" \
      "python apps/api/scripts/check_container_release_plan_contract.py"
    ;;
  help|*)
    printf '%s\n' \
      'Quality Gate container entrypoint.' \
      'Invoke it through ./scripts/run-quality-gate.sh.'
    ;;
esac
