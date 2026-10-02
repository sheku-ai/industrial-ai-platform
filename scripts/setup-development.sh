#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/apps/api/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
REQUIREMENTS="$ROOT_DIR/apps/api/requirements-dev.txt"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

printf 'SHEKU development environment setup\n'
printf 'Repository: %s\n' "$ROOT_DIR"
printf 'Platform: %s\n' "$(uname -s)"
printf 'Python required: 3.12\n'

[[ -f "$REQUIREMENTS" ]] || fail "Backend development requirements were not found: $REQUIREMENTS"

HOST_PYTHON=""
DETECTED_PYTHON="not found"
for candidate in python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)" ||
      version="unavailable"
    if [[ "$DETECTED_PYTHON" == "not found" ]]; then
      DETECTED_PYTHON="$candidate ($version)"
    fi
    if [[ "$version" == 3.12.* ]]; then
      HOST_PYTHON="$candidate"
      DETECTED_PYTHON="$candidate ($version)"
      break
    fi
  fi
done

if [[ -z "$HOST_PYTHON" ]]; then
  printf 'ERROR: SHEKU development requires Python 3.12.\n' >&2
  printf 'Detected: %s\n' "$DETECTED_PYTHON" >&2
  printf 'Install or configure Python 3.12 on the host. The Product Installer does not require host Python.\n' >&2
  printf 'No development environment changes were made.\n' >&2
  exit 1
fi
printf 'Python detected: %s\n' "$DETECTED_PYTHON"

if [[ -e "$VENV_DIR" || -L "$VENV_DIR" ]]; then
  [[ -f "$VENV_DIR/pyvenv.cfg" && -x "$VENV_PYTHON" ]] ||
    fail "Existing apps/api/.venv is incomplete. Remove or recreate it deliberately; it was not changed."
  if ! "$VENV_PYTHON" -c '
import os
import sys
expected = sys.argv[1]
assert sys.version_info[:2] == (3, 12)
assert sys.prefix != sys.base_prefix
assert os.path.samefile(sys.prefix, expected)
' "$VENV_DIR" >/dev/null 2>&1; then
    fail "Existing apps/api/.venv is not a valid Python 3.12 environment. "\
"Remove or recreate it deliberately; it was not changed."
  fi
  printf 'Virtual environment: apps/api/.venv (reused)\n'
else
  if ! "$HOST_PYTHON" -m venv "$VENV_DIR"; then
    fail "Python 3.12 could not create apps/api/.venv. Check venv and ensurepip, "\
"then inspect the incomplete environment before retrying."
  fi
  printf 'Virtual environment: apps/api/.venv (created)\n'
fi

[[ -x "$VENV_PYTHON" ]] || fail "apps/api/.venv/bin/python is missing or not executable."
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  fail "pip is unavailable inside apps/api/.venv. Check Python 3.12 venv/ensurepip. "\
"No global pip installation was attempted."
fi

"$VENV_PYTHON" -m pip install -r "$REQUIREMENTS"
printf 'Backend dependencies: synchronized from apps/api/requirements-dev.txt\n'
printf 'Development environment: READY\n'
