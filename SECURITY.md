# Security

## Supported Version

Security fixes target the current `2.x` release line.

## Local Console

SOC Agent is designed to bind to `127.0.0.1` by default. Do not bind the
operations console to a public interface without an HTTPS reverse proxy and an
external identity layer.

Review mutations require a server-configured operator token:

```bash
export SOC_OPERATOR_NAME=interview-operator
export SOC_OPERATOR_ROLE=admin
export SOC_OPERATOR_TOKEN="$(openssl rand -hex 32)"
./venv/bin/soc-agent console
```

The `scripts/start_soc_agent.sh` launcher writes the generated token to
`.soc-console-token` with owner-only permissions. The file is ignored by Git.

## Report Data

Reports, screenshots, reconciliation records, and evidence archives can contain
invoice and customer data. Review them before sharing. Uploaded screenshots are
sent to the configured vision model when GUI visual verification is used.

## Audit Integrity

Review events are chained with SHA-256 hashes in `review-audit.jsonl`. This
detects local modification but is not a replacement for a remote append-only
audit service. A production deployment should export audit events to a trusted
external store.

## Reporting A Vulnerability

Do not include production credentials or customer records in a vulnerability
report. Provide reproduction steps using the synthetic Mock ERP fixture.
