# Contributing To OpsKestrel

## Development Setup

```bash
cd /Users/mmmz/Documents/Codex/OpsKestrel
./scripts/bootstrap_macos_demo.sh
```

Use Python 3.9 through 3.12. Create a feature branch, keep changes scoped, and
include tests for behavior changes.

## Verification

```bash
./venv/bin/python -W error::ResourceWarning \
  -m unittest discover -s tests/unit -p 'test_*.py'
./venv/bin/opskestrel release-check
./venv/bin/opskestrel scenario validate \
  scenarios/invoice_reconciliation/scenario.json
```

For the full acceptance script:

```bash
./scripts/release_acceptance.sh
```

Real desktop or browser changes should also run the relevant deterministic
task, workflow, dataset, or invoice scenario on macOS.

## Design Rules

- Keep business decisions deterministic.
- Prefer browser DOM and macOS Accessibility over screenshot coordinates.
- Preserve evidence for every automated lookup and failure.
- Do not let client input override authenticated operator identity.
- Treat existing reports, audit chains, and closure fingerprints as durable
  interfaces.
- Preserve MIT attribution to the upstream Self-Operating Computer project.
- Do not introduce upstream SOC branding into the OpsKestrel product surface.

## Pull Requests

Describe the business behavior changed, the failure modes tested, and any
compatibility impact. Do not include `.env`, operator tokens, customer data, or
local report artifacts.
