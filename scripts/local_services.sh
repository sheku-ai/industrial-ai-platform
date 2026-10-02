#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -x "$REPOSITORY_ROOT/apps/api/.venv/bin/python" ]; then
  PYTHON="$REPOSITORY_ROOT/apps/api/.venv/bin/python"
else
  echo "API virtual environment Python is missing or not executable: $REPOSITORY_ROOT/apps/api/.venv/bin/python" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/local_services.py" "$@"
