"""Batch CSV-to-ERP browser reconciliation orchestration."""

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from opskestrel.browser import ERPSearchResult
from opskestrel.reconciliation import (
    ReconciliationReport,
    load_expected_invoices,
    reconcile_invoices,
)
from opskestrel.reconciliation_config import ReconciliationConfig


@dataclass(frozen=True)
class ERPLookupEvidence:
    invoice_id: str
    found: bool
    record_count: int
    duplicate: bool
    screenshot_path: Optional[str]
    error: Optional[str] = None
    attempts: int = 1
    retry_errors: Tuple[str, ...] = ()
    diagnostics_path: Optional[str] = None
    cached: bool = False

    def to_dict(self) -> Dict:
        return {
            "invoice_id": self.invoice_id,
            "found": self.found,
            "record_count": self.record_count,
            "duplicate": self.duplicate,
            "screenshot_path": self.screenshot_path,
            "error": self.error,
            "attempts": self.attempts,
            "retry_errors": list(self.retry_errors),
            "diagnostics_path": self.diagnostics_path,
            "cached": self.cached,
        }

    @classmethod
    def from_dict(cls, payload: Dict) -> "ERPLookupEvidence":
        return cls(
            invoice_id=payload["invoice_id"],
            found=bool(payload["found"]),
            record_count=int(payload["record_count"]),
            duplicate=bool(payload["duplicate"]),
            screenshot_path=payload.get("screenshot_path"),
            error=payload.get("error"),
            attempts=int(payload.get("attempts", 1)),
            retry_errors=tuple(payload.get("retry_errors", [])),
            diagnostics_path=payload.get("diagnostics_path"),
            cached=bool(payload.get("cached", False)),
        )


@dataclass(frozen=True)
class BrowserReconciliationReport:
    expected_csv: str
    reconciliation: ReconciliationReport
    lookups: Tuple[ERPLookupEvidence, ...]
    checkpoint_path: Optional[str] = None

    @property
    def collection_errors(self) -> Tuple[ERPLookupEvidence, ...]:
        return tuple(
            lookup for lookup in self.lookups if lookup.error is not None
        )

    @property
    def cached_lookups(self) -> Tuple[ERPLookupEvidence, ...]:
        return tuple(
            lookup for lookup in self.lookups if lookup.cached
        )

    def to_dict(self) -> Dict:
        return {
            "expected_csv": self.expected_csv,
            "checkpoint_path": self.checkpoint_path,
            "collection": {
                "lookups": len(self.lookups),
                "errors": len(self.collection_errors),
                "cached": len(self.cached_lookups),
                "retried": len(
                    [
                        lookup
                        for lookup in self.lookups
                        if lookup.attempts > 1
                    ]
                ),
            },
            "reconciliation": self.reconciliation.to_dict(),
            "lookups": [
                lookup.to_dict() for lookup in self.lookups
            ],
        }

    @classmethod
    def from_dict(cls, payload: Dict) -> "BrowserReconciliationReport":
        return cls(
            expected_csv=str(payload["expected_csv"]),
            reconciliation=ReconciliationReport.from_dict(
                payload["reconciliation"]
            ),
            lookups=tuple(
                ERPLookupEvidence.from_dict(lookup)
                for lookup in payload.get("lookups", ())
            ),
            checkpoint_path=payload.get("checkpoint_path"),
        )


class ReconciliationCheckpointError(ValueError):
    """Raised when a reconciliation checkpoint is invalid."""


