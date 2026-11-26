#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

./venv/bin/python -W error::ResourceWarning \
  -m unittest discover -s tests/unit -p 'test_*.py'
./venv/bin/python -m opskestrel release-check
./venv/bin/python -m opskestrel scenario validate \
  scenarios/invoice_reconciliation/scenario.json

if [[ "${OPSKESTREL_ACCEPTANCE_BROWSER:-0}" == "1" ]]; then
  ./scripts/demo_invoice_reconciliation.sh
fi

printf '\nRelease acceptance: PASSED\n'
