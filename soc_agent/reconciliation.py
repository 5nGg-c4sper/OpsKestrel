"""Deterministic order and invoice reconciliation."""

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from soc_agent.reconciliation_config import ReconciliationConfig


class ReconciliationStatus(str, Enum):
    MATCHED = "matched"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    STATUS_MISMATCH = "status_mismatch"
    MISSING_IN_ERP = "missing_in_erp"
    DUPLICATE_IN_ERP = "duplicate_in_erp"
    INVALID_INPUT = "invalid_input"


class ReconciliationInputError(ValueError):
    """Raised when raw invoice data cannot be normalized."""


@dataclass(frozen=True)
class ReconciliationResult:
    invoice_id: str
    status: ReconciliationStatus
    expected: Optional[Dict[str, Any]]
    actual: Optional[Dict[str, Any]]
    differences: Tuple[str, ...] = ()
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "status": self.status.value,
            "expected": _json_value(self.expected),
            "actual": _json_value(self.actual),
            "differences": list(self.differences),
            "error": self.error,
        }


@dataclass(frozen=True)
class ReconciliationReport:
    results: Tuple[ReconciliationResult, ...]

    @property
    def summary(self) -> Dict[str, Any]:
        by_status = {
            status.value: 0
            for status in ReconciliationStatus
        }
        for result in self.results:
            by_status[result.status.value] += 1
        return {
            "total": len(self.results),
            "by_status": by_status,
            "all_matched": (
                bool(self.results)
                and all(
                    result.status == ReconciliationStatus.MATCHED
                    for result in self.results
                )
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "results": [result.to_dict() for result in self.results],
        }


def load_expected_invoices_csv(path: Union[str, Path]) -> List[Dict[str, str]]:
    source_path = Path(path).expanduser().resolve()
    with source_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        return list(csv.DictReader(csv_file))


def load_expected_invoices_xlsx(
    path: Union[str, Path],
) -> List[Dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise ReconciliationInputError(
            "openpyxl is required to read XLSX invoice files"
        ) from error

    source_path = Path(path).expanduser().resolve()
    workbook = load_workbook(
        source_path,
        read_only=True,
        data_only=True,
    )
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None:
            raise ReconciliationInputError(
                f"XLSX invoice file is empty: {source_path}"
            )
        headers = [
            str(value).strip() if value is not None else ""
            for value in header_row
        ]
        if any(not header for header in headers):
            raise ReconciliationInputError(
                "XLSX invoice headers must not be empty"
            )
        records = []
        for row in rows:
            if row is None or all(value is None for value in row):
                continue
            record = {}
            for header, value in zip(headers, row):
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                record[header] = "" if value is None else str(value)
            records.append(record)
        return records
    finally:
        workbook.close()


def load_expected_invoices(
    path: Union[str, Path],
) -> List[Dict[str, Any]]:
    source_path = Path(path).expanduser().resolve()
    suffix = source_path.suffix.casefold()
    if suffix in {".xlsx", ".xlsm"}:
        return load_expected_invoices_xlsx(source_path)
    if suffix == ".csv":
        return load_expected_invoices_csv(source_path)
    raise ReconciliationInputError(
        f"unsupported expected invoice format: {suffix or '<none>'}"
    )


def load_erp_invoices_json(path: Union[str, Path]) -> List[Dict[str, Any]]:
    source_path = Path(path).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("invoices")
    if not isinstance(payload, list):
        raise ReconciliationInputError(
            "ERP JSON must be a list or contain an invoices list"
        )
    return [dict(row) for row in payload]


def reconcile_files(
    expected_csv: Union[str, Path],
    erp_json: Union[str, Path],
    amount_tolerance: Optional[Union[str, Decimal]] = None,
    config: Optional[ReconciliationConfig] = None,
) -> ReconciliationReport:
    expected_rows = load_expected_invoices(expected_csv)
    erp_rows = load_erp_invoices_json(erp_json)
    if config is not None:
        expected_rows = config.map_expected_rows(expected_rows)
        erp_rows = config.map_erp_rows(erp_rows)
    tolerance = (
        amount_tolerance
        if amount_tolerance is not None
        else (
            config.amount_tolerance
            if config is not None
            else Decimal("0.01")
        )
    )
    return reconcile_invoices(
        expected_rows,
        erp_rows,
        amount_tolerance=tolerance,
    )


def reconcile_invoices(
    expected_rows: Iterable[Mapping[str, Any]],
    erp_rows: Iterable[Mapping[str, Any]],
    amount_tolerance: Union[str, Decimal] = "0.01",
) -> ReconciliationReport:
    tolerance = _parse_tolerance(amount_tolerance)
    results: List[ReconciliationResult] = []
    valid_expected = []
    expected_ids = {}

    for row_number, row in enumerate(expected_rows, start=1):
        raw = dict(row)
        try:
            normalized = _normalize_expected(raw)
        except ReconciliationInputError as error:
            invoice_id = _row_identifier(
                raw.get("invoice_id"),
                "expected",
                row_number,
            )
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.INVALID_INPUT,
                    expected=raw,
                    actual=None,
                    error=str(error),
                )
            )
            continue
        valid_expected.append(normalized)
        expected_ids.setdefault(normalized["invoice_id"], []).append(
            normalized
        )

    duplicate_expected_ids = {
        invoice_id
        for invoice_id, rows in expected_ids.items()
        if len(rows) > 1
    }
    for invoice_id in duplicate_expected_ids:
        for row in expected_ids[invoice_id]:
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.INVALID_INPUT,
                    expected=_public_invoice(row),
                    actual=None,
                    error="duplicate expected invoice_id",
                )
            )

    valid_erp = {}
    invalid_erp = {}
    for row_number, row in enumerate(erp_rows, start=1):
        raw = dict(row)
        try:
            normalized = _normalize_erp(raw)
        except ReconciliationInputError as error:
            invoice_id = _row_identifier(
                raw.get("invoice_id"),
                "erp",
                row_number,
            )
            invalid_erp.setdefault(invoice_id, []).append(
                {"row": raw, "error": str(error)}
            )
            continue
        valid_erp.setdefault(normalized["invoice_id"], []).append(
            normalized
        )

    invalid_erp_ids = set(invalid_erp)
    for expected in valid_expected:
        invoice_id = expected["invoice_id"]
        if invoice_id in duplicate_expected_ids:
            continue
        if invoice_id in invalid_erp_ids:
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.INVALID_INPUT,
                    expected=_public_invoice(expected),
                    actual=invalid_erp[invoice_id][0]["row"],
                    error="ERP invoice data is invalid",
                )
            )
            continue

        candidates = valid_erp.get(invoice_id, [])
        if not candidates:
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.MISSING_IN_ERP,
                    expected=_public_invoice(expected),
                    actual=None,
                    error="invoice not found in ERP",
                )
            )
            continue
        if len(candidates) > 1:
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.DUPLICATE_IN_ERP,
                    expected=_public_invoice(expected),
                    actual=[
                        _public_invoice(candidate)
                        for candidate in candidates
                    ],
                    error=(
                        "duplicate invoice found in ERP: "
                        f"{len(candidates)} records"
                    ),
                )
            )
            continue

        actual = candidates[0]
        differences = []
        if expected["currency"] != actual["currency"]:
            differences.append(
                f"currency: {expected['currency']} != {actual['currency']}"
            )
        amount_delta = expected["amount"] - actual["amount"]
        if abs(amount_delta) > tolerance:
            differences.append(
                f"amount: {expected['amount']} != {actual['amount']}"
            )
        if expected["status"].casefold() != actual["status"].casefold():
            differences.append(
                f"status: {expected['status']} != {actual['status']}"
            )

        result_status = _result_status(differences)
        results.append(
            ReconciliationResult(
                invoice_id,
                result_status,
                expected=_public_invoice(expected),
                actual=_public_invoice(actual),
                differences=tuple(differences),
            )
        )

    for invoice_id in sorted(invalid_erp):
        if invoice_id in expected_ids:
            continue
        for invalid in invalid_erp[invoice_id]:
            results.append(
                ReconciliationResult(
                    invoice_id,
                    ReconciliationStatus.INVALID_INPUT,
                    expected=None,
                    actual=invalid["row"],
                    error=invalid["error"],
                )
            )

    ordered = tuple(
        sorted(
            results,
            key=lambda result: (
                result.invoice_id.casefold(),
                result.status.value,
                result.error or "",
            ),
        )
    )
    return ReconciliationReport(ordered)


