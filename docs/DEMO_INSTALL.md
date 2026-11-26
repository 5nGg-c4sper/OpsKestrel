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
generated JSON/HTML/XLSX and checkpoint artifacts.
