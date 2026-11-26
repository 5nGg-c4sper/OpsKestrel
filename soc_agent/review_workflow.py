"""Apply persisted operator reviews to reconciliation run artifacts."""

import json
from pathlib import Path
from typing import Dict

from soc_agent.erp_reconciliation import BrowserReconciliationReport
from soc_agent.evidence_bundle import create_evidence_bundle
from soc_agent.reconciliation import ReconciliationStatus
from soc_agent.reporting.reconciliation_report import (
    ReconciliationHTMLReportWriter,
)
from soc_agent.reporting.reconciliation_xlsx import (
    ReconciliationXLSXWriter,
)
from soc_agent.reviews import (
    ReviewError,
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
    root, _, payload, report = _load_run(run_dir)
    store = ReviewStore(root / "review.json")
    records = store.records
    summary = build_review_summary(report.reconciliation, records)
    return {
        "available": True,
        "run": root.name,
        "review_summary": summary,
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
        "review_log": str(root / "review.json"),
        "report_path": str(root / "reconciliation.json"),
        "report_has_reviews": "review_summary" in payload,
    }


def save_review(
    run_dir,
    invoice_id: str,
    status,
    reviewer: str,
    note: str = "",
) -> Dict:
    root, report_path, payload, report = _load_run(run_dir)
    matched = {
        result.invoice_id.casefold()
        for result in report.reconciliation.results
        if result.status == ReconciliationStatus.MATCHED
    }
    all_ids = {
        result.invoice_id.casefold()
        for result in report.reconciliation.results
    }
    normalized_id = invoice_id.strip().casefold()
    if normalized_id not in all_ids:
        raise ReviewError(f"invoice not found in report: {invoice_id}")
    if normalized_id in matched:
        raise ReviewError("matched invoices do not require review")

    store = ReviewStore(root / "review.json")
    record = store.set(
        invoice_id=invoice_id,
        status=status,
        reviewer=reviewer,
        note=note,
    )
    records = store.records
    updated_payload = apply_reviews_to_payload(payload, records)
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
    if bundle_path.is_file():
        create_evidence_bundle(root, bundle_path)

    state = review_state(root)
    state["updated"] = record.to_dict()
    state["bundle_refreshed"] = bundle_path.is_file()
    return state


def _write_json_atomic(path: Path, payload: Dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
