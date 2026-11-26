# Changelog

## 2.0.0 - 2026-11-26

First interview-ready SOC Agent release.

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
- `.env` and `.soc-console-token` remain outside version control

