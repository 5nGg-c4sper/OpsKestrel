<h1 align="center">OpsKestrel</h1>

<p align="center">
  <strong>Evidence-first operations automation for macOS and browser workflows.</strong>
</p>

<p align="center">
  OpsKestrel combines deterministic desktop actions, browser DOM adapters,
  business rules, human review, and auditable evidence. Version 2.2 adds a
  responsive React operations console for runs, evidence, workers, and reviews.
</p>

OpsKestrel executes versioned JSON tasks through deterministic desktop actions
and uses a vision model only for screenshot verification. Its first reference
product is invoice reconciliation, while the underlying platform targets
repeatable cross-system operations.

Documentation:

- [Project overview and interview walkthrough](docs/PROJECT.md)
- [Product positioning and differentiation](docs/POSITIONING.md)
- [Five-minute interview demo](docs/INTERVIEW_DEMO.md)
- [Promotional and resume notes](docs/PROMO.md)
- [Product roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [PostgreSQL queue deployment](docs/POSTGRES.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)

The local operations console can start the built-in invoice demo, upload a
CSV/XLSX/PDF input, stream run logs, download JSON/HTML/XLSX artifacts, and show
recent run history. A stuck run can be stopped from the console; this terminates
the run's process group and records the result as `cancelled` while preserving
logs and artifacts produced before cancellation. Completed runs can be packaged
as one auditable ZIP with a SHA-256 file manifest:

![OpsKestrel operations console](docs/assets/console-2.jpg)

```bash
./venv/bin/opskestrel console --port 8766
```

The Console 2.0 frontend includes:

- an operations overview with live worker and execution state
- a dedicated invoice-demo and CSV/XLSX/PDF launch flow
- run logs, reconciliation summaries, and evidence artifacts
- authenticated difference review with batch decisions and audit history

![Run monitor with logs, artifacts, and reconciliation results](docs/assets/run-monitor-2.jpg)

![Authenticated reconciliation review queue](docs/assets/reviews-2.jpg)

The built frontend is included in the Python package, so operators do not need
Node.js. To rebuild it from source:

```bash
cd web/console
pnpm install
pnpm build
```

For the interview-ready setup, use the one-command launcher. It creates a local
operator token once, stores it with owner-only permissions, and starts the
console with `admin` role by default:

```bash
./scripts/start_opskestrel.sh
```

Enter the token from `.opskestrel-console-token` in the console to unlock review
operations. The token file is ignored by Git. The launcher honors
`OPSKESTREL_CONSOLE_HOST`, `OPSKESTREL_CONSOLE_PORT`, `OPSKESTREL_REPORTS_DIR`, `OPSKESTREL_QUEUE_DB`,
`OPSKESTREL_OPERATOR_NAME`, and `OPSKESTREL_OPERATOR_ROLE`.

Check a running console from another shell:

```bash
./venv/bin/opskestrel health
./venv/bin/opskestrel release-check
```

The same archive can be created from the command line:

```bash
./venv/bin/opskestrel bundle reports/demo-20261126-120000
```

Evidence packages can contain invoice data and screenshots. Review them before
sharing outside the operator's machine.

The console also provides an authenticated human review workflow for
reconciliation differences. Each difference can be marked `pending`,
`confirmed`, or `false_positive`; reviewers can select historical runs, batch
update multiple differences, and close a fully reviewed run. Decisions are
stored in `review.json`; immutable append-only events are hash-chained in
`review-audit.jsonl`. JSON, HTML, XLSX, and an existing evidence bundle are
refreshed so the deterministic algorithm result and the operator decision remain
separately auditable. The configured console token identifies the reviewer;
client-supplied reviewer names are ignored.

Roles are enforced server-side:

- `viewer`: read review state and audit history
- `reviewer`: save individual or batch decisions
- `admin`: reviewer permissions plus closing a completed review run

The enterprise Mock ERP provides a real login page, session expiry, pagination,
controlled failures, and CSV export without external services:

![Enterprise Mock ERP login](docs/assets/erp-login.jpg)

The invoice reconciliation report combines deterministic result classification,
business filters, retry/cache state, and screenshot evidence:

![Invoice reconciliation report](docs/assets/invoice-report.jpg)

Configure the project root `.env` from [.env.example](.env.example).
Python 3.9 through 3.12 is supported.

Run one task:

```bash
./venv/bin/opskestrel run tasks/calculator_17x23.json
```

Run the parameterized calculator task:

```bash
./venv/bin/opskestrel run tasks/calculator_parameterized.json \
  --param right=23
```

`calculator_parameterized.json` defaults `left` to `17`, `operator` to `*`, and
`expected_result` to `391`. `right` has no default and must be supplied with
`--param`.

Override several string parameters by repeating `--param`:

```bash
./venv/bin/opskestrel run tasks/calculator_parameterized.json \
  --param left=3 \
  --param right=4 \
  --param expected_result=12
```

Task strings can reference declared parameters with `${parameter_name}` in
fields such as `app`, `content`, `keys`, `prompt`, and `summary`. Referencing an
undeclared or missing parameter fails before the first desktop action.
`verify_vision` steps accept `expected_vision_result` (default `true`), plus
`verification_attempts` and `verification_retry_delay_seconds` for retrying
transient screenshot or model results.

Add an explicit approval checkpoint before a high-risk action:

```json
{
  "type": "approval",
  "prompt": "是否允许提交这份客户资料？"
}
```

The approval step always asks the configured confirmation handler. Approval
continues to the next step; rejection cancels the task. `--non-interactive`
treats approval checkpoints as rejected. Reports store `approval_prompt` and
`approval_result` on the step.

Use macOS Accessibility controls instead of raw coordinates:

```json
{
  "type": "click_element",
  "app": "计算器",
  "element": {
    "role": "AXButton",
    "text": "7",
    "match_index": 0
  }
}
```

Locators support `role`, `text`, `title`, `description`, `value`, and
`match_index`. `text` matches the control title, description, or value, which
works across apps that expose the same label through different AX fields. The
matching control frame is converted into the same normalized coordinate space
used by ordinary clicks.

Read a value from a located Accessibility control:

```json
{
  "type": "read_element",
  "app": "计算器",
  "element": {"role": "AXStaticText"},
  "read_attribute": "value",
  "output": "display_value"
}
```

`read_attribute` accepts `title`, `description`, or `value`. The extracted value
and output name are recorded on the step. Set `sensitive_output` to `true` to
keep the value out of the persisted report.

Runtime outputs can be referenced by later steps in the same task:

```json
{
  "type": "write",
  "content": "计算器值：${display_value}"
}
```

Runtime placeholders are resolved immediately before each step executes.
Undefined, duplicate, or parameter-conflicting output names fail validation.
`sensitive_output` values remain usable at runtime but are not written to the
report.

Use a runtime value condition to continue or skip a step:

```json
{
  "type": "write",
  "content": "approved",
  "condition": {
    "type": "value",
    "variable": "display_value",
    "operator": "equals",
    "expected_value": "391"
  }
}
```

Value conditions support `equals`, `not_equals`, `contains`,
`not_contains`, `matches`, `not_matches`, `exists`, and `not_exists`.

Runtime outputs also flow across child tasks in one workflow:

```bash
./venv/bin/opskestrel workflow workflows/runtime_variable.json
```

The first task reads the calculator display; the second task writes that value
into TextEdit. WorkflowResult records the variable source task and whether the
value is sensitive.

Sensitive screen regions can be blacked out before any screenshot is uploaded
to the vision model or copied into report artifacts:

```json
{
  "redaction_regions": [
    {
      "x": 0.0,
      "y": 0.1,
      "width": 0.35,
      "height": 0.2
    }
  ]
}
```

Coordinates are normalized to `0-1` relative to the screenshot. Every
verification screenshot and failure screenshot in the task is redacted before
it is exposed to another component.

Run all JSON tasks in a directory:

```bash
./venv/bin/opskestrel suite tasks/
```

Pass shared parameters to every task in a suite:

```bash
./venv/bin/opskestrel suite tasks/ --param right=23
```

Every task in a parameterized suite must declare each shared parameter. A task
that does not declare a supplied parameter fails with an unknown parameter
error.

Every task still writes its own report and artifacts. After the suite finishes,
OpsKestrel also writes a summary report under `reports/` named
`<timestamp>-<suite-name>.json` and prints its path:

```text
Suite: tasks
Total: 2
Passed: 2
Failed: 0
Timed out: 0
Cancelled: 0
Duration: 8.72 seconds
Report: reports/20261124-090000-tasks.json
```

The suite report includes overall counts, status, timing, whether execution
stopped early, and every nested task result. Task `report_path` and
`failure_log` values are preserved so an inspector can trace the summary back
to the original diagnostics:

```json
{
  "suite_name": "tasks",
  "status": "passed",
  "total": 1,
  "passed": 1,
  "failed": 0,
  "timed_out": 0,
  "cancelled": 0,
  "stopped_early": false,
  "results": [
    {
      "task_name": "calculator_17x23",
      "status": "passed",
      "report_path": "reports/20261124-090000-calculator_17x23.json",
      "failure_log": null
    }
  ],
  "report_path": "reports/20261124-090000-tasks.json"
}
```

Suite names are sanitized for filenames. A repeated run with the same timestamp
uses a `-1`, `-2`, and subsequent suffix instead of overwriting an earlier
report.

Run a data-driven task dataset:

```bash
./venv/bin/opskestrel dataset datasets/calculator_cases.json
```

Each dataset case supplies its own parameters. Dataset commands therefore do
not accept `--param`. The task path inside a dataset is resolved relative to the
dataset file's directory.

Every case creates its own task report and screenshot artifacts. After all cases
finish, a summary report containing case names, parameters, statuses, durations,
and nested task reports is written under `reports/` as
`<timestamp>-<dataset-name>.json`.

Dataset cases retry only `failed` results, never `cancelled` or `timed_out`
results. Retry configuration is optional:

```json
{
  "name": "default_17x23",
  "parameters": {"right": "23"},
  "attempts": 2,
  "retry_delay_seconds": 0.5
}
```

`attempts` includes the initial execution and accepts values from 1 to 3.

Datasets can also load one case per CSV row:

```bash
./venv/bin/opskestrel dataset datasets/calculator_csv.json
```

The dataset maps CSV columns to task parameters:

```json
{
  "name": "calculator_csv_regression",
  "task": "../tasks/calculator_parameterized.json",
  "data_source": {
    "type": "csv",
    "path": "calculator_rows.csv",
    "case_name_column": "case_id",
    "parameters": {
      "left": "left",
      "operator": "operator",
      "right": "right",
      "expected_result": "expected_result"
    }
  }
}
```

The referenced CSV uses its headers as data fields:

```csv
case_id,left,operator,right,expected_result
case_17x23,17,*,23,391
case_125_div_5,125,/,5,25
```

Each row becomes an independent case and task report. When `parameters` is
omitted, every column except `case_name_column` is mapped to a task parameter
with the same name. Missing columns, empty values, repeated case names, and
malformed CSV rows stop dataset loading before any desktop action begins.
CSV source settings can also define default `attempts` and
`retry_delay_seconds` for every generated case.

Use either inline `cases` or `data_source`, not both.

Run the safe multi-record TextEdit workflow:

```bash
./venv/bin/opskestrel dataset datasets/textedit_csv.json
```

Each CSV row opens a new TextEdit document, writes a customer record, checks
the expected customer and note with the vision verifier, then closes the
document without saving. The source data is in
[datasets/textedit_rows.csv](datasets/textedit_rows.csv).

Run an ordered multi-task workflow:

```bash
./venv/bin/opskestrel workflow workflows/textedit_calculator.json \
  --param customer_name=张三 \
  --param note=首次联系
```

The example first writes and verifies a TextEdit record, then performs the
parameterized calculator task. Each task owns its own cleanup, so the TextEdit
document and calculator window are closed independently.
Each child task writes its own JSON report. After the workflow finishes, a
summary report is written under `reports/` with the ordered task statuses,
parameters, durations, nested task reports, cleanup result, and whether
execution stopped early.

Run the same workflow once for every CSV row:

```bash
./venv/bin/opskestrel dataset datasets/textedit_workflow_csv.json
```

This dataset uses the `workflow` target instead of `task`. Every CSV case runs
the complete ordered workflow with its own parameters, workflow report, nested
task reports, and final dataset summary entry.

Package a reusable business scenario with a manifest, workflow, dataset, CSV
data, and operator notes. Validate it without touching the desktop:

```bash
./venv/bin/opskestrel scenario validate \
  scenarios/customer_followup/scenario.json
```

Run the complete scenario through the normal permission and reporting pipeline:

```bash
./venv/bin/opskestrel scenario run \
  scenarios/customer_followup/scenario.json \
  --non-interactive
```

The included customer follow-up package generates three synthetic customer
records in TextEdit, verifies each record, checks an associated amount in
Calculator, closes documents without saving, and writes nested workflow and
dataset reports.

Run deterministic invoice reconciliation without a model or API key:

```bash
./venv/bin/opskestrel reconcile \
  scenarios/invoice_reconciliation/data/input_invoices.csv \
  scenarios/invoice_reconciliation/data/erp_invoices.json \
  --output reports/invoice-reconciliation.json
```

Use `--fail-on-differences` in CI when any mismatch, missing record, duplicate,
or invalid input should return exit code `1`. Amounts use decimal arithmetic and
a configurable absolute tolerance. The expected input may be CSV or XLSX.

Start the local Mock ERP browser fixture:

```bash
./venv/bin/opskestrel mock-erp --port 8765
```

Open `http://127.0.0.1:8765` and search an invoice such as `INV-1001`. The page
provides stable `data-testid` selectors and structured field attributes for the
upcoming browser adapter. It uses only the synthetic JSON fixture and does not
require credentials or external services.

Start the enterprise-like fixture with login, pagination, failure injection,
and CSV export:

```bash
./venv/bin/opskestrel mock-erp \
  --enterprise \
  --port 8765 \
  --failure-config scenarios/invoice_reconciliation/failure-example.json
```

The demo login is `demo` / `demo`. Browser commands can read production-like
credentials from `OPSKESTREL_ERP_USERNAME` and `OPSKESTREL_ERP_PASSWORD`, avoiding secrets in
the command line. Explicit `--username` and `--password` options are available
for local testing only.

Collect an invoice through the browser UI without starting the server manually:

```bash
./venv/bin/opskestrel erp-search INV-1001 \
  --screenshot reports/erp-inv-1001.png
```

The command starts the Mock ERP on an ephemeral port, opens Chrome through
Playwright, fills the invoice search, reads structured DOM fields, handles
missing and duplicate records, and closes the browser. Use `--json` for machine
output or `--headed` to watch the browser.

Run the complete CSV-to-ERP reconciliation batch:

```bash
./venv/bin/opskestrel erp-reconcile \
  scenarios/invoice_reconciliation/data/input_invoices.csv \
  --screenshot-dir reports/invoice-reconciliation/evidence \
  --checkpoint reports/invoice-reconciliation/checkpoint.json \
  --output reports/invoice-reconciliation.json \
  --html reports/invoice-reconciliation.html \
  --xlsx reports/invoice-reconciliation.xlsx
```

Each invoice is collected through the browser, then all records are passed to
the deterministic reconciliation engine. The report includes one lookup per
invoice, collection errors, screenshots, and the final reconciliation summary.
The optional HTML report adds summary cards, status filters, text search, and
clickable screenshot evidence.

`--lookup-attempts` and `--retry-delay` control per-invoice browser retries.
`--checkpoint` persists each successful lookup and automatically resumes only
missing invoices on the next run. The checkpoint is tied to the exact expected
CSV hash; use `--reset-checkpoint` to start a new collection explicitly.
`--selector-profile` loads ERP field selectors from a JSON file, so switching
target systems does not require Python changes.
`--config` applies expected-column mappings, ERP field mappings, status aliases,
currency aliases, and an optional amount tolerance. `--xlsx` writes Summary,
Results, and Collection worksheets with screenshot hyperlinks.

The packaged browser scenario can also be validated and run directly:

```bash
./venv/bin/opskestrel scenario validate \
  scenarios/invoice_reconciliation/scenario.json

./venv/bin/opskestrel scenario run \
  scenarios/invoice_reconciliation/scenario.json \
  --checkpoint reports/invoice-reconciliation/checkpoint.json \
  --html reports/invoice-reconciliation.html \
  --xlsx reports/invoice-reconciliation.xlsx
```

Manage the persistent execution queue:

```bash
./venv/bin/opskestrel queue enqueue task \
  tasks/calculator_parameterized.json \
  --param right=23 \
  --priority 5 \
  --allow-app 计算器 \
  --allow-action open_app \
  --allow-action write \
  --allow-action press \
  --allow-action verify_vision \
  --allow-action done \
  --require-label office-mac \
  --parallel-safe

./venv/bin/opskestrel queue enqueue workflow \
  workflows/textedit_calculator.json \
  --param customer_name=张三 \
  --param note=首次联系

./venv/bin/opskestrel queue list
./venv/bin/opskestrel queue workers
./venv/bin/opskestrel queue cancel <pending-job-id>
./venv/bin/opskestrel queue retry <failed-job-id>
./venv/bin/opskestrel queue run
./venv/bin/opskestrel queue run --drain
./venv/bin/opskestrel queue run --stale-after-seconds 3600 --max-attempts 3
./venv/bin/opskestrel queue run --worker-id macbook-runner-1
./venv/bin/opskestrel queue worker \
  --worker-id macbook-runner-1 \
  --label office-mac \
  --poll-interval 2
./venv/bin/opskestrel queue run --label office-mac
./venv/bin/opskestrel queue run --label office-mac --max-concurrency 2
```

The queue is stored in `reports/queue.db` by default. `queue run` processes one
job by default, `--max-jobs` limits a batch, and `--drain` processes until no
pending jobs remain. Enqueuing and listing do not require the API key; running
the worker initializes the desktop environment and vision provider. Running
jobs whose claim lease expires are automatically returned to `pending` or
failed after `--max-attempts`.

Failed and timed-out executions are also returned to `pending` until
`--max-attempts` is reached. Cancelled jobs are never retried automatically.

`queue cancel` only accepts a `pending` job, so an actively running GUI task is
not reported as cancelled while it is still controlling the desktop.
`queue retry` accepts `failed`, `timed_out`, or `cancelled` jobs, returns them
to `pending`, and resets the automatic attempt budget. Both commands support
SQLite and PostgreSQL through `--queue-db`.

`--queue-db` accepts a filesystem path, `sqlite:///` URL, or PostgreSQL DSN:

```bash
./venv/bin/opskestrel queue list \
  --queue-db postgresql://user:pass@db.example.com/opskestrel
```

PostgreSQL mode requires the `psycopg` dependency from `requirements.txt`. It
uses `FOR UPDATE SKIP LOCKED` for multi-machine claims and an exclusive lock row
to keep non-parallel-safe GUI jobs globally serialized.

Each Worker also receives a unique ID. While a job is executing, a background
heartbeat renews `claimed_at`; heartbeats and completion are rejected unless
the Worker still owns the job. `--worker-id` can provide a stable identity for
managed runners.

`queue workers` shows recently active Worker IDs, hostnames, PIDs, current
jobs, and last heartbeat times. Use `--online-within-seconds` to control the
online window.

`queue worker` runs continuously instead of exiting when the queue is empty.
It remains registered as idle, polls for new jobs, and shuts down gracefully on
`SIGINT` or `SIGTERM` after the current job completes.

Run deployment diagnostics before starting unattended work:

```bash
./venv/bin/opskestrel doctor \
  --worker-id macbook-runner-1

./venv/bin/opskestrel doctor \
  --worker-id macbook-runner-1 \
  --json
```

The doctor checks Python, macOS, model configuration, GUI session, Screen
Recording and Accessibility permissions, report directory, queue backend, and
Worker heartbeat. It does not execute desktop actions. A missing requested
Worker or failed prerequisite returns exit code `1`.

To start a Worker automatically after macOS login, render and inspect a
LaunchAgent without installing it:

```bash
./venv/bin/python scripts/worker_launchd.py render \
  --worker-id macbook-runner-1 \
  --label office-mac \
  --output /private/tmp/opskestrel-worker.plist
```

After granting the required Accessibility and Screen Recording permissions,
install it with `install` instead of `render`. A per-user LaunchAgent starts
the Worker in the graphical login session, restarts it after abnormal exits,
and writes logs under `~/Library/Logs/OpsKestrel/`. See
[docs/LAUNCHD.md](docs/LAUNCHD.md) for installation, status, restart, and
uninstall commands.

`--require-label` restricts a job to Workers advertising every required label.
`queue run --label` advertises capabilities for the current Worker. Matching is
case-insensitive; jobs with no required labels can run on any Worker.

`--max-concurrency` controls Worker slots, but GUI safety remains the default:
jobs without `parallel_safe=true` are globally serialized so two tasks cannot
compete for the mouse and keyboard. Only explicitly parallel-safe jobs may use
additional slots.

`--allow-app` and `--allow-action` create a per-job execution permission
profile. When omitted, the default SafetyPolicy remains in effect. When
present, access outside the allowlist cancels the task before the unauthorized
desktop action runs.

Stop immediately when a case does not pass:

```bash
./venv/bin/opskestrel dataset datasets/calculator_cases.json \
  --stop-on-failure
```

Failure diagnostics can be verified with the intentionally failing dataset:

```bash
./venv/bin/opskestrel dataset datasets/calculator_failure_case.json
```

This command is expected to return exit code `1`. Each non-passed task writes a
`failure.log` beside its report artifacts, and the task JSON report links to it
through `failure_log`. Dataset output also prints failed case names, attempt
counts, errors, task reports, and failure log paths.

Run the safe cross-application activation example:

```bash
./venv/bin/opskestrel run tasks/examples/multi_app_activate.json
```

Run the Accessibility-based click example:

```bash
./venv/bin/opskestrel run tasks/examples/accessibility_click.json
```

Run the Accessibility value-reading example:

```bash
./venv/bin/opskestrel run tasks/examples/read_element.json
```

Run the cross-app runtime variable example:

```bash
./venv/bin/opskestrel run tasks/examples/runtime_variable.json
```

`open_app` starts or opens an application. `activate_app` explicitly brings an
application to the foreground, including applications already opened earlier in
the same task.

Any regular step can include a vision `condition`. When the condition does not
match, the step is recorded as `skipped` and the task continues:

```bash
./venv/bin/opskestrel run tasks/examples/conditional_step_skip.json
```

Condition diagnostics include the prompt, expected and actual values, condition
duration, and an archived `condition_screenshot`. These fields are also shown
in terminal output and included in failure logs when condition evaluation fails.

Deterministic steps can repeat without duplicating JSON:

```bash
./venv/bin/opskestrel run tasks/examples/loop_write.json
```

`loop.count` is the total execution count and `loop.delay_seconds` is the delay
between iterations. Conditions are evaluated once before entering a loop.

Tasks can define `setup_steps` and `cleanup_steps` around the main `steps`:

```bash
./venv/bin/opskestrel run tasks/examples/setup_cleanup.json
```

Setup runs before the main flow. Cleanup runs after success, failure, timeout, or
early completion. A cleanup failure changes a previously passed task to failed,
but does not replace an existing main-flow failure.

For local development without the installed command, use
`./venv/bin/python -m opskestrel` with the same arguments.

The package must be installed in editable mode after changing entry points:

```bash
./venv/bin/python -m pip install -e .
```

If the environment uses legacy `setuptools` without editable-install support,
use `./venv/bin/python setup.py develop` instead.

Each task produces a JSON report under `reports/`. Suite and dataset commands
also produce their own summary reports. Verification screenshots are archived
under `reports/artifacts/<report-name>/`. Reports and screenshots are ignored by
Git because they may contain sensitive desktop content.

## Manual macOS GUI CI

The `macOS GUI Smoke` GitHub Actions workflow runs deterministic tasks on a
self-hosted Mac in a logged-in GUI session. It is manual-only and never runs on
pushes or pull requests, preventing ordinary CI jobs from taking control of a
developer desktop.

Prepare the self-hosted runner:

1. Register a repository-level macOS runner and add the custom `opskestrel-gui` label.
2. Start the runner from Terminal while the same user is logged into an
   unlocked desktop session. Do not install it as a background-only service.
3. Grant the runner host application Accessibility and Screen Recording
   permissions in macOS System Settings.
4. Create the repository secret `OPENAI_API_KEY`.
5. Optionally create the repository variable `OPENAI_BASE_URL`. It defaults to
   `https://api.siliconflow.cn/v1`.

From GitHub, open **Actions**, select **macOS GUI Smoke**, choose the task and
model, then run the workflow. Only a small allowlist of reviewed tasks is
available. Report upload is disabled by default because screenshots may contain
sensitive desktop content; enable `upload_reports` only when a seven-day private
artifact is acceptable.

The project keeps the original MIT license and remains a derivative of the
OthersideAI Self-Operating Computer project.


## Upstream Compatibility

OpsKestrel retains the `operate` command and the original OpenAI-compatible
computer-use modules for compatibility with the upstream MIT project. They are
not the primary OpsKestrel product interface.

OpsKestrel is an independent derivative and does not claim the
Self-Operating Computer name, branding, or roadmap. The original copyright and
MIT license are preserved in [LICENSE](LICENSE), and the upstream project is
available at [OthersideAI/self-operating-computer](https://github.com/OthersideAI/self-operating-computer).
