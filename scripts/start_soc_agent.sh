#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -x "venv/bin/soc-agent" ]]; then
  ./scripts/bootstrap_macos_demo.sh
fi

token_file="$project_root/.soc-console-token"
if [[ ! -f "$token_file" ]]; then
  umask 077
  openssl rand -hex 32 > "$token_file"
fi

export SOC_OPERATOR_TOKEN="$(tr -d '\n' < "$token_file")"
export SOC_OPERATOR_NAME="${SOC_OPERATOR_NAME:-interview-operator}"
export SOC_OPERATOR_ROLE="${SOC_OPERATOR_ROLE:-admin}"
export SOC_CONSOLE_HOST="${SOC_CONSOLE_HOST:-127.0.0.1}"
export SOC_CONSOLE_PORT="${SOC_CONSOLE_PORT:-8766}"
export SOC_REPORTS_DIR="${SOC_REPORTS_DIR:-reports}"
export SOC_QUEUE_DB="${SOC_QUEUE_DB:-$SOC_REPORTS_DIR/queue.db}"

printf 'SOC Agent Console: http://%s:%s\n' \
  "$SOC_CONSOLE_HOST" "$SOC_CONSOLE_PORT"
printf 'Operator: %s (%s)\n' \
  "$SOC_OPERATOR_NAME" "$SOC_OPERATOR_ROLE"
printf 'Access token file: %s\n' "$token_file"

exec ./venv/bin/soc-agent console
