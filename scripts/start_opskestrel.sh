#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -x "venv/bin/opskestrel" ]]; then
  ./scripts/bootstrap_macos_demo.sh
fi

token_file="$project_root/.opskestrel-console-token"
if [[ ! -f "$token_file" ]]; then
  umask 077
  openssl rand -hex 32 > "$token_file"
fi

export OPSKESTREL_OPERATOR_TOKEN="$(tr -d '\n' < "$token_file")"
export OPSKESTREL_OPERATOR_NAME="${OPSKESTREL_OPERATOR_NAME:-interview-operator}"
export OPSKESTREL_OPERATOR_ROLE="${OPSKESTREL_OPERATOR_ROLE:-admin}"
export OPSKESTREL_CONSOLE_HOST="${OPSKESTREL_CONSOLE_HOST:-127.0.0.1}"
export OPSKESTREL_CONSOLE_PORT="${OPSKESTREL_CONSOLE_PORT:-8766}"
export OPSKESTREL_REPORTS_DIR="${OPSKESTREL_REPORTS_DIR:-reports}"
export OPSKESTREL_QUEUE_DB="${OPSKESTREL_QUEUE_DB:-$OPSKESTREL_REPORTS_DIR/queue.db}"

printf 'OpsKestrel Console: http://%s:%s\n' \
  "$OPSKESTREL_CONSOLE_HOST" "$OPSKESTREL_CONSOLE_PORT"
printf 'Operator: %s (%s)\n' \
  "$OPSKESTREL_OPERATOR_NAME" "$OPSKESTREL_OPERATOR_ROLE"
printf 'Access token file: %s\n' "$token_file"

exec ./venv/bin/opskestrel console