class ReconciliationCheckpoint:
    def __init__(
        self,
        path: Union[str, Path],
        expected_csv: Union[str, Path],
        config_fingerprint: str = "",
    ):
        self.path = Path(path).expanduser().resolve()
        self.expected_csv = Path(expected_csv).expanduser().resolve()
        self.expected_hash = hashlib.sha256(
            self.expected_csv.read_bytes()
        ).hexdigest()
        self.config_fingerprint = config_fingerprint
        self.lookups = {}
        self._load()

    def get(self, invoice_id: str):
        payload = self.lookups.get(invoice_id.casefold())
        if payload is None:
            return None
        evidence_payload = {
            **payload["evidence"],
            "cached": True,
        }
        evidence = ERPLookupEvidence.from_dict(
            evidence_payload
        )
        return tuple(payload["records"]), evidence

    def save(
        self,
        invoice_id: str,
        records,
        evidence: ERPLookupEvidence,
    ) -> None:
        self.lookups[invoice_id.casefold()] = {
            "invoice_id": invoice_id,
            "records": list(records),
            "evidence": evidence.to_dict(),
        }
        self._write()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ReconciliationCheckpointError(
                f"failed to read checkpoint {self.path}: {error}"
            ) from error
        if payload.get("schema_version") != 1:
            raise ReconciliationCheckpointError(
                "unsupported reconciliation checkpoint version"
            )
        if payload.get("expected_sha256") != self.expected_hash:
            raise ReconciliationCheckpointError(
                "checkpoint does not match the current expected CSV"
            )
        if payload.get("config_fingerprint", "") != self.config_fingerprint:
            raise ReconciliationCheckpointError(
                "checkpoint does not match the reconciliation config"
            )
        lookups = payload.get("lookups")
        if not isinstance(lookups, dict):
            raise ReconciliationCheckpointError(
                "checkpoint lookups must be an object"
            )
        self.lookups = lookups

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "expected_csv": str(self.expected_csv),
            "expected_sha256": self.expected_hash,
            "config_fingerprint": self.config_fingerprint,
            "lookups": self.lookups,
        }
        temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def reconcile_expected_csv_with_browser(
    expected_csv: Union[str, Path],
    adapter,
    screenshot_dir: Optional[Union[str, Path]] = None,
    amount_tolerance: Optional[Union[str, Decimal]] = None,
    checkpoint_path: Optional[Union[str, Path]] = None,
    config: Optional[ReconciliationConfig] = None,
) -> BrowserReconciliationReport:
    source_path = Path(expected_csv).expanduser().resolve()
    expected_rows = load_expected_invoices(source_path)
    if config is not None:
        expected_rows = config.map_expected_rows(expected_rows)
    screenshot_root = (
        Path(screenshot_dir).expanduser().resolve()
        if screenshot_dir is not None
        else None
    )
    if screenshot_root is not None:
        screenshot_root.mkdir(parents=True, exist_ok=True)
    checkpoint = (
        ReconciliationCheckpoint(
            checkpoint_path,
            source_path,
            config_fingerprint=(
                config.fingerprint()
                if config is not None
                else ReconciliationConfig().fingerprint()
            ),
        )
        if checkpoint_path is not None
        else None
    )

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
        cached = checkpoint.get(invoice_id) if checkpoint else None
        if cached is not None:
            cached_records, cached_evidence = cached
            erp_rows.extend(cached_records)
            evidence.append(cached_evidence)
            continue

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
                    attempts=int(getattr(error, "attempts", 1)),
                    retry_errors=tuple(
                        getattr(error, "failures", ())
                    ),
                    diagnostics_path=getattr(
                        error,
                        "diagnostics_path",
                        None,
                    ),
                )
            )
            continue

        mapped_records = (
            config.map_erp_rows(result.records)
            if config is not None
            else list(result.records)
        )
        erp_rows.extend(mapped_records)
        result_evidence = _evidence_from_result(result)
        evidence.append(result_evidence)
        if checkpoint is not None:
            checkpoint.save(
                invoice_id,
                mapped_records,
                result_evidence,
            )

    tolerance = (
        amount_tolerance
        if amount_tolerance is not None
        else (
            config.amount_tolerance
            if config is not None
            else Decimal("0.01")
        )
    )
    reconciliation = reconcile_invoices(
        expected_rows,
        erp_rows,
        amount_tolerance=tolerance,
    )
    return BrowserReconciliationReport(
        expected_csv=str(source_path),
        reconciliation=reconciliation,
        lookups=tuple(evidence),
        checkpoint_path=(
            str(checkpoint.path) if checkpoint is not None else None
        ),
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
        attempts=result.attempts,
        retry_errors=result.retry_errors,
    )


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return normalized.lower() or "invoice"
