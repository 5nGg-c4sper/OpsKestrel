# Customer Follow-up Batch

This scenario demonstrates a repeatable desktop workflow for a small customer
follow-up batch:

1. Read one customer row from CSV.
2. Open TextEdit and create a new blank document.
3. Enter the customer name and follow-up note.
4. Verify both values visually.
5. Close the document without saving.
6. Open Calculator and verify the associated amount.
7. Repeat for every CSV row and write task, workflow, and dataset reports.

Validate the package without touching the desktop:

```bash
./venv/bin/opskestrel scenario validate \
  scenarios/customer_followup/scenario.json
```

Run the complete batch:

```bash
./venv/bin/opskestrel scenario run \
  scenarios/customer_followup/scenario.json \
  --non-interactive
```

Use only synthetic or approved customer data. The CSV file, reports, and
screenshots can contain business-sensitive information and must not be
committed without review.
