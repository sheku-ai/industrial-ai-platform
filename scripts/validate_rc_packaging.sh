#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT_DIR}/apps/api/.venv/bin/python"
ENV_FILE="${INSTALL_ENV_FILE:-$ROOT_DIR/.env}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "API virtual environment Python is missing or not executable: ${PYTHON}" >&2
  exit 1
fi

view_selected=false
for argument in "$@"; do
  case "${argument}" in
    --commands | --evidence | --gates | --checklist | --ci-contract | --manifest | \
      --release-contract | --release-summary | --compatibility | --artifacts)
      view_selected=true
      ;;
  esac
done

if [[ "${view_selected}" == "true" ]]; then
  validator_args=("$@")
else
  validator_args=(--release-contract "$@")
fi

if [[ ${DATABASE_URL+x} ]]; then
  exec "${PYTHON}" "${ROOT_DIR}/scripts/platform_release_candidate.py" "${validator_args[@]}"
fi

exec "${PYTHON}" - "${ROOT_DIR}" "${ENV_FILE}" "${validator_args[@]}" <<'PY'
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL

root = Path(sys.argv[1])
env_file = Path(sys.argv[2])
if not env_file.is_absolute():
    env_file = root / env_file
if not env_file.is_file():
    raise SystemExit("RC packaging configuration error: installer environment file is missing")

values = dotenv_values(env_file, interpolate=False)
required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
if any(not values.get(name) for name in required):
    raise SystemExit("RC packaging configuration error: PostgreSQL installer configuration is incomplete")

port_value = os.environ.get("POSTGRES_PORT") or values.get("POSTGRES_PORT") or "5432"
try:
    port = int(port_value)
    if not 1 <= port <= 65535:
        raise ValueError
except ValueError:
    raise SystemExit("RC packaging configuration error: POSTGRES_PORT is invalid") from None

url = URL.create(
    "postgresql+psycopg",
    username=values["POSTGRES_USER"],
    password=values["POSTGRES_PASSWORD"],
    host="127.0.0.1",
    port=port,
    query={"dbname": values["POSTGRES_DB"]},
)
environment = os.environ.copy()
environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
os.execve(
    sys.executable,
    [sys.executable, str(root / "scripts/platform_release_candidate.py"), *sys.argv[3:]],
    environment,
)
PY
