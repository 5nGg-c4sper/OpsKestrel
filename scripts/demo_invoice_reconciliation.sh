#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

timestamp="$(date '+%Y%m%d-%H%M%S')"
output_dir="reports/demo-$timestamp"
mkdir -p "$output_dir"

./venv/bin/python ./venv/bin/opskestrel scenario run \
  scenarios/invoice_reconciliation/scenario.json \
  --non-interactive \
  --reset-checkpoint \
  --failure-config \
  scenarios/invoice_reconciliation/failure-example.json \
  --checkpoint "$output_dir/checkpoint.json" \
  --screenshot-dir "$output_dir/evidence" \
  --output "$output_dir/reconciliation.json" \
  --html "$output_dir/reconciliation.html" \
  --xlsx "$output_dir/reconciliation.xlsx"

printf '\nDemo artifacts: %s\n' "$output_dir"

if [[ "$(uname -s)" == "Darwin" ]]; then
  open "$output_dir/reconciliation.html"
fi
