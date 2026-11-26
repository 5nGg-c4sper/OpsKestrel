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
  python_bin="${SOC_PYTHON:-}"
  if [[ -z "$python_bin" ]]; then
    for candidate in python3.12 python3.11 python3.10 python3.9; do
      if command -v "$candidate" >/dev/null 2>&1; then
        python_bin="$candidate"
        break
      fi
    done
  fi
  if [[ -z "$python_bin" ]]; then
    printf 'Python 3.9 through 3.12 is required.\n' >&2
    exit 1
  fi
  "$python_bin" -c \
    'import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] < (3, 13) else 1)' \
    || {
      printf 'Unsupported Python: %s (need 3.9 through 3.12).\n' \
        "$("$python_bin" --version 2>&1)" >&2
      exit 1
    }
  "$python_bin" -m venv venv
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
