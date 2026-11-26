# OpsKestrel Promotional Notes

## One-Line Description

An auditable macOS automation platform for cross-system invoice reconciliation,
with browser-first data collection, deterministic rules, retries, checkpoints,
and Excel/HTML reports.

## GitHub Description

```text
Auditable macOS desktop/browser automation with deterministic invoice
reconciliation, enterprise Mock ERP, Playwright DOM adapters, recovery,
checkpoints, and JSON/HTML/XLSX reports.
```

## 30-Second Pitch

> OpsKestrel automates repetitive business workflows across desktop applications
> and browser ERPs. Its invoice reconciliation product reads CSV, Excel, or PDF
> inputs, checks ERP data through Playwright, and uses deterministic rules to
> classify amount, currency, status, missing, duplicate, and invalid records.
> Every lookup has evidence, transient failures retry, successful work resumes
> from checkpoints, and the final result is available as JSON, HTML, and Excel.

## Core Selling Points

- DOM-first browser automation with configurable selectors
- deterministic `Decimal` reconciliation instead of model-decided accounting
- enterprise Mock ERP with login, pagination, session expiry, and fault injection
- retry, failure isolation, diagnostics, and checkpoint resume
- credentials through environment variables
- JSON, filterable HTML, and multi-sheet XLSX reports
- local operations console for input upload, progress, logs, reports, artifacts,
  run history, Workers, and one-click demo launch
- authenticated reviewer roles, batch review, and hash-chained audit events
- SHA-256 evidence bundles and integrity-bound review closure
- queue, multi-worker, LaunchAgent, and PostgreSQL foundation

## Interview Description

> I built a reference enterprise automation platform around a real accounting
> problem rather than a generic click demo. The system uses browser DOM
> adapters, deterministic business rules, evidence capture, and hash-bound
> checkpoints. I tested it against a stateful ERP simulator that injects login,
> pagination, slow responses, 503 failures, duplicates, and missing records.
> Real ERP integration becomes an adapter/configuration task without changing
> the queue, reconciliation, recovery, or reporting layer.

## Resume Bullet Examples

- Built a macOS/browser RPA platform with Playwright DOM adapters, configurable
  selectors, deterministic invoice rules, and auditable evidence.
- Designed retry, login-recovery, checkpoint, and configuration-fingerprint
  mechanisms to make batch reconciliation resumable and repeatable.
- Delivered JSON, filterable HTML, and multi-sheet Excel reports for 500-record
  batches with screenshot and diagnostic links.
- Built an enterprise ERP simulator covering authentication, pagination,
  session expiry, slow responses, and one-time server failures.
- Added 400+ automated tests, CI acceptance, and one-command interview demos.

## Suggested Screenshots

Generate current 2.1 screenshots from the running OpsKestrel console, Mock ERP,
HTML reconciliation report, and XLSX Summary/Results sheets. The architecture
diagram is available at `docs/assets/architecture.svg`.
