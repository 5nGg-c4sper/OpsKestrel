"""Persist operator review decisions for reconciliation differences."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Mapping, Optional

from soc_agent.reconciliation import (
    ReconciliationReport,
    ReconciliationStatus,
)


class ReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"


class ReviewError(ValueError):
    """Raised when a review decision or store is invalid."""


@dataclass(frozen=True)
class ReviewRecord:
    invoice_id: str
    status: ReviewStatus
    reviewer: str
    note: str = ""
    updated_at: datetime = None

    def __post_init__(self):
        invoice_id = self.invoice_id.strip()
        reviewer = self.reviewer.strip()
        note = self.note.strip()
        if not invoice_id:
            raise ReviewError("invoice_id must not be empty")
        if not reviewer:
            raise ReviewError("reviewer must not be empty")
        if len(reviewer) > 100:
            raise ReviewError("reviewer must be 100 characters or fewer")
        if len(note) > 2000:
            raise ReviewError("note must be 2000 characters or fewer")
        object.__setattr__(self, "invoice_id", invoice_id)
        object.__setattr__(self, "reviewer", reviewer)
        object.__setattr__(self, "note", note)
        if not isinstance(self.status, ReviewStatus):
            object.__setattr__(self, "status", ReviewStatus(self.status))
        if self.updated_at is None:
            object.__setattr__(
                self,
                "updated_at",
                datetime.now(timezone.utc),
            )

    def to_dict(self) -> Dict:
        return {
            "invoice_id": self.invoice_id,
            "status": self.status.value,
            "reviewer": self.reviewer,
            "note": self.note,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "ReviewRecord":
        return cls(
            invoice_id=str(payload.get("invoice_id", "")),
            status=ReviewStatus(str(payload.get("status", ""))),
            reviewer=str(payload.get("reviewer", "")),
            note=str(payload.get("note", "")),
            updated_at=(
                datetime.fromisoformat(str(payload["updated_at"]))
                if payload.get("updated_at")
                else None
            ),
        )


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self._records: Dict[str, ReviewRecord] = {}
        self._load()

    @property
    def records(self) -> Mapping[str, ReviewRecord]:
        return dict(self._records)

    def get(self, invoice_id: str) -> Optional[ReviewRecord]:
        return self._records.get(invoice_id.strip().casefold())

    def set(
        self,
        invoice_id: str,
        status,
        reviewer: str,
        note: str = "",
    ) -> ReviewRecord:
        record = ReviewRecord(
            invoice_id=invoice_id,
            status=status,
            reviewer=reviewer,
            note=note,
        )
        self._records[record.invoice_id.casefold()] = record
        self._write()
        return record

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ReviewError(
                f"failed to read review store {self.path}: {error}"
            ) from error
        if payload.get("schema_version") != 1:
            raise ReviewError("unsupported review store version")
        reviews = payload.get("reviews")
        if not isinstance(reviews, dict):
            raise ReviewError("review store must contain a reviews object")
        records = {}
        for value in reviews.values():
            if not isinstance(value, dict):
                raise ReviewError("review entries must be objects")
            try:
                record = ReviewRecord.from_dict(value)
            except (ValueError, TypeError) as error:
                raise ReviewError(str(error)) from error
            records[record.invoice_id.casefold()] = record
        self._records = records

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "reviews": {
                key: record.to_dict()
                for key, record in sorted(self._records.items())
            },
        }
        temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def build_review_summary(
    report: ReconciliationReport,
    records: Mapping[str, ReviewRecord],
) -> Dict:
    difference_ids = [
        result.invoice_id
        for result in report.results
        if result.status != ReconciliationStatus.MATCHED
    ]
    pending = 0
    confirmed = 0
    false_positive = 0
    for invoice_id in difference_ids:
        record = records.get(invoice_id.casefold())
        status = record.status if record else ReviewStatus.PENDING
        if status == ReviewStatus.CONFIRMED:
            confirmed += 1
        elif status == ReviewStatus.FALSE_POSITIVE:
            false_positive += 1
        else:
            pending += 1
    reviewed = confirmed + false_positive
    return {
        "total_differences": len(difference_ids),
        "pending": pending,
        "confirmed": confirmed,
        "false_positive": false_positive,
        "reviewed": reviewed,
        "all_reviewed": (
            bool(difference_ids) and reviewed == len(difference_ids)
        ),
    }


def review_payload(record: Optional[ReviewRecord]) -> Dict:
    if record is None:
        return {
            "status": ReviewStatus.PENDING.value,
            "reviewer": None,
            "note": "",
            "updated_at": None,
        }
    return record.to_dict()


def apply_reviews_to_payload(
    payload: Mapping,
    records: Mapping[str, ReviewRecord],
) -> Dict:
    updated = json.loads(json.dumps(payload))
    reconciliation = ReconciliationReport.from_dict(
        updated["reconciliation"]
    )
    for result in updated["reconciliation"]["results"]:
        if result.get("status") == ReconciliationStatus.MATCHED.value:
            result.pop("review", None)
            continue
        result["review"] = review_payload(
            records.get(str(result["invoice_id"]).casefold())
        )
    updated["review_summary"] = build_review_summary(
        reconciliation,
        records,
    )
    return updated
