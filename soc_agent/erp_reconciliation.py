"""Batch CSV-to-ERP browser reconciliation orchestration."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from soc_agent.browser import ERPSearchResult
from soc_agent.reconciliation import (
    ReconciliationReport,
    load_expected_invoices_csv,
    reconcile_invoices,
)


@dataclass(frozen=True)
class ERPLookupEvidence:
    invoice_id: str
    found: bool
    record_count: int
    duplicate: bool
    screenshot_path: Optional[str]
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "invoice_id": self.invoice_id,
            "found": self.found,
            "record_count": self.record_count,
            "duplicate": self.duplicate,
            "screenshot_path": self.screenshot_path,
            "error": self.error,
        }


@dataclass(frozen=True)
class BrowserReconciliationReport:
    expected_csv: str
    reconciliation: ReconciliationReport
    lookups: Tuple[ERPLookupEvidence, ...]

    @property
    def collection_errors(self) -> Tuple[ERPLookupEvidence, ...]:
        return tuple(
            lookup for lookup in self.lookups if lookup.error is not None
        )

    def to_dict(self) -> Dict:
        return {
            "expected_csv": self.expected_csv,
            "collection": {
                "lookups": len(self.lookups),
                "errors": len(self.collection_errors),
            },
            "reconciliation": self.reconciliation.to_dict(),
            "lookups": [
                lookup.to_dict() for lookup in self.lookups
            ],
        }


def reconcile_expected_csv_with_browser(
    expected_csv: Union[str, Path],
    adapter,
    screenshot_dir: Optional[Union[str, Path]] = None,
    amount_tolerance: Union[str, Decimal] = "0.01",
) -> BrowserReconciliationReport:
    source_path = Path(expected_csv).expanduser().resolve()
    expected_rows = load_expected_invoices_csv(source_path)
    screenshot_root = (
        Path(screenshot_dir).expanduser().resolve()
        if screenshot_dir is not None
        else None
    )
    if screenshot_root is not None:
        screenshot_root.mkdir(parents=True, exist_ok=True)

    invoice_ids = []
    for row in expected_rows:
        invoice_id = str(row.get("invoice_id", "")).strip()
        if invoice_id and invoice_id.casefold() not in {
            item.casefold() for item in invoice_ids
        }:
            invoice_ids.append(invoice_id)

    erp_rows = []
    evidence = []
    for invoice_id in invoice_ids:
        screenshot_path = None
        if screenshot_root is not None:
            screenshot_path = str(
                screenshot_root
                / f"{_safe_filename(invoice_id)}.png"
            )
        try:
            result = adapter.search(
                invoice_id,
                screenshot_path=screenshot_path,
            )
        except Exception as error:
            evidence.append(
                ERPLookupEvidence(
                    invoice_id=invoice_id,
                    found=False,
                    record_count=0,
                    duplicate=False,
                    screenshot_path=None,
                    error=str(error),
                )
            )
            continue

        erp_rows.extend(result.records)
        evidence.append(_evidence_from_result(result))

    reconciliation = reconcile_invoices(
        expected_rows,
        erp_rows,
        amount_tolerance=amount_tolerance,
    )
    return BrowserReconciliationReport(
        expected_csv=str(source_path),
        reconciliation=reconciliation,
        lookups=tuple(evidence),
    )


def _evidence_from_result(
    result: ERPSearchResult,
) -> ERPLookupEvidence:
    return ERPLookupEvidence(
        invoice_id=result.invoice_id,
        found=result.found,
        record_count=result.record_count,
        duplicate=result.duplicate,
        screenshot_path=result.screenshot_path,
    )


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return normalized.lower() or "invoice"
