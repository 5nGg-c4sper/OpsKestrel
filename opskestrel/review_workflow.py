"""Apply authenticated operator reviews to reconciliation run artifacts."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable

from opskestrel.erp_reconciliation import BrowserReconciliationReport
from opskestrel.evidence_bundle import create_evidence_bundle
from opskestrel.operators import OperatorRole
from opskestrel.reconciliation import ReconciliationStatus
from opskestrel.reporting.reconciliation_report import (
    ReconciliationHTMLReportWriter,
)
from opskestrel.reporting.reconciliation_xlsx import (
    ReconciliationXLSXWriter,
)
from opskestrel.reviews import (
    ReviewAuditLog,
    ReviewError,
    ReviewRecord,
    ReviewStore,
    apply_reviews_to_payload,
    build_review_summary,
    review_payload,
)


def _load_run(run_dir):
    root = Path(run_dir).expanduser().resolve()
    report_path = root / "reconciliation.json"
    if not report_path.is_file():
        raise ReviewError(
            f"reconciliation report is missing: {report_path}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        report = BrowserReconciliationReport.from_dict(payload)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        raise ReviewError(
            f"failed to read reconciliation report: {error}"
        ) from error
    return root, report_path, payload, report


def review_state(run_dir) -> Dict:
    root, report_path, payload, report = _load_run(run_dir)
    store, audit = _verified_review_store(root)
    records = store.records
    summary = build_review_summary(report.reconciliation, records)
    closure = _load_closure(root, payload)
    return {
        "available": True,
        "run": root.name,
        "review_summary": summary,
        "closure": closure,
        "can_close": closure is None and summary["pending"] == 0,
        "results": [
            {
                "invoice_id": result.invoice_id,
                "status": result.status.value,
                "review": review_payload(
                    records.get(result.invoice_id.casefold())
                ),
            }
            for result in report.reconciliation.results
            if result.status != ReconciliationStatus.MATCHED
        ],
        "audit_events": list(audit.events),
        "review_log": str(root / "review.json"),
        "audit_log": str(root / "review-audit.jsonl"),
        "report_path": str(report_path),
        "report_has_reviews": "review_summary" in payload,
    }


def list_review_runs(reports_dir) -> Dict:
    root = Path(reports_dir).expanduser().resolve()
    runs = []
    for report_path in root.glob("*/reconciliation.json"):
        run_dir = report_path.parent
        try:
            state = review_state(run_dir)
        except (ReviewError, OSError, ValueError) as error:
            runs.append(
                {
                    "run": run_dir.name,
                    "error": str(error),
                    "updated_at": report_path.stat().st_mtime,
                }
            )
            continue
        runs.append(
            {
                "run": run_dir.name,
                "updated_at": report_path.stat().st_mtime,
                "review_summary": state["review_summary"],
                "closed": state["closure"] is not None,
            }
        )
    runs.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"available": bool(runs), "runs": runs}


def save_review(
    run_dir,
    invoice_id: str,
    status,
    reviewer: str,
    note: str = "",
    reviewer_role=OperatorRole.REVIEWER,
) -> Dict:
    root, report_path, payload, report = _load_run(run_dir)
    _ensure_open(root, payload)
    _validate_review_targets(report, [invoice_id])

    store, audit = _verified_review_store(root)
    previous = store.get(invoice_id)
    record = ReviewRecord(
        invoice_id=invoice_id,
        status=status,
        reviewer=reviewer,
        note=note,
        reviewer_role=reviewer_role,
    )
    audit.append(
        invoice_id,
        previous.status if previous else None,
        record,
    )
    store.put(record)
    bundle_refreshed = _sync_review_artifacts(
        root,
        report_path,
        payload,
        report,
        store.records,
    )
    state = review_state(root)
    state["updated"] = record.to_dict()
    state["bundle_refreshed"] = bundle_refreshed
    return state


def save_review_batch(
    run_dir,
    invoice_ids: Iterable[str],
    status,
    reviewer: str,
    note: str = "",
    reviewer_role=OperatorRole.REVIEWER,
) -> Dict:
    root, report_path, payload, report = _load_run(run_dir)
    _ensure_open(root, payload)
    normalized_ids = []
    seen = set()
    for invoice_id in invoice_ids:
        normalized = str(invoice_id).strip()
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            normalized_ids.append(normalized)
    if not normalized_ids:
        raise ReviewError("select at least one invoice")
    _validate_review_targets(report, normalized_ids)

    store, audit = _verified_review_store(root)
    records = dict(store.records)
    updated = []
    timestamp = datetime.now(timezone.utc)
    for invoice_id in normalized_ids:
        previous = records.get(invoice_id.casefold())
        record = ReviewRecord(
            invoice_id=invoice_id,
            status=status,
            reviewer=reviewer,
            note=note,
            reviewer_role=reviewer_role,
            updated_at=timestamp,
        )
        audit.append(
            invoice_id,
            previous.status if previous else None,
            record,
        )
        records[invoice_id.casefold()] = record
        updated.append(record)
    store._replace_records(records)
    bundle_refreshed = _sync_review_artifacts(
        root,
        report_path,
        payload,
        report,
        records,
    )
    state = review_state(root)
    state["updated"] = [record.to_dict() for record in updated]
    state["bundle_refreshed"] = bundle_refreshed
    return state


def close_review(
    run_dir,
    reviewer: str,
    note: str = "",
    reviewer_role=OperatorRole.ADMIN,
) -> Dict:
    root, report_path, payload, report = _load_run(run_dir)
    _ensure_open(root, payload)
    state = review_state(root)
    if state["review_summary"]["pending"]:
        raise ReviewError(
            "all reconciliation differences must be reviewed before closing"
        )
    closure = {
        "schema_version": 1,
        "status": "closed",
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "closed_by": reviewer,
        "closed_by_role": OperatorRole(reviewer_role).value,
        "note": str(note).strip(),
        "review_summary": state["review_summary"],
        "report_content_sha256": _report_content_hash(payload),
    }
    updated_payload = dict(payload)
    updated_payload["review_closure"] = closure
    _write_json_atomic(report_path, updated_payload)
    _write_json_atomic(_closure_path(root), closure)

    records = ReviewStore(root / "review.json").records
    html_path = root / "reconciliation.html"
    if html_path.is_file():
        ReconciliationHTMLReportWriter().write(
            report,
            html_path,
            reviews=records,
            closure=closure,
        )
    xlsx_path = root / "reconciliation.xlsx"
    if xlsx_path.is_file():
        ReconciliationXLSXWriter().write(
            report,
            xlsx_path,
            reviews=records,
            closure=closure,
        )
    bundle_path = root / "evidence-bundle.zip"
    bundle_refreshed = bundle_path.is_file()
    if bundle_refreshed:
        create_evidence_bundle(root, bundle_path)
    result = review_state(root)
    result["bundle_refreshed"] = bundle_refreshed
    return result


def _validate_review_targets(report, invoice_ids):
    matched = {
        result.invoice_id.casefold()
        for result in report.reconciliation.results
        if result.status == ReconciliationStatus.MATCHED
    }
    all_ids = {
        result.invoice_id.casefold()
        for result in report.reconciliation.results
    }
    for invoice_id in invoice_ids:
        normalized = invoice_id.strip().casefold()
        if normalized not in all_ids:
            raise ReviewError(f"invoice not found in report: {invoice_id}")
        if normalized in matched:
            raise ReviewError("matched invoices do not require review")


def _verified_review_store(root):
    store = ReviewStore(root / "review.json")
    audit = ReviewAuditLog(root / "review-audit.jsonl")
    records = store.records
    if records and not audit.events:
        for record in sorted(
            records.values(),
            key=lambda item: item.updated_at,
        ):
            audit.append(record.invoice_id, None, record)
    latest = {
        event["invoice_id"].casefold(): event
        for event in audit.events
    }
    if set(latest) != set(records):
        raise ReviewError(
            "review store does not match the audit log"
        )
    for key, record in records.items():
        event = latest[key]
        if (
            event["new_status"] != record.status.value
            or event["reviewer"] != record.reviewer
            or event["reviewer_role"] != record.reviewer_role
            or event["note"] != record.note
            or event["timestamp"] != record.updated_at.isoformat()
        ):
            raise ReviewError(
                f"review store audit mismatch for {record.invoice_id}"
            )
    return store, audit


def _sync_review_artifacts(
    root,
    report_path,
    payload,
    report,
    records,
):
    updated_payload = apply_reviews_to_payload(payload, records)
    updated_payload.pop("review_closure", None)
    _write_json_atomic(report_path, updated_payload)

    html_path = root / "reconciliation.html"
    if html_path.is_file():
        ReconciliationHTMLReportWriter().write(
            report,
            html_path,
            reviews=records,
        )
    xlsx_path = root / "reconciliation.xlsx"
    if xlsx_path.is_file():
        ReconciliationXLSXWriter().write(
            report,
            xlsx_path,
            reviews=records,
        )
    bundle_path = root / "evidence-bundle.zip"
    refreshed = bundle_path.is_file()
    if refreshed:
        create_evidence_bundle(root, bundle_path)
    return refreshed


def _closure_path(root):
    return root / "review-close.json"


def _ensure_open(root, payload):
    closure = _load_closure(root, payload)
    if closure is not None:
        raise ReviewError("review run is closed")


def _load_closure(root, payload):
    closure = payload.get("review_closure")
    path = _closure_path(root)
    if closure is None and path.is_file():
        try:
            closure = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReviewError(
                f"failed to read review closure: {error}"
            ) from error
    if closure is None:
        return None
    if closure.get("schema_version") != 1:
        raise ReviewError("unsupported review closure version")
    expected = closure.get("report_content_sha256")
    if expected != _report_content_hash(payload):
        raise ReviewError(
            "closed reconciliation report failed integrity verification"
        )
    return dict(closure)


def _report_content_hash(payload):
    content = {
        "expected_csv": payload.get("expected_csv"),
        "checkpoint_path": payload.get("checkpoint_path"),
        "reconciliation": {
            "summary": payload["reconciliation"].get("summary"),
            "results": [
                {
                    key: value
                    for key, value in result.items()
                    if key != "review"
                }
                for result in payload["reconciliation"].get("results", [])
            ],
        },
        "lookups": payload.get("lookups", []),
    }
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: Dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
