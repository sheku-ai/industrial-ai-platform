#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ -x "$REPOSITORY_ROOT/apps/api/.venv/bin/python" ]; then
  PYTHON="$REPOSITORY_ROOT/apps/api/.venv/bin/python"
elif [ -x "$REPOSITORY_ROOT/apps/api/.venv/Scripts/python.exe" ]; then
  PYTHON="$REPOSITORY_ROOT/apps/api/.venv/Scripts/python.exe"
else
  echo "API virtual environment was not found under apps/api/.venv" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/local_platform.py" "$@"
