#!/usr/bin/env bash
# Run from any location: bash /home/YOUR_USERNAME/HelloSama/deploy/update.sh
# Existing tracked changes are never discarded; migrations do not recreate the database.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
VENV_PATH="${VENV_PATH:-$PROJECT_DIR/.venv}"
if [[ -d .git ]] && git remote get-url origin >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    printf '%s\n' 'Tracked files have local changes. Commit or review them before updating; no changes were discarded.' >&2
    exit 1
  fi
  git pull --ff-only
fi
if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_PATH"
fi
"$VENV_PATH/bin/python" -m pip install --disable-pip-version-check -r requirements.lock
"$VENV_PATH/bin/python" deploy/configure.py
chmod 600 .env
export HELLOSAMA_ENV_FILE="$PROJECT_DIR/.env"
"$VENV_PATH/bin/python" manage.py check --deploy --fail-level WARNING
"$VENV_PATH/bin/python" manage.py migrate --noinput
"$VENV_PATH/bin/python" manage.py collectstatic --noinput
"$VENV_PATH/bin/python" deploy/write_wsgi.py
"$VENV_PATH/bin/python" manage.py check_readiness
touch .release
printf '\n%s\n' 'Update complete. Ensure the HelloSama always-on worker uses this virtual environment. Review readiness items before live testing.'
