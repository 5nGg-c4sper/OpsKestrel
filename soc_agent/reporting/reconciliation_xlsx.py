"""Write business-friendly invoice reconciliation workbooks."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from soc_agent.erp_reconciliation import BrowserReconciliationReport
from soc_agent.reconciliation import ReconciliationStatus
from soc_agent.reviews import ReviewStatus, build_review_summary


HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")
HEADER_FONT = Font(bold=True)


class ReconciliationXLSXWriter:
    def write(
        self,
        report: BrowserReconciliationReport,
        output_path,
        reviews=None,
        closure=None,
    ) -> Path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        summary_sheet = workbook.active
        summary_sheet.title = "Summary"
        results_sheet = workbook.create_sheet("Results")
        collection_sheet = workbook.create_sheet("Collection")
        reviews = reviews or {}

        self._write_summary(summary_sheet, report, reviews, closure)
        self._write_results(results_sheet, report, reviews)
        self._write_collection(collection_sheet, report)

        temp_path = path.with_suffix(path.suffix + ".tmp")
        workbook.save(temp_path)
        workbook.close()
        temp_path.replace(path)
        return path

    def _write_summary(self, sheet, report, reviews, closure):
        summary = report.reconciliation.summary
        review_summary = build_review_summary(
            report.reconciliation,
            reviews,
        )
        rows = [
            ("Metric", "Value"),
            ("Total invoices", summary["total"]),
            ("Matched", summary["by_status"]["matched"]),
            ("Amount mismatch", summary["by_status"]["amount_mismatch"]),
            ("Currency mismatch", summary["by_status"]["currency_mismatch"]),
            ("Status mismatch", summary["by_status"]["status_mismatch"]),
            ("Missing in ERP", summary["by_status"]["missing_in_erp"]),
            ("Duplicate in ERP", summary["by_status"]["duplicate_in_erp"]),
            ("Invalid input", summary["by_status"]["invalid_input"]),
            ("Collection errors", len(report.collection_errors)),
            ("Cached lookups", len(report.cached_lookups)),
            ("Differences pending review", review_summary["pending"]),
            ("Differences confirmed", review_summary["confirmed"]),
            ("Differences false positive", review_summary["false_positive"]),
            (
                "All differences reviewed",
                "yes" if review_summary["all_reviewed"] else "no",
            ),
            ("All matched", "yes" if summary["all_matched"] else "no"),
            (
                "Review status",
                closure["status"] if closure else "open",
            ),
            (
                "Closed by",
                _excel_safe(
                    closure.get("closed_by", "") if closure else ""
                ),
            ),
            (
                "Closed at",
                closure.get("closed_at", "") if closure else "",
            ),
            (
                "Close note",
                _excel_safe(closure.get("note", "") if closure else ""),
            ),
        ]
        for row in rows:
            sheet.append(row)
        self._format_header(sheet)
        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 18
        sheet.freeze_panes = "A2"

    def _write_results(self, sheet, report, reviews):
        sheet.append(
            [
                "Invoice ID",
                "Status",
                "Expected Amount",
                "ERP Amount",
                "Expected Currency",
                "ERP Currency",
                "Expected Status",
                "ERP Status",
                "Details",
                "Attempts",
                "Cached",
                "Screenshot",
                "Diagnostics",
                "Review Status",
                "Reviewer",
                "Review Note",
                "Reviewed At",
            ]
        )
        lookups = {
            lookup.invoice_id.casefold(): lookup
            for lookup in report.lookups
        }
        for result in report.reconciliation.results:
            expected = (
                result.expected
                if isinstance(result.expected, dict)
                else {}
            )
            actual = (
                result.actual
                if isinstance(result.actual, dict)
                else {}
            )
            lookup = lookups.get(result.invoice_id.casefold())
            review = reviews.get(result.invoice_id.casefold())
            if result.status == ReconciliationStatus.MATCHED:
                review_status = ""
            elif review is None:
                review_status = ReviewStatus.PENDING.value
            else:
                review_status = review.status.value
            detail = (
                result.error
                or "; ".join(result.differences)
                or ""
            )
            sheet.append(
                [
                    result.invoice_id,
                    result.status.value,
                    expected.get("amount"),
                    actual.get("amount"),
                    expected.get("currency"),
                    actual.get("currency"),
                    expected.get("status"),
                    actual.get("status"),
                    detail,
                    lookup.attempts if lookup else "",
                    (
                        "yes"
                        if lookup and lookup.cached
                        else "no"
                    ),
                    (
                        Path(lookup.screenshot_path).resolve().as_uri()
                        if lookup and lookup.screenshot_path
                        else ""
                    ),
                    (
                        Path(lookup.diagnostics_path).resolve().as_uri()
                        if lookup and lookup.diagnostics_path
                        else ""
                    ),
                    review_status,
                    _excel_safe(review.reviewer if review else ""),
                    _excel_safe(review.note if review else ""),
                    (
                        review.updated_at.isoformat()
                        if review is not None
                        else ""
                    ),
                ]
            )
        self._format_header(sheet)
        sheet.auto_filter.ref = sheet.dimensions
        sheet.freeze_panes = "A2"
        widths = {
            "A": 18,
            "B": 20,
            "I": 42,
            "L": 36,
            "M": 36,
            "N": 24,
            "O": 24,
            "P": 42,
            "Q": 26,
        }
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row[11:13]:
                if cell.value:
                    cell.hyperlink = cell.value
                    cell.style = "Hyperlink"

    def _write_collection(self, sheet, report):
        sheet.append(
            [
                "Invoice ID",
                "Found",
                "Record Count",
                "Duplicate",
                "Attempts",
                "Cached",
                "Retry Errors",
                "Collection Error",
                "Screenshot",
                "Diagnostics",
            ]
        )
        for lookup in report.lookups:
            sheet.append(
                [
                    lookup.invoice_id,
                    "yes" if lookup.found else "no",
                    lookup.record_count,
                    "yes" if lookup.duplicate else "no",
                    lookup.attempts,
                    "yes" if lookup.cached else "no",
                    "; ".join(lookup.retry_errors),
                    lookup.error or "",
                    (
                        Path(lookup.screenshot_path).resolve().as_uri()
                        if lookup.screenshot_path
                        else ""
                    ),
                    (
                        Path(lookup.diagnostics_path).resolve().as_uri()
                        if lookup.diagnostics_path
                        else ""
                    ),
                ]
            )
        self._format_header(sheet)
        sheet.auto_filter.ref = sheet.dimensions
        sheet.freeze_panes = "A2"
        for column in ("A", "G", "H", "I", "J"):
            sheet.column_dimensions[column].width = 28

    @staticmethod
    def _format_header(sheet):
        for cell in sheet[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT


def _excel_safe(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
