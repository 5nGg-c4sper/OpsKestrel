# Invoice Reconciliation

This scenario compares an expected invoice ledger with records exported from an
ERP or order system.

The deterministic reconciliation core is complete and does not require an API
key, browser, or vision model:

```bash
./venv/bin/soc-agent reconcile \
  scenarios/invoice_reconciliation/data/input_invoices.csv \
  scenarios/invoice_reconciliation/data/erp_invoices.json
```

Write a machine-readable report and fail CI when differences exist:

```bash
./venv/bin/soc-agent reconcile \
  scenarios/invoice_reconciliation/data/input_invoices.csv \
  scenarios/invoice_reconciliation/data/erp_invoices.json \
  --output reports/invoice-reconciliation.json \
  --fail-on-differences
```

The fixture contains 20 synthetic invoices covering:

- 10 matched invoices
- 2 amount mismatches
- 1 currency mismatch
- 1 status mismatch
- 2 records missing from ERP
- 1 duplicate ERP record
- 3 invalid input records

Amount comparisons use `Decimal` and support an absolute tolerance. Results are
always sorted deterministically by invoice ID.

Start the local Mock ERP:

```bash
./venv/bin/soc-agent mock-erp --port 8765
```

Open `http://127.0.0.1:8765`. The page searches the synthetic ERP JSON and exposes
stable browser selectors for invoice ID, record count, and the `invoice_id`,
`customer_id`, `currency`, `amount`, `status`, and `due_date` fields.

The browser adapter collects these fields from the page and feeds the
deterministic reconciliation core:

```bash
./venv/bin/soc-agent erp-search INV-1017 \
  --screenshot reports/erp-inv-1017.png
```

This starts the fixture automatically, opens system Chrome through Playwright,
searches by invoice ID, and reads all records through stable DOM selectors.
`INV-1017` returns two records and is reported as a duplicate.