def _normalize_expected(row: Mapping[str, Any]) -> Dict[str, Any]:
    invoice_id = _required_text(row, "invoice_id")
    return {
        "invoice_id": invoice_id,
        "customer_id": _required_text(row, "customer_id"),
        "currency": _required_text(row, "currency").upper(),
        "amount": _required_decimal(row, "expected_amount"),
        "status": _required_text(row, "expected_status"),
        "due_date": _required_date(row, "due_date"),
    }


def _normalize_erp(row: Mapping[str, Any]) -> Dict[str, Any]:
    invoice_id = _required_text(row, "invoice_id")
    return {
        "invoice_id": invoice_id,
        "customer_id": _required_text(row, "customer_id"),
        "currency": _required_text(row, "currency").upper(),
        "amount": _required_decimal(row, "amount"),
        "status": _required_text(row, "status"),
        "due_date": _required_date(row, "due_date"),
    }


def _required_text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None or not str(value).strip():
        raise ReconciliationInputError(f"missing required field: {name}")
    return str(value).strip()


def _required_decimal(row: Mapping[str, Any], name: str) -> Decimal:
    value = _required_text(row, name)
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ReconciliationInputError(
            f"invalid decimal field {name}: {value}"
        ) from error
    if not amount.is_finite():
        raise ReconciliationInputError(
            f"invalid decimal field {name}: {value}"
        )
    return amount


def _required_date(row: Mapping[str, Any], name: str) -> date:
    value = _required_text(row, name)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ReconciliationInputError(
            f"invalid ISO date field {name}: {value}"
        ) from error


def _parse_tolerance(
    value: Union[str, Decimal],
) -> Decimal:
    try:
        tolerance = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("amount_tolerance must be a decimal") from error
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError(
            "amount_tolerance must be a non-negative decimal"
        )
    return tolerance


def _row_identifier(value, source: str, row_number: int) -> str:
    if value is not None and str(value).strip():
        return str(value).strip()
    return f"<{source}-row-{row_number}>"


def _result_status(differences: List[str]) -> ReconciliationStatus:
    if any(item.startswith("currency:") for item in differences):
        return ReconciliationStatus.CURRENCY_MISMATCH
    if any(item.startswith("amount:") for item in differences):
        return ReconciliationStatus.AMOUNT_MISMATCH
    if any(item.startswith("status:") for item in differences):
        return ReconciliationStatus.STATUS_MISMATCH
    return ReconciliationStatus.MATCHED


def _public_invoice(invoice: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: (
            str(value)
            if isinstance(value, (Decimal, date))
            else value
        )
        for key, value in invoice.items()
    }


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value
