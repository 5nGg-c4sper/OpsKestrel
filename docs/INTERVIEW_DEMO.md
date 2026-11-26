# Five-Minute Interview Demo

## Before the Interview

Prepare a terminal at the repository root:

```bash
cd /Users/mmmz/self-operating-computer
source venv/bin/activate
./venv/bin/soc-agent doctor --worker-id macbook-runner-1
```

Keep Chrome installed and the Mac unlocked. Do not use a real ERP account or
customer data for this demonstration.

## 0:00-0:40 Problem

Say:

> Finance teams often export expected invoices to Excel, then manually search
> an ERP for each invoice. They compare amount, currency, and status, while
> handling slow pages, missing records, duplicates, and login expiry.

Show:

```text
scenarios/invoice_reconciliation/data/input_invoices.csv
```

Point out the seven result categories in the report summary.

## 0:40-2:00 Run the Demo

Run:

```bash
./scripts/demo_invoice_reconciliation.sh
```

While it runs, explain:

- enterprise Mock ERP requires login
- Chrome is controlled through Playwright
- DOM fields are preferred over screenshot interpretation
- INV-1001 fails once with a simulated 503 and retries
- INV-1002 simulates a slow response
- successful lookups are checkpointed

## 2:00-2:45 HTML Report

Open the generated `reconciliation.html`.

Show:

- matched versus differing records
- amount and status mismatch filters
- invoice search
- screenshot evidence
- cache and retry indicators

Say:

> Business decisions are deterministic. The model is not deciding whether
> amounts match, and every result can be traced to an ERP screenshot.

## 2:45-3:20 Excel Report

Open `reconciliation.xlsx`.

Show:

- Summary sheet
- Results sheet with filters
- Collection sheet
- screenshot and diagnostics hyperlinks
- retry and cache columns

## 3:20-4:00 Reliability Walkthrough

Run or show the result of:

```bash
./scripts/demo_invoice_failures.sh
```

Explain:

- query retry and backoff
- login redirect recovery
- failure screenshots and diagnostics
- per-invoice isolation
- checkpoint resume
- CSV and mapping hashes prevent stale cache reuse

## 4:00-4:35 Architecture

Open `docs/PROJECT.md`.

Explain the layers:

- scenario manifest and data mapping
- browser and desktop adapters
- deterministic reconciliation
- queue and worker operations
- reports and audit evidence

State clearly:

> The project uses a local enterprise ERP simulator. A real ERP integration
> requires a test environment and selector calibration, but the reconciliation,
> retry, checkpoint, reporting, and queue layers remain unchanged.

## 4:35-5:00 Test Evidence and Next Steps

Run:

```bash
./venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
```

Show the current test count. Mention:

- 500-invoice deterministic stress generation
- LaunchAgent crash recovery
- PostgreSQL multi-worker tests
- XLSX, PDF, CSV input
- HTML operations console

## Demonstration Boundaries

Do not claim:

- production validation against SAP, Yonyou, or Kingdee
- support for every ERP without adapter work
- that the vision model performs the accounting comparison
- autonomous operation on sensitive financial systems without approval

The strongest claim is:

> A working, tested reference platform that can be connected to a real ERP
> through credentials, URLs, and selector configuration without redesigning
> the reconciliation and reliability layers.
