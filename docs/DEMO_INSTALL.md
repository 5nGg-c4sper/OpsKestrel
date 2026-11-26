# macOS Demo Installation

## Requirements

- macOS with a logged-in graphical session
- Google Chrome under `/Applications`
- Python 3.9 or newer
- Accessibility and Screen Recording permission for the process running the
  browser workflow

## Bootstrap

Run:

```bash
cd /Users/mmmz/self-operating-computer
./scripts/bootstrap_macos_demo.sh
```

The script:

1. verifies macOS and Google Chrome
2. creates `venv` when missing
3. installs the editable project and dependencies
4. copies `.env.example` only when `.env` does not already exist
5. validates the invoice scenario package
6. prints the one-command demo entry point

The script never overwrites an existing `.env`.

## Launch

```bash
./scripts/demo_invoice_reconciliation.sh
```

Artifacts are written to `reports/demo-<timestamp>/`:

- checkpoint
- evidence screenshots
- reconciliation JSON
- filterable HTML
- Excel workbook

## Console

```bash
./venv/bin/soc-agent console --port 8766
```

Open `http://127.0.0.1:8766` to view reports, online Workers, and start the
invoice demo. The console also accepts CSV, XLSX, XLSM, and text-labeled PDF
inputs up to 10 MB, shows live log output and run history, and links to the
generated JSON/HTML/XLSX and checkpoint artifacts. The **停止当前运行** button
terminates the active run's process group, including browser child processes,
and records the run as `cancelled`. Logs and artifacts completed before
cancellation remain available. After a run finishes, **生成证据包** creates
`evidence-bundle.zip` with every report, screenshot, checkpoint, and log plus a
SHA-256 manifest. Review the archive before sharing it because it can contain
invoice data and screenshots.

## Human Review

The **人工复核** section lists every non-matching invoice. Select a review
conclusion, enter the reviewer and optional note, then save:

- `pending`: not handled yet
- `confirmed`: the detected difference is real
- `false_positive`: the difference is not actionable

Decisions are written to `review.json` and synchronized to
`reconciliation.json`, `reconciliation.html`, and `reconciliation.xlsx`.
If an evidence bundle already exists, it is regenerated. After restarting the
console, the latest reconciliation run with review data is selected
automatically.
