#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export HELLOSAMA_ENV_FILE="$PROJECT_DIR/.env"
VENV_PATH="${VENV_PATH:-$PROJECT_DIR/.venv}"
exec "$VENV_PATH/bin/python" manage.py portal_worker
