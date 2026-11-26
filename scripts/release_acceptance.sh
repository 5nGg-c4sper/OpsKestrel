#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

./venv/bin/python -W error::ResourceWarning \
  -m unittest discover -s tests/unit -p 'test_*.py'
./venv/bin/python -m soc_agent release-check
./venv/bin/python -m soc_agent scenario validate \
  scenarios/invoice_reconciliation/scenario.json

if [[ "${SOC_ACCEPTANCE_BROWSER:-0}" == "1" ]]; then
  ./scripts/demo_invoice_reconciliation.sh
fi

printf '\nRelease acceptance: PASSED\n'
