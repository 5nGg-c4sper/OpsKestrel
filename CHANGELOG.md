# Changelog

## 2.2.0 - 2026-11-27

Web Console 2.0.

- Added a responsive React, TypeScript, and Vite operations console
- Rebuilt the overview around live workers, current execution, reviews, runs, and evidence
- Added dedicated new-run, run-monitor, and authenticated review workflows
- Added reusable status, surface, table, dialog, and notification components
- Bundled built frontend assets in the Python package with legacy HTML fallback
- Added static asset path validation and Console API shape coverage
- Added frontend build documentation and CI

## 2.1.1 - 2026-11-27

Documentation and release presentation.

- Added real screenshots for the console, enterprise Mock ERP, and reconciliation report
- Updated the roadmap test count to the current 471 tests
- Replaced completed milestones with the current delivery boundary

## 2.1.0 - 2026-11-26

Product identity and namespace migration.

- Renamed the product from SOC Agent to OpsKestrel
- Renamed the Python package from `soc_agent` to `opskestrel`
- Renamed the CLI command from `soc-agent` to `opskestrel`
- Renamed environment variables from `SOC_*` to `OPSKESTREL_*`
- Renamed console tokens, service labels, and temporary artifacts
- Organized the standalone project under the `OpsKestrel` workspace folder
- Positioned the product as evidence-first operations automation
- Retained MIT attribution to the upstream Self-Operating Computer project

## 2.0.0 - 2026-11-26

First interview-ready release under the former project codename.

### Added

- Deterministic macOS task, workflow, suite, and dataset execution
- Persistent queue, retry, worker heartbeat, LaunchAgent, and PostgreSQL support
- Accessible UI element targeting and cross-application runtime variables
- Enterprise Mock ERP with login, pagination, session expiry, faults, and export
- Playwright DOM-first invoice collection and deterministic reconciliation
- CSV, XLSX, and PDF expected inputs with resumable checkpoints
- JSON, filterable HTML, and multi-sheet XLSX reconciliation reports
- Local operations console, uploads, logs, cancellation, and run history
- SHA-256 evidence bundles
- Authenticated operator review with roles and hash-chained audit events
- Batch review, historical-run selection, and integrity-bound review closure
- Health checks, one-command startup, release checks, and release CI

### Security

- Console review mutations require a server-configured Bearer Token
- Client-supplied reviewer names are ignored
- Review and closure tampering is detected
- Excel formula injection is neutralized for review text
- `.env` and `.opskestrel-console-token` remain outside version control

