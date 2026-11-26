#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This demo bootstrap requires macOS.\n' >&2
  exit 1
fi

if [[ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  printf 'Google Chrome is required at /Applications/Google Chrome.app.\n' >&2
  exit 1
fi

if [[ ! -x "venv/bin/python" ]]; then
  python3 -m venv venv
fi

./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -e .

if [[ ! -f ".env" ]]; then
  cp ".env.example" ".env"
  printf 'Created .env from .env.example. Fill model credentials before GUI runs.\n'
fi

./venv/bin/python ./venv/bin/soc-agent scenario validate \
  scenarios/invoice_reconciliation/scenario.json

printf '\nDemo is ready. Run:\n'
printf '  ./scripts/demo_invoice_reconciliation.sh\n'
