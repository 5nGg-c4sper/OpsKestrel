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

The next implementation phase will add a local mock ERP and a browser adapter
that collects these same ERP fields from a web interface.
