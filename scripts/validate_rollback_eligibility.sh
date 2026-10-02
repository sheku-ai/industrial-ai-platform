#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"
PYTHON="${API_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "API virtual environment Python is missing or not executable: ${PYTHON}" >&2
  exit 1
fi

export PYTHONPATH="${API_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${API_DIR}"
exec "${PYTHON}" "scripts/validate_release_operational_evidence.py" rollback "$@"
